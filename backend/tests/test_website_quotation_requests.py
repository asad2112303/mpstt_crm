"""Website intake inbox — public.quotation_requests.

The table is the website's, not the CRM's, so it is created from the DDL of
record (supabase/sql/quotation_requests.sql) rather than by Alembic. Tests
apply that same file so what runs here is exactly what runs in Supabase.
"""
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text

from tests.conftest import TEST_DATABASE_URL
from tests.helpers import auth_headers, seed_profile

DDL = (
    Path(__file__).resolve().parents[2] / "supabase" / "sql" / "quotation_requests.sql"
).read_text()

# Exactly the columns the website's /api/quote sends — nothing else.
WEBSITE_COLUMNS = (
    "full_name, organization, phone, email, organization_type, requirement, "
    "consent, source_page, product_slug, category_slug, product_name, intent"
)
PAYLOAD = {
    "full_name": "Browser Buyer",
    "organization": "Browser Clinic",
    "phone": "+92 300 1234567",
    "email": "buyer@example.com",
    "organization_type": "Clinic",
    "requirement": "I'm interested in Hand Sanitizer.",
    "consent": True,
    "source_page": "/contact?intent=quotation&product=hand-sanitizer",
    "product_slug": "hand-sanitizer",
    "category_slug": "cleaning-hygiene",
    "product_name": "Hand Sanitizer",
    "intent": "quotation",
}


@pytest.fixture(autouse=True)
async def quotation_requests_table():
    """Recreate the website table from its DDL of record before each test.

    Applied over a plain asyncpg connection: the file is several statements and
    contains ``::text`` casts, which SQLAlchemy's ``text()`` would read as bind
    parameters.
    """
    conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
    try:
        await conn.execute("DROP TABLE IF EXISTS public.quotation_requests CASCADE")
        await conn.execute(DDL)
    finally:
        await conn.close()
    yield


async def submit(db_session, **overrides) -> str:
    """Insert the way the website does: only its own columns, defaults for the rest."""
    data = {**PAYLOAD, **overrides}
    placeholders = ", ".join(f":{k}" for k in PAYLOAD)
    ref = (
        await db_session.execute(
            text(
                f"INSERT INTO public.quotation_requests ({WEBSITE_COLUMNS}) "
                f"VALUES ({placeholders}) RETURNING reference"
            ),
            data,
        )
    ).scalar_one()
    await db_session.commit()
    return ref


