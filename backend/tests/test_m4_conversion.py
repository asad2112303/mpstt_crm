"""M4 exit-gate tests: atomic conversion, idempotency, concurrency, history."""
import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from tests.helpers import auth_headers, seed_profile
from tests.test_m2_prospects import create_prospect
from tests.test_m3_catalogue import seed_catalogue


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


async def make_sellable_variant(client, db_session) -> dict:
    admin_headers = auth_headers(await seed_profile(db_session, role="admin"))
    ids = await seed_catalogue(client, admin_headers)
    resp = await client.post(
        f"/api/v1/catalogue/products/{ids['product']['id']}/variants",
        headers=admin_headers,
        json={"variant_code": f"V{uuid.uuid4().hex[:8]}", "variant_name": f"Yellow {uuid.uuid4().hex[:4]}",
              "attributes": {"colour": "Yellow", "thickness_micron": 25}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def convert_body(variant_id: str) -> dict:
    return {
        "items": [
            {"product_variant_id": variant_id, "quantity": "100",
             "unit_price": "12.50", "discount_percent": "10"},
        ],
        "customer_po_number": "PO-778899",
        "payment_terms_days": 45,
    }


async def test_conversion_creates_customer_and_order_atomically(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)

    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant["id"]),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    org = data["organization"]
    order = data["order"]

    assert org["lifecycle_status"] == "customer"
    assert org["converted_at"] is not None
    assert org["customer_profile"]["customer_code"].startswith("CUST-")
    assert org["customer_profile"]["payment_terms_days"] == 45
    # Prospect history is preserved and closed as Won.
    assert org["prospect_profile"]["stage"] == "won"

    assert order["order_number"].startswith("ORD-")
    assert order["status"] == "draft"
    # 100 * 12.50 = 1250 gross, 10% discount = 125, net 1125, tax 18% = 202.50
    assert order["subtotal"] == "1250.00"
    assert order["discount_total"] == "125.00"
    assert order["tax_total"] == "202.50"
    assert order["grand_total"] == "1327.50"
    assert order["items"][0]["specification_snapshot"]["colour"] == "Yellow"


async def test_conversion_requires_idempotency_key(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers=user_headers, json=convert_body(variant["id"]),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_conversion_retry_replays_same_result(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    key = str(uuid.uuid4())
    body = convert_body(variant["id"])

    first = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": key}, json=body,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": key}, json=body,
    )
    assert second.status_code == 201
    assert (
        second.json()["data"]["order"]["order_number"]
        == first.json()["data"]["order"]["order_number"]
    )


async def test_double_conversion_with_new_key_conflicts(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant["id"]),
    )
    assert resp.status_code == 201
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant["id"]),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_CUSTOMER"


async def test_simultaneous_conversions_create_one_customer(client, user_headers, db_session):
    """Two racing conversion attempts: exactly one wins, one 409s."""
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)

    from app.core import db as db_module
    from app.main import create_app

    async def attempt() -> int:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
                headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
                json=convert_body(variant["id"]),
            )
            return resp.status_code

    results = await asyncio.gather(attempt(), attempt())
    await db_module.dispose_engine()
    assert sorted(results) == [201, 409]

    from sqlalchemy import text

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM crm.customer_profiles WHERE organization_id = :id"),
            {"id": prospect["id"]},
        )
    ).scalar_one()
    assert count == 1
    orders = (
        await db_session.execute(
            text("SELECT count(*) FROM crm.sales_orders WHERE organization_id = :id"),
            {"id": prospect["id"]},
        )
    ).scalar_one()
    assert orders == 1


async def test_failed_validation_rolls_back_everything(client, user_headers, db_session):
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"items": [{"product_variant_id": str(uuid.uuid4()),
                         "quantity": "10", "unit_price": "5.00"}]},
    )
    assert resp.status_code == 422

    check = await client.get(f"/api/v1/prospects/{prospect['id']}", headers=user_headers)
    data = check.json()["data"]
    assert data["lifecycle_status"] == "prospect"
    assert data["customer_profile"] is None


async def test_customer_screens_exclude_prospects_and_history_survives(
    client, user_headers, db_session
):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    org_id = prospect["id"]

    # History before conversion.
    await client.post(
        f"/api/v1/organizations/{org_id}/contacts", headers=user_headers,
        json={"full_name": "Ms Procurement", "phone_primary": "0300-5556667"},
    )
    await client.post(
        f"/api/v1/prospects/{org_id}/activities", headers=user_headers,
        json={"activity_type": "visit", "outcome": "Initial meeting"},
    )

    # Not visible in customers yet.
    resp = await client.get(f"/api/v1/customers/{org_id}", headers=user_headers)
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/prospects/{org_id}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant["id"]),
    )
    assert resp.status_code == 201

    # Now a customer; contacts and timeline history intact on the SAME record.
    resp = await client.get(f"/api/v1/customers/{org_id}", headers=user_headers)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/organizations/{org_id}/contacts", headers=user_headers)
    assert any(c["full_name"] == "Ms Procurement" for c in resp.json()["data"])
    resp = await client.get(f"/api/v1/customers/{org_id}/timeline", headers=user_headers)
    kinds = {e["kind"] for e in resp.json()["data"]}
    assert "order" in kinds and "activity.visit" in kinds

    # Gone from the prospect list.
    resp = await client.get("/api/v1/prospects", headers=user_headers,
                            params={"search": prospect["org_code"]})
    assert all(p["id"] != org_id for p in resp.json()["data"])
