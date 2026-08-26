"""M6 exit-gate tests: reservations, concurrency, cancellation, adjustments."""
import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from tests.helpers import auth_headers, seed_profile
from tests.test_m2_prospects import create_prospect
from tests.test_m4_conversion import convert_body, make_sellable_variant


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


async def ensure_warehouse(client, admin_headers) -> dict:
    resp = await client.get("/api/v1/inventory/warehouses", headers=admin_headers)
    existing = [w for w in resp.json()["data"] if w["is_active"]]
    if existing:
        return existing[0]
    resp = await client.post(
        "/api/v1/inventory/warehouses", headers=admin_headers,
        json={"code": "MAIN", "name": "Main Warehouse", "address": "Islamabad"},
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def stock_up(client, admin_headers, warehouse_id: str, variant_id: str, qty: str):
    resp = await client.post(
        "/api/v1/inventory/adjustments", headers=admin_headers,
        json={"warehouse_id": warehouse_id, "product_variant_id": variant_id,
              "quantity": qty, "reason": "Opening stock", "movement_type": "opening"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def make_customer_with_order(client, user_headers, db_session, variant_id: str) -> dict:
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        f"/api/v1/prospects/{prospect['id']}/convert-to-customer-order",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json=convert_body(variant_id),
    )
    assert resp.status_code == 201
    return resp.json()["data"]


async def test_confirm_reserves_stock(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "500")

    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    order = data["order"]

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "confirmed"

    resp = await client.get("/api/v1/inventory/balances", headers=user_headers,
                            params={"search": variant["variant_name"]})
    row = next(r for r in resp.json()["data"] if r["product_variant_id"] == variant["id"])
    assert float(row["reserved"]) >= 100.0
    assert float(row["available"]) == float(row["on_hand"]) - float(row["reserved"])

    # Double confirm blocked by status guard.
    resp = await client.post(
        f"/api/v1/orders/{order['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    assert resp.status_code == 409


async def test_insufficient_stock_blocks_confirmation(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "10")  # order needs 100

    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    resp = await client.post(
        f"/api/v1/orders/{data['order']['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INSUFFICIENT_STOCK"

    # Order remains draft; nothing reserved.
    resp = await client.get(f"/api/v1/orders/{data['order']['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "draft"


async def test_concurrent_confirmations_one_wins_when_stock_covers_one(
    client, user_headers, admin_headers, db_session
):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "150")  # each order needs 100

    order_a = (await make_customer_with_order(client, user_headers, db_session, variant["id"]))["order"]
    order_b = (await make_customer_with_order(client, user_headers, db_session, variant["id"]))["order"]

    from app.core import db as db_module
    from app.main import create_app

    async def attempt(order_id: str) -> int:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/orders/{order_id}/confirm",
                headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
            )
            return resp.status_code

    results = await asyncio.gather(attempt(order_a["id"]), attempt(order_b["id"]))
    await db_module.dispose_engine()
    assert sorted(results) == [200, 409]


async def test_cancellation_releases_reservations(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "300")

    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    order = data["order"]
    await client.post(
        f"/api/v1/orders/{order['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )

    before = await client.get("/api/v1/inventory/balances", headers=user_headers,
                              params={"search": variant["variant_name"]})
    reserved_before = float(next(
        r for r in before.json()["data"] if r["product_variant_id"] == variant["id"]
    )["reserved"])

    resp = await client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=user_headers,
        json={"reason": "Customer withdrew the PO"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    after = await client.get("/api/v1/inventory/balances", headers=user_headers,
                             params={"search": variant["variant_name"]})
    reserved_after = float(next(
        r for r in after.json()["data"] if r["product_variant_id"] == variant["id"]
    )["reserved"])
    assert reserved_after == reserved_before - 100.0


async def test_adjustment_rules(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)

    # Operational user cannot adjust stock.
    resp = await client.post(
        "/api/v1/inventory/adjustments", headers=user_headers,
        json={"warehouse_id": wh["id"], "product_variant_id": variant["id"],
              "quantity": "5", "reason": "sneaky"},
    )
    assert resp.status_code == 403

    # Negative beyond on-hand blocked.
    resp = await client.post(
        "/api/v1/inventory/adjustments", headers=admin_headers,
        json={"warehouse_id": wh["id"], "product_variant_id": variant["id"],
              "quantity": "-50", "reason": "Damage write-off"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NEGATIVE_STOCK"

    await stock_up(client, admin_headers, wh["id"], variant["id"], "40")
    resp = await client.post(
        "/api/v1/inventory/adjustments", headers=admin_headers,
        json={"warehouse_id": wh["id"], "product_variant_id": variant["id"],
              "quantity": "-15", "reason": "Damaged in storage", "reference": "DMG-01"},
    )
    assert resp.status_code == 201
    assert float(resp.json()["data"]["on_hand"]) == 25.0

    # Movement history shows both signed entries.
    resp = await client.get("/api/v1/inventory/movements", headers=admin_headers,
                            params={"product_variant_id": variant["id"]})
    types = [m["movement_type"] for m in resp.json()["data"]]
    assert "opening" in types and "adjustment" in types


async def test_direct_order_requires_customer(client, user_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    prospect = await create_prospect(client, user_headers)
    resp = await client.post(
        "/api/v1/orders", headers=user_headers,
        json={"organization_id": prospect["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "10",
                         "unit_price": "9.99"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "NOT_A_CUSTOMER"


async def test_manual_status_guards(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "200")
    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    order = data["order"]

    # Draft cannot be marked preparing.
    resp = await client.post(f"/api/v1/orders/{order['id']}/mark-preparing", headers=user_headers)
    assert resp.status_code == 409

    await client.post(
        f"/api/v1/orders/{order['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    resp = await client.post(f"/api/v1/orders/{order['id']}/mark-preparing", headers=user_headers)
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/orders/{order['id']}/mark-ready", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"


async def test_draft_order_editable_until_confirmed(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "500")
    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    order = data["order"]

    # Draft: items/qty editable, totals recalculated server-side.
    resp = await client.put(
        f"/api/v1/orders/{order['id']}", headers=user_headers,
        json={"customer_po_number": "PO-EDITED",
              "items": [{"product_variant_id": variant["id"], "quantity": "10",
                         "unit_price": "100.00", "discount_percent": "0"}]},
    )
    assert resp.status_code == 200, resp.text
    edited = resp.json()["data"]
    assert edited["customer_po_number"] == "PO-EDITED"
    assert edited["grand_total"] == "1180.00"  # 1000 + 18% tax
    assert len(edited["items"]) == 1

    # Confirmed: frozen.
    resp = await client.post(
        f"/api/v1/orders/{order['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    assert resp.status_code == 200
    resp = await client.put(
        f"/api/v1/orders/{order['id']}", headers=user_headers,
        json={"notes": "tamper"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ORDER_NOT_DRAFT"


async def test_warehouse_editable_by_admin(client, user_headers, admin_headers):
    wh = await ensure_warehouse(client, admin_headers)
    resp = await client.patch(
        f"/api/v1/inventory/warehouses/{wh['id']}", headers=admin_headers,
        json={"code": wh["code"], "name": "Renamed Warehouse", "address": "New address",
              "is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Renamed Warehouse"

    # Operational user cannot edit warehouses.
    resp = await client.patch(
        f"/api/v1/inventory/warehouses/{wh['id']}", headers=user_headers,
        json={"code": wh["code"], "name": "X", "is_active": True},
    )
    assert resp.status_code == 403
