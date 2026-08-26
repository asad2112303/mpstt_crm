"""M10 exit-gate tests: KPI correctness, exclusions, reconciliation, search,
export audit, role access."""
from datetime import date

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m9_payments import issued_invoice, record_payment


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


async def test_dashboard_role_split(client, user_headers, admin_headers):
    resp = await client.get("/api/v1/dashboard/summary", headers=user_headers)
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "operational" in body
    assert "management" not in body  # finance KPIs are admin-only

    resp = await client.get("/api/v1/dashboard/summary", headers=admin_headers)
    body = resp.json()["data"]
    assert "management" in body
    assert "outstanding_total" in body["management"]


async def test_kpis_reconcile_and_exclude_reversed(
    client, user_headers, admin_headers, db_session
):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]

    # A reversed payment must not count in collections.
    good = await record_payment(client, user_headers, org_id, "200.00")
    bad = await record_payment(client, user_headers, org_id, "999.00")
    await client.post(f"/api/v1/payments/{bad['id']}/reverse",
                      headers=admin_headers, json={"reason": "Bounced"})

    resp = await client.get("/api/v1/reports/collections", headers=admin_headers,
                            params={"date_from": date.today().isoformat(),
                                    "date_to": date.today().isoformat()})
    rows = resp.json()["data"]["rows"]
    numbers = [r["payment_number"] for r in rows]
    assert good["payment_number"] in numbers
    assert bad["payment_number"] not in numbers

    # Receivables report total matches the KPI.
    resp = await client.get("/api/v1/reports/receivables", headers=admin_headers)
    report_total = sum(float(r["outstanding"]) for r in resp.json()["data"]["rows"])
    resp = await client.get("/api/v1/dashboard/summary", headers=admin_headers)
    kpi_total = float(resp.json()["data"]["management"]["outstanding_total"])
    assert abs(report_total - kpi_total) < 0.01


async def test_finance_csv_export_is_audited(client, admin_headers):
    resp = await client.get("/api/v1/reports/receivables", headers=admin_headers,
                            params={"format": "csv"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    resp = await client.get("/api/v1/admin/audit", headers=admin_headers,
                            params={"action": "report.exported"})
    assert any(r["entity_id"] == "receivables" for r in resp.json()["data"])


async def test_non_finance_report_available_to_user(client, user_headers):
    resp = await client.get("/api/v1/reports/pipeline", headers=user_headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/reports/inventory", headers=user_headers)
    assert resp.status_code == 200
    for row in resp.json()["data"]["rows"]:
        assert float(row["available"]) == float(row["on_hand"]) - float(row["reserved"])


async def test_global_search_finds_documents(client, user_headers, admin_headers, db_session):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_name = data["organization"]["name"]

    resp = await client.get("/api/v1/search", headers=user_headers,
                            params={"q": invoice["invoice_number"]})
    kinds = {r["kind"] for r in resp.json()["data"]}
    assert "invoice" in kinds

    resp = await client.get("/api/v1/search", headers=user_headers,
                            params={"q": org_name.split()[0]})
    assert any(r["kind"] in ("customer", "prospect") for r in resp.json()["data"])


async def test_unknown_report_404(client, user_headers):
    resp = await client.get("/api/v1/reports/nope", headers=user_headers)
    assert resp.status_code == 404
