"""M9 exit-gate tests: allocations, over-allocation, concurrency, reversal,
receipts, statements."""
import asyncio
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from tests.helpers import auth_headers, seed_profile
from tests.test_m7_invoices import confirmed_order


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


async def issued_invoice(client, user_headers, admin_headers, db_session) -> tuple[dict, dict]:
    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post("/api/v1/invoices/from-order", headers=user_headers,
                             json={"sales_order_id": data["order"]["id"]})
    invoice = resp.json()["data"]
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    return data, resp.json()["data"]


async def record_payment(client, user_headers, org_id: str, amount: str) -> dict:
    resp = await client.post(
        "/api/v1/payments", headers=user_headers,
        json={"organization_id": org_id, "payment_date": date.today().isoformat(),
              "amount": amount, "method": "bank_transfer", "reference": "TRX-001"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def allocate(client, user_headers, payment_id: str, allocations: list) -> object:
    return await client.post(
        f"/api/v1/payments/{payment_id}/allocate",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"allocations": allocations},
    )


async def test_partial_payment_updates_invoice(client, user_headers, admin_headers, db_session):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]
    payment = await record_payment(client, user_headers, org_id, "500.00")

    resp = await allocate(client, user_headers, payment["id"],
                          [{"invoice_id": invoice["id"], "amount": "500.00"}])
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "allocated"

    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    inv = resp.json()["data"]
    assert inv["allocated"] == "500.00"
    assert inv["derived_status"] == "partially_paid"
    # grand_total 1327.50 - 500 = 827.50
    assert inv["outstanding"] == "827.50"


async def test_one_payment_across_multiple_invoices_and_full_payment(
    client, user_headers, admin_headers, db_session
):
    data1, invoice1 = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data1["organization"]["id"]

    # Second invoice for the SAME organization (direct reorder).
    resp = await client.get(f"/api/v1/orders/{data1['order']['id']}", headers=user_headers)
    variant_id = resp.json()["data"]["items"][0]["product_variant_id"]
    resp = await client.post(
        "/api/v1/orders", headers=user_headers,
        json={"organization_id": org_id,
              "items": [{"product_variant_id": variant_id, "quantity": "10",
                         "unit_price": "100.00"}]},
    )
    order2 = resp.json()["data"]
    await client.post(f"/api/v1/orders/{order2['id']}/confirm",
                      headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={})
    resp = await client.post("/api/v1/invoices/from-order", headers=user_headers,
                             json={"sales_order_id": order2["id"]})
    invoice2_draft = resp.json()["data"]
    resp = await client.post(
        f"/api/v1/invoices/{invoice2_draft['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    invoice2 = resp.json()["data"]

    # One payment covers invoice1 fully (1327.50) + invoice2 fully (1180.00).
    payment = await record_payment(client, user_headers, org_id, "2507.50")
    resp = await allocate(client, user_headers, payment["id"], [
        {"invoice_id": invoice1["id"], "amount": "1327.50"},
        {"invoice_id": invoice2["id"], "amount": "1180.00"},
    ])
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "allocated"
    assert resp.json()["data"]["unallocated"] == "0.00"

    for inv_id in (invoice1["id"], invoice2["id"]):
        resp = await client.get(f"/api/v1/invoices/{inv_id}", headers=user_headers)
        assert resp.json()["data"]["derived_status"] == "paid"


async def test_multiple_payments_to_one_invoice(client, user_headers, admin_headers, db_session):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]

    p1 = await record_payment(client, user_headers, org_id, "1000.00")
    await allocate(client, user_headers, p1["id"],
                   [{"invoice_id": invoice["id"], "amount": "1000.00"}])
    p2 = await record_payment(client, user_headers, org_id, "327.50")
    resp = await allocate(client, user_headers, p2["id"],
                          [{"invoice_id": invoice["id"], "amount": "327.50"}])
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    assert resp.json()["data"]["derived_status"] == "paid"


