"""M12 exit-gate tests: staged import, validation, duplicates, reconciliation."""
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


def csv_bytes(rows: list[str], header: str | None = None) -> bytes:
    header = header or ("name,org_type,city,phone,contact_name,contact_phone,"
                        "customer_since,payment_terms_days")
    return ("\n".join([header, *rows]) + "\n").encode()


async def upload(client, admin_headers, content: bytes, filename: str = "legacy.csv"):
    return await client.post(
        "/api/v1/admin/imports", headers=admin_headers,
        files={"file": (filename, content, "text/csv")},
    )


async def test_import_is_admin_only(client, user_headers):
    resp = await upload(client, user_headers, csv_bytes(["X Hospital,hospital,,,,,,"]))
    assert resp.status_code == 403


async def test_unknown_column_blocked(client, admin_headers):
    resp = await upload(client, admin_headers,
                        csv_bytes(["A,hospital"], header="name,mystery_column"))
    assert resp.status_code == 422
    assert "mystery_column" in resp.json()["error"]["message"]


async def test_stage_validate_approve_reconcile(client, admin_headers, db_session):
    marker = uuid.uuid4().hex[:6]
    content = csv_bytes([
        f"Import Hosp {marker},hospital,Rawalpindi,0300-1231234,Mr Store,0301-9998887,,",
        f"Import Lab {marker},laboratory,Lahore,,,,2025-06-01,45",   # confirmed customer
        f"Bad Row {marker},spaceship,,,,,,",                          # invalid org_type
        ",hospital,,,,,,",                                            # missing name
    ])
    resp = await upload(client, admin_headers, content)
    assert resp.status_code == 201, resp.text
    batch = resp.json()["data"]
    assert batch["source_count"] == 4
    assert batch["ready_count"] == 2
    assert batch["error_count"] == 2
    assert batch["status"] == "pending_review"

    error_rows = [r for r in batch["rows"] if r["status"] == "error"]
    assert len(error_rows) == 2
    assert any("org_type" in " ".join(r["validation_errors"]) for r in error_rows)

    # Approve: ready rows import; counts reconcile (ready = imported + rejected).
    resp = await client.post(f"/api/v1/admin/imports/{batch['id']}/approve",
                             headers=admin_headers)
    assert resp.status_code == 200, resp.text
    done = resp.json()["data"]
    assert done["status"] == "imported"
    assert done["ready_count"] == done["imported_count"] + done["rejected_count"]
    assert done["imported_count"] == 2

    # Prospect defaulted; customer only where explicitly confirmed.
    resp = await client.get("/api/v1/prospects", headers=admin_headers,
                            params={"search": f"Import Hosp {marker}"})
    assert len(resp.json()["data"]) == 1
    assert resp.json()["data"][0]["prospect_profile"]["stage"] == "targeted"

    resp = await client.get("/api/v1/customers", headers=admin_headers,
                            params={"search": f"Import Lab {marker}"})
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["customer_profile"]["customer_since"] == "2025-06-01"
    assert rows[0]["customer_profile"]["payment_terms_days"] == 45

    # Re-approval blocked.
    resp = await client.post(f"/api/v1/admin/imports/{batch['id']}/approve",
                             headers=admin_headers)
    assert resp.status_code == 409


async def test_duplicates_flagged_never_auto_merged(client, admin_headers, db_session):
    marker = uuid.uuid4().hex[:6]
    first = csv_bytes([f"Dup Clinic {marker},clinic,Multan,0345-5556667,,,,"])
    resp = await upload(client, admin_headers, first)
    batch1 = resp.json()["data"]
    await client.post(f"/api/v1/admin/imports/{batch1['id']}/approve", headers=admin_headers)

    # Same name+phone again → flagged duplicate, skipped by default.
    resp = await upload(client, admin_headers, first, filename="again.csv")
    batch2 = resp.json()["data"]
    assert batch2["duplicate_count"] == 1
    dup_row = batch2["rows"][0]
    assert dup_row["status"] == "duplicate"
    assert dup_row["duplicate_of"] is not None

    resp = await client.post(f"/api/v1/admin/imports/{batch2['id']}/approve",
                             headers=admin_headers)
    done = resp.json()["data"]
    assert done["imported_count"] == 0
    assert done["rows"][0]["status"] == "skipped"

    # Only ONE organization with that name exists — never merged, never doubled.
    resp = await client.get("/api/v1/prospects", headers=admin_headers,
                            params={"search": f"Dup Clinic {marker}"})
    assert len(resp.json()["data"]) == 1