async def test_website_row_lands_in_the_inbox(client, db_session):
    reference = await submit(db_session)
    uid = await seed_profile(db_session)

    resp = await client.get("/api/v1/quotation-requests", headers=auth_headers(uid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    row = body["data"][0]

    # Database-generated, never sent by the website.
    assert row["reference"] == reference
    assert reference.startswith("MPSTT-")
    assert row["status"] == "new"
    assert row["contacted_at"] is None
    assert row["internal_notes"] is None
    assert row["created_at"] and row["updated_at"] and row["consent_at"]
    # Submitted fields survive the round trip.
    assert row["organization"] == "Browser Clinic"
    assert row["product_name"] == "Hand Sanitizer"
    assert row["intent"] == "quotation"


async def test_inbox_requires_authentication(client, db_session):
    await submit(db_session)
    resp = await client.get("/api/v1/quotation-requests")
    assert resp.status_code == 401


async def test_the_crm_cannot_create_requests(client, db_session):
    uid = await seed_profile(db_session)
    resp = await client.post(
        "/api/v1/quotation-requests", json=PAYLOAD, headers=auth_headers(uid)
    )
    # Only the website writes new requests.
    assert resp.status_code == 405


async def test_search_and_status_filters(client, db_session):
    await submit(db_session)
    await submit(db_session, organization="Other Hospital", product_name="Waste Bags")
    uid = await seed_profile(db_session)
    headers = auth_headers(uid)

    hits = await client.get(
        "/api/v1/quotation-requests", params={"search": "Waste"}, headers=headers
    )
    assert [r["organization"] for r in hits.json()["data"]] == ["Other Hospital"]

    by_ref = await client.get(
        "/api/v1/quotation-requests", params={"search": "MPSTT-"}, headers=headers
    )
    assert by_ref.json()["meta"]["total"] == 2

    new_only = await client.get(
        "/api/v1/quotation-requests", params={"status": "new"}, headers=headers
    )
    assert new_only.json()["meta"]["total"] == 2

    won_only = await client.get(
        "/api/v1/quotation-requests", params={"status": "won"}, headers=headers
    )
    assert won_only.json()["meta"]["total"] == 0

    bad = await client.get(
        "/api/v1/quotation-requests", params={"status": "nonsense"}, headers=headers
    )
    assert bad.status_code == 422


async def test_summary_counts_every_status(client, db_session):
    await submit(db_session)
    await submit(db_session)
    uid = await seed_profile(db_session)
    headers = auth_headers(uid)

    request_id = (
        await client.get("/api/v1/quotation-requests", headers=headers)
    ).json()["data"][0]["id"]
    await client.patch(
        f"/api/v1/quotation-requests/{request_id}", json={"status": "won"}, headers=headers
    )

    data = (await client.get("/api/v1/quotation-requests/summary", headers=headers)).json()["data"]
    assert data["total"] == 2
    assert data["by_status"]["new"] == 1
    assert data["by_status"]["won"] == 1
    assert data["by_status"]["lost"] == 0  # unused statuses still reported
    assert data["new_count"] == 1
    assert data["open_count"] == 1  # 'won' is no longer open


async def test_status_update_stamps_contacted_at_once(client, db_session):
    await submit(db_session)
    uid = await seed_profile(db_session)
    headers = auth_headers(uid)
    request_id = (
        await client.get("/api/v1/quotation-requests", headers=headers)
    ).json()["data"][0]["id"]

    first = await client.patch(
        f"/api/v1/quotation-requests/{request_id}",
        json={"status": "contacted", "internal_notes": "Called, wants 200 litres."},
        headers=headers,
    )
    assert first.status_code == 200
    contacted_at = first.json()["data"]["contacted_at"]
    assert contacted_at is not None
    assert first.json()["data"]["internal_notes"] == "Called, wants 200 litres."

    second = await client.patch(
        f"/api/v1/quotation-requests/{request_id}",
        json={"status": "quotation_sent"},
        headers=headers,
    )
    assert second.json()["data"]["status"] == "quotation_sent"
    # First pickup is recorded once, not moved on every later step.
    assert second.json()["data"]["contacted_at"] == contacted_at
    # Notes are untouched by a status-only patch.
    assert second.json()["data"]["internal_notes"] == "Called, wants 200 litres."


async def test_update_is_audited_and_rejects_unknown_status(client, db_session):
    await submit(db_session)
    uid = await seed_profile(db_session)
    headers = auth_headers(uid)
    request_id = (
        await client.get("/api/v1/quotation-requests", headers=headers)
    ).json()["data"][0]["id"]

    bad = await client.patch(
        f"/api/v1/quotation-requests/{request_id}", json={"status": "archived"}, headers=headers
    )
    assert bad.status_code == 422

    await client.patch(
        f"/api/v1/quotation-requests/{request_id}", json={"status": "lost"}, headers=headers
    )
    # audit_log is append-only and shared by the whole session, so scope the
    # assertion to this request rather than counting every row in the table.
    logged = (
        await db_session.execute(
            text(
                "SELECT action, entity_type, new_data FROM crm.audit_log "
                "WHERE action = 'quotation_request.updated' AND entity_id = :rid"
            ),
            {"rid": request_id},
        )
    ).all()
    assert len(logged) == 1  # the rejected patch wrote nothing
    assert logged[0].entity_type == "quotation_request"
    assert logged[0].new_data["status"] == "lost"


async def test_updated_at_trigger_fires_on_crm_edits(client, db_session):
    await submit(db_session)
    uid = await seed_profile(db_session)
    headers = auth_headers(uid)
    row = (await client.get("/api/v1/quotation-requests", headers=headers)).json()["data"][0]

    patched = await client.patch(
        f"/api/v1/quotation-requests/{row['id']}",
        json={"internal_notes": "Chased by email."},
        headers=headers,
    )
    body = patched.json()["data"]
    assert body["updated_at"] > row["updated_at"]  # DB trigger, not the app
    assert body["created_at"] == row["created_at"]
    assert body["status"] == "new"  # notes-only patch leaves status alone


async def test_missing_request_is_404(client, db_session):
    uid = await seed_profile(db_session)
    resp = await client.get(
        "/api/v1/quotation-requests/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(uid),
    )
    assert resp.status_code == 404