async def test_over_allocation_blocked_both_ways(client, user_headers, admin_headers, db_session):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]

    # More than the payment balance.
    payment = await record_payment(client, user_headers, org_id, "100.00")
    resp = await allocate(client, user_headers, payment["id"],
                          [{"invoice_id": invoice["id"], "amount": "150.00"}])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "OVER_ALLOCATION"

    # More than the invoice outstanding.
    big = await record_payment(client, user_headers, org_id, "99999.00")
    resp = await allocate(client, user_headers, big["id"],
                          [{"invoice_id": invoice["id"], "amount": "5000.00"}])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "OVER_ALLOCATION"


async def test_concurrent_allocations_cannot_overpay_invoice(
    client, user_headers, admin_headers, db_session
):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]
    # Invoice outstanding is 1327.50; two payments of 1000 each race to allocate 1000.
    p1 = await record_payment(client, user_headers, org_id, "1000.00")
    p2 = await record_payment(client, user_headers, org_id, "1000.00")

    from app.core import db as db_module
    from app.main import create_app

    async def attempt(payment_id: str) -> int:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/payments/{payment_id}/allocate",
                headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
                json={"allocations": [{"invoice_id": invoice["id"], "amount": "1000.00"}]},
            )
            return resp.status_code

    results = await asyncio.gather(attempt(p1["id"]), attempt(p2["id"]))
    await db_module.dispose_engine()
    assert sorted(results) == [200, 409]

    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    assert float(resp.json()["data"]["allocated"]) == 1000.0


async def test_reversal_restores_outstanding_and_is_admin_only(
    client, user_headers, admin_headers, db_session
):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]
    payment = await record_payment(client, user_headers, org_id, "1327.50")
    await allocate(client, user_headers, payment["id"],
                   [{"invoice_id": invoice["id"], "amount": "1327.50"}])

    # Operational user cannot reverse.
    resp = await client.post(f"/api/v1/payments/{payment['id']}/reverse",
                             headers=user_headers, json={"reason": "sneaky"})
    assert resp.status_code == 403

    # Admin reversal needs a reason and restores the invoice outstanding.
    resp = await client.post(f"/api/v1/payments/{payment['id']}/reverse",
                             headers=admin_headers, json={})
    assert resp.status_code == 422
    resp = await client.post(f"/api/v1/payments/{payment['id']}/reverse",
                             headers=admin_headers, json={"reason": "Cheque bounced"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "reversed"

    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    inv = resp.json()["data"]
    assert float(inv["allocated"]) == 0.0
    assert float(inv["outstanding"]) == float(inv["grand_total"])


async def test_receipt_and_statement_reconcile(client, user_headers, admin_headers, db_session):
    data, invoice = await issued_invoice(client, user_headers, admin_headers, db_session)
    org_id = data["organization"]["id"]
    payment = await record_payment(client, user_headers, org_id, "1327.50")
    await allocate(client, user_headers, payment["id"],
                   [{"invoice_id": invoice["id"], "amount": "1327.50"}])

    resp = await client.post(f"/api/v1/payments/{payment['id']}/receipt", headers=user_headers)
    assert resp.status_code == 201, resp.text
    receipt = resp.json()["data"]["receipt"]
    assert receipt["receipt_number"].startswith("RCP-")

    resp = await client.get(f"/api/v1/payments/{payment['id']}/receipt/pdf", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"

    # Statement: invoice debit and payment credit net to zero.
    resp = await client.get(f"/api/v1/customers/{org_id}/statement", headers=user_headers)
    statement = resp.json()["data"]
    kinds = {r["kind"] for r in statement["rows"]}
    assert {"invoice", "payment"} <= kinds
    assert float(statement["closing_balance"]) == 0.0

    # Receivables aging no longer lists the paid invoice.
    resp = await client.get("/api/v1/receivables", headers=user_headers)
    rows = resp.json()["data"]["rows"]
    assert all(r["invoice_id"] != invoice["id"] for r in rows)
