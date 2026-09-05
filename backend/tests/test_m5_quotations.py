"""M5 exit-gate tests: calculations, immutability, revisions, transitions,
conversion paths, PDF snapshot."""
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m2_prospects import create_prospect
from tests.test_m4_conversion import make_sellable_variant


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


async def draft_quote(client, headers, org_id: str, variant_id: str, **overrides) -> dict:
    body = {
        "organization_id": org_id,
        "valid_until": "2099-12-31",
        "items": [
            {"product_variant_id": variant_id, "quantity": "100",
             "unit_price": "12.50", "discount_percent": "10"},
        ],
        **overrides,
    }
    resp = await client.post("/api/v1/quotations", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def send(client, headers, quote_id: str) -> dict:
    resp = await client.post(
        f"/api/v1/quotations/{quote_id}/send",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def test_totals_and_rounding(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    # 100 x 12.50 = 1250; -10% = 1125; +18% tax = 202.50 → 1327.50
    assert quote["subtotal"] == "1250.00"
    assert quote["discount_total"] == "125.00"
    assert quote["tax_total"] == "202.50"
    assert quote["grand_total"] == "1327.50"
    assert quote["quotation_number"].startswith("QT-")
    assert quote["revision_no"] == 1


async def test_send_freezes_quote_and_advances_stage(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])

    sent = await send(client, user_headers, quote["id"])
    assert sent["status"] == "sent"

    # The PDF is rendered from the frozen snapshot, so it downloads without
    # object storage being involved at all.
    resp = await client.get(f"/api/v1/quotations/{quote['id']}/pdf", headers=user_headers)
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF-")

    # Sent quotes are immutable.
    resp = await client.put(
        f"/api/v1/quotations/{quote['id']}", headers=user_headers,
        json={"notes": "tamper"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "QUOTE_NOT_EDITABLE"

    # Prospect stage advanced.
    resp = await client.get(f"/api/v1/prospects/{prospect['id']}", headers=user_headers)
    assert resp.json()["data"]["prospect_profile"]["stage"] == "quotation_sent"

    # Concurrent double-send with a fresh key hits the status guard.
    resp = await client.post(
        f"/api/v1/quotations/{quote['id']}/send",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 409


async def test_pdf_snapshot_survives_catalogue_edits(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    await send(client, user_headers, quote["id"])

    # Later catalogue edits must not change the sent document.
    admin_headers = auth_headers(await seed_profile(db_session, role="admin"))
    await client.patch(
        f"/api/v1/catalogue/variants/{variant['id']}", headers=admin_headers,
        json={"variant_name": "RENAMED AFTER SEND"},
    )
    resp = await client.get(f"/api/v1/quotations/{quote['id']}", headers=user_headers)
    item = resp.json()["data"]["items"][0]
    assert "RENAMED AFTER SEND" not in item["description_snapshot"]

    resp = await client.get(f"/api/v1/quotations/{quote['id']}/pdf", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


async def test_revision_chain(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    await send(client, user_headers, quote["id"])

    resp = await client.post(f"/api/v1/quotations/{quote['id']}/revise", headers=user_headers)
    assert resp.status_code == 201, resp.text
    rev2 = resp.json()["data"]
    assert rev2["revision_no"] == 2
    assert rev2["status"] == "draft"
    assert rev2["parent_quotation_id"] == quote["id"]
    assert rev2["quotation_number"] == quote["quotation_number"]

    # Only one open draft revision at a time.
    resp = await client.post(f"/api/v1/quotations/{quote['id']}/revise", headers=user_headers)
    assert resp.status_code == 409

    # Edit and send rev 2 → rev 1 becomes superseded.
    resp = await client.put(
        f"/api/v1/quotations/{rev2['id']}", headers=user_headers,
        json={"items": [{"product_variant_id": variant["id"], "quantity": "100",
                         "unit_price": "11.00", "discount_percent": "0"}]},
    )
    assert resp.status_code == 200
    await send(client, user_headers, rev2["id"])

    resp = await client.get(f"/api/v1/quotations/{quote['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "superseded"

    resp = await client.get(f"/api/v1/quotations/{quote['id']}/revisions", headers=user_headers)
    revisions = resp.json()["data"]
    assert [r["revision_no"] for r in revisions] == [1, 2]


async def test_accept_requires_sent_and_not_expired(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)

    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    resp = await client.post(f"/api/v1/quotations/{quote['id']}/accept", headers=user_headers)
    assert resp.status_code == 409  # draft cannot be accepted

    expired = await draft_quote(client, user_headers, prospect["id"], variant["id"],
                                valid_until="2020-01-01")
    await send(client, user_headers, expired["id"])
    resp = await client.get(f"/api/v1/quotations/{expired['id']}", headers=user_headers)
    assert resp.json()["data"]["effective_status"] == "expired"
    resp = await client.post(f"/api/v1/quotations/{expired['id']}/accept", headers=user_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "QUOTE_EXPIRED"

    # Reject needs a reason.
    ok_quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    await send(client, user_headers, ok_quote["id"])
    resp = await client.post(f"/api/v1/quotations/{ok_quote['id']}/reject",
                             headers=user_headers, json={})
    assert resp.status_code == 422
    resp = await client.post(f"/api/v1/quotations/{ok_quote['id']}/reject",
                             headers=user_headers, json={"reason": "Price too high"})
    assert resp.status_code == 200


async def test_quote_conversion_converts_prospect(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    await send(client, user_headers, quote["id"])
    await client.post(f"/api/v1/quotations/{quote['id']}/accept", headers=user_headers)

    resp = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["quotation"]["status"] == "converted"
    assert data["order"]["source_quotation_id"] == quote["id"]
    assert data["order"]["grand_total"] == quote["grand_total"]

    # Organization became a customer through the same frozen conversion path.
    resp = await client.get(f"/api/v1/customers/{prospect['id']}", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["prospect_profile"]["stage"] == "won"


async def test_quote_conversion_for_existing_customer(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)

    # First make it a customer via direct conversion.
    from tests.test_m4_conversion import convert_body

    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant["id"]),
    )
    assert resp.status_code == 201

    # A reorder quotation for the customer.
    quote = await draft_quote(client, user_headers, prospect["id"], variant["id"])
    await send(client, user_headers, quote["id"])
    await client.post(f"/api/v1/quotations/{quote['id']}/accept", headers=user_headers)
    resp = await client.post(
        f"/api/v1/quotations/{quote['id']}/convert-to-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["order"]["status"] == "draft"
