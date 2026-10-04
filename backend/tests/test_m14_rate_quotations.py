"""Rate quotations: products and per-unit rates, with nothing to total."""
import re
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m13_direct_billing import make_tracked_variant


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


def idem(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": str(uuid.uuid4())}


async def test_rate_list_quotes_per_unit_and_never_totals(
    client, user_headers, admin_headers, db_session
):
    a = await make_tracked_variant(client, admin_headers, db_session, colour="Red")
    b = await make_tracked_variant(client, admin_headers, db_session, colour="Yellow")

    resp = await client.post(
        "/api/v1/rate-quotations", headers=idem(user_headers),
        json={
            "customer_name": "Shifa International Hospital",
            "contact_person": "Procurement",
            "valid_until": "2026-12-31",
            "items": [
                {"product_variant_id": a["id"], "unit_price": "950"},
                {"product_variant_id": b["id"], "unit_price": "1200.50"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    quote = resp.json()["data"]
    assert quote["quotation_number"].startswith("RQ-")
    assert quote["status"] == "issued"
    assert len(quote["items"]) == 2

    # A rate per unit, and no quantity or line total anywhere in the payload.
    first = quote["items"][0]
    assert first["unit_price"] == "950.00"
    assert first["uom_code"]
    assert "quantity" not in first
    assert "line_total" not in first
    for banned in ("subtotal", "grand_total", "tax_total", "discount_total"):
        assert banned not in quote

    pdf = await client.get(f"/api/v1/rate-quotations/{quote['id']}/pdf", headers=user_headers)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"


async def test_the_document_shows_rates_and_no_total(
    client, user_headers, admin_headers, db_session
):
    """Render the template directly: no Qty column, no Amount, no total band."""
    from app.services.pdf import render_html

    variant = await make_tracked_variant(client, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/rate-quotations", headers=idem(user_headers),
        json={"customer_name": "Rate Check Clinic",
              "items": [{"product_variant_id": variant["id"], "unit_price": "480"}]},
    )
    quote_id = resp.json()["data"]["id"]

    detail = await client.get(f"/api/v1/rate-quotations/{quote_id}", headers=user_headers)
    assert detail.status_code == 200

    from sqlalchemy import select

    from app.models.rate_quotes import RateQuotation

    stored = (
        await db_session.execute(
            select(RateQuotation).where(RateQuotation.id == uuid.UUID(quote_id))
        )
    ).scalar_one()
    html = render_html("rate-quotation.html", stored.pdf_context)
    body = html[html.index("<body>"):]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))

    assert "RATE LIST" in text
    assert "Rate (PKR)" in text
    assert "480.00" in text
    assert "per " in text  # "per PCS"
    # The things a rate list must not carry.
    assert "TOTAL AMOUNT" not in text
    assert "AMOUNT DUE" not in text
    assert ">Qty<" not in body
    assert "Grand" not in text


async def test_rate_list_needs_no_customer_record(client, user_headers, admin_headers, db_session):
    variant = await make_tracked_variant(client, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/rate-quotations", headers=idem(user_headers),
        json={"items": [{"product_variant_id": variant["id"], "unit_price": "100"}]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["organization_id"] is None
    assert resp.json()["data"]["customer_name"] is None


async def test_repeated_submit_makes_one_rate_list(client, user_headers, admin_headers, db_session):
    variant = await make_tracked_variant(client, admin_headers, db_session)
    headers = idem(user_headers)
    payload = {"customer_name": "Retry Clinic",
               "items": [{"product_variant_id": variant["id"], "unit_price": "100"}]}

    first = await client.post("/api/v1/rate-quotations", headers=headers, json=payload)
    again = await client.post("/api/v1/rate-quotations", headers=headers, json=payload)
    assert first.status_code == 201
    assert again.json()["data"]["quotation_number"] == first.json()["data"]["quotation_number"]

    listed = await client.get("/api/v1/rate-quotations", headers=user_headers,
                              params={"search": "Retry Clinic"})
    assert listed.json()["meta"]["total"] == 1


async def test_rates_are_frozen_against_later_price_changes(
    client, user_headers, admin_headers, db_session
):
    variant = await make_tracked_variant(client, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/rate-quotations", headers=idem(user_headers),
        json={"customer_name": "Frozen Co",
              "items": [{"product_variant_id": variant["id"], "unit_price": "500"}]},
    )
    quote_id = resp.json()["data"]["id"]

    renamed = await client.patch(
        f"/api/v1/catalogue/variants/{variant['id']}", headers=admin_headers,
        json={"variant_name": "Renamed After Quoting"},
    )
    assert renamed.status_code == 200, renamed.text

    again = await client.get(f"/api/v1/rate-quotations/{quote_id}", headers=user_headers)
    assert again.json()["data"]["items"][0]["unit_price"] == "500.00"
    assert "Renamed After Quoting" not in again.json()["data"]["items"][0]["description_snapshot"]


async def test_cancelling_a_rate_list(client, user_headers, admin_headers, db_session):
    variant = await make_tracked_variant(client, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/rate-quotations", headers=idem(user_headers),
        json={"items": [{"product_variant_id": variant["id"], "unit_price": "100"}]},
    )
    quote_id = resp.json()["data"]["id"]
    cancelled = await client.post(
        f"/api/v1/rate-quotations/{quote_id}/cancel", headers=user_headers,
        json={"reason": "Rates revised"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    blocked = await client.post(
        f"/api/v1/rate-quotations/{quote_id}/cancel", headers=user_headers,
        json={"reason": "Again"},
    )
    assert blocked.status_code == 409
