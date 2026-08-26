"""M8 exit-gate tests: partials, over-delivery, POD gate, stock reconciliation."""
import uuid

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m4_conversion import make_sellable_variant
from tests.test_m6_orders_inventory import (
    ensure_warehouse,
    make_customer_with_order,
    stock_up,
)

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


async def confirmed_order_with_stock(client, user_headers, admin_headers, db_session):
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "500")
    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    resp = await client.post(
        f"/api/v1/orders/{data['order']['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    assert resp.status_code == 200
    return data, variant


async def upload_signed_challan(client, user_headers, delivery_id: str) -> str:
    resp = await client.post(
        "/api/v1/documents/upload", headers=user_headers,
        files={"file": ("signed-challan.pdf", PDF_BYTES, "application/pdf")},
        data={"entity_type": "delivery", "entity_id": delivery_id,
              "document_type": "signed_challan"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def make_challan(client, user_headers, order_id: str, item_id: str, qty: str) -> dict:
    resp = await client.post(
        "/api/v1/deliveries", headers=user_headers,
        json={"sales_order_id": order_id,
              "items": [{"sales_order_item_id": item_id, "quantity": qty}]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def complete(client, user_headers, delivery: dict, **pod_extra):
    doc_id = await upload_signed_challan(client, user_headers, delivery["id"])
    return await client.post(
        f"/api/v1/deliveries/{delivery['id']}/complete",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"receiver_name": "Store Incharge", "receiver_designation": "Storekeeper",
              "signed_challan_document_id": doc_id, **pod_extra},
    )


async def test_two_partial_deliveries_drive_order_status(
    client, user_headers, admin_headers, db_session
):
    data, variant = await confirmed_order_with_stock(client, user_headers, admin_headers, db_session)
    order = data["order"]
    item_id = order["items"][0]["id"]  # ordered 100

    first = await make_challan(client, user_headers, order["id"], item_id, "60")
    assert first["challan_number"].startswith("DC-")
    resp = await complete(client, user_headers, first)
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "partially_delivered"

    second = await make_challan(client, user_headers, order["id"], item_id, "40")
    resp = await complete(client, user_headers, second)
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "fully_delivered"

    # Remaining view is exhausted.
    resp = await client.get(f"/api/v1/deliveries/order/{order['id']}/remaining",
                            headers=user_headers)
    assert float(resp.json()["data"][0]["remaining"]) == 0.0


async def test_over_delivery_rejected(client, user_headers, admin_headers, db_session):
    data, _ = await confirmed_order_with_stock(client, user_headers, admin_headers, db_session)
    order = data["order"]
    item_id = order["items"][0]["id"]

    resp = await client.post(
        "/api/v1/deliveries", headers=user_headers,
        json={"sales_order_id": order["id"],
              "items": [{"sales_order_item_id": item_id, "quantity": "150"}]},
    )
    assert resp.status_code == 422

    # Open challan quantities also count against remaining.
    await make_challan(client, user_headers, order["id"], item_id, "80")
    resp = await client.post(
        "/api/v1/deliveries", headers=user_headers,
        json={"sales_order_id": order["id"],
              "items": [{"sales_order_item_id": item_id, "quantity": "30"}]},
    )
    assert resp.status_code == 422


async def test_missing_pod_blocks_completion(client, user_headers, admin_headers, db_session):
    data, _ = await confirmed_order_with_stock(client, user_headers, admin_headers, db_session)
    order = data["order"]
    delivery = await make_challan(client, user_headers, order["id"], order["items"][0]["id"], "50")

    resp = await client.post(
        f"/api/v1/deliveries/{delivery['id']}/complete",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"receiver_name": "Store Incharge"},  # no signed challan / signature
    )
    assert resp.status_code == 422
    assert "signed_challan" in str(resp.json()["error"]["field_errors"])

    resp = await client.get(f"/api/v1/deliveries/{delivery['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "draft"


async def test_stock_and_reservation_reconcile_on_delivery(
    client, user_headers, admin_headers, db_session
):
    data, variant = await confirmed_order_with_stock(client, user_headers, admin_headers, db_session)
    order = data["order"]

    async def balance():
        resp = await client.get("/api/v1/inventory/balances", headers=user_headers,
                                params={"search": variant["variant_name"]})
        return next(r for r in resp.json()["data"] if r["product_variant_id"] == variant["id"])

    before = await balance()
    delivery = await make_challan(client, user_headers, order["id"], order["items"][0]["id"], "100")
    resp = await complete(client, user_headers, delivery)
    assert resp.status_code == 200

    after = await balance()
    assert float(after["on_hand"]) == float(before["on_hand"]) - 100.0
    assert float(after["reserved"]) == float(before["reserved"]) - 100.0
    # Available unchanged: both on_hand and reserved dropped together.
    assert float(after["available"]) == float(before["available"])


async def test_rejected_quantities_stay_in_stock(client, user_headers, admin_headers, db_session):
    data, variant = await confirmed_order_with_stock(
        client, user_headers, admin_headers, db_session
    )
    order = data["order"]
    delivery = await make_challan(client, user_headers, order["id"], order["items"][0]["id"], "100")
    item = delivery["items"][0]

    resp = await complete(
        client, user_headers, delivery,
        line_results=[{"delivery_item_id": item["id"], "delivered_quantity": "70",
                       "rejected_quantity": "30", "rejection_remarks": "Damaged cartons"}],
    )
    assert resp.status_code == 200, resp.text
    completed = resp.json()["data"]
    assert float(completed["items"][0]["delivered_quantity"]) == 70.0
    assert float(completed["items"][0]["rejected_quantity"]) == 30.0

    # Order remains partially delivered (70 of 100).
    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "partially_delivered"


async def test_challan_pdf(client, user_headers, admin_headers, db_session):
    data, _ = await confirmed_order_with_stock(client, user_headers, admin_headers, db_session)
    order = data["order"]
    delivery = await make_challan(client, user_headers, order["id"], order["items"][0]["id"], "10")
    resp = await client.get(f"/api/v1/deliveries/{delivery['id']}/challan", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
