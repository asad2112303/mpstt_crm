"""M12 UAT: the complete lifecycle in one scenario.

prospect → visit → requirement → sample → quote → revise → send → accept →
convert (customer + first order) → confirm/reserve → invoice → two partial
deliveries with POD → partial payment → final payment → receipt → reports.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m3_catalogue import seed_catalogue
from tests.test_m8_deliveries import PDF_BYTES

IDEM = lambda: {"Idempotency-Key": str(uuid.uuid4())}  # noqa: E731


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user", full_name="Field Officer"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin", full_name="MPSTT Admin"))


async def test_full_prospect_to_payment_lifecycle(client, user_headers, admin_headers, db_session):
    # --- Catalogue (admin) -------------------------------------------------
    ids = await seed_catalogue(client, admin_headers)
    resp = await client.post(
        f"/api/v1/catalogue/products/{ids['product']['id']}/variants",
        headers=admin_headers,
        json={"variant_code": f"UAT-{uuid.uuid4().hex[:6]}",
              "variant_name": f"Yellow UAT {uuid.uuid4().hex[:4]}",
              "attributes": {"colour": "Yellow", "thickness_micron": 30}},
    )
    variant = resp.json()["data"]

    resp = await client.get("/api/v1/inventory/warehouses", headers=admin_headers)
    warehouses = [w for w in resp.json()["data"] if w["is_active"]]
    if warehouses:
        wh = warehouses[0]
    else:
        wh = (await client.post("/api/v1/inventory/warehouses", headers=admin_headers,
                                json={"code": "MAIN", "name": "Main Warehouse"})).json()["data"]
    await client.post("/api/v1/inventory/adjustments", headers=admin_headers,
                      json={"warehouse_id": wh["id"], "product_variant_id": variant["id"],
                            "quantity": "1000", "reason": "UAT opening stock",
                            "movement_type": "opening"})

    # --- 1. Prospect created ----------------------------------------------
    resp = await client.post("/api/v1/prospects", headers=user_headers, json={
        "name": f"UAT General Hospital {uuid.uuid4().hex[:6]}",
        "org_type": "hospital", "city": "Islamabad", "source": "field_visit",
        "phone": "051-2223334", "contact_name": "Dr Procurement",
        "confirm_duplicate": True,
    })
    assert resp.status_code == 201
    org = resp.json()["data"]
    org_id = org["id"]

    # --- 2. Visit with next action -----------------------------------------
    resp = await client.post(f"/api/v1/prospects/{org_id}/activities", headers=user_headers, json={
        "activity_type": "visit", "outcome": "Toured waste store",
        "next_action_title": "Collect requirement sheet",
        "next_action_due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
    })
    assert resp.status_code == 201

    # --- 3. Requirement ------------------------------------------------------
    resp = await client.put(f"/api/v1/prospects/{org_id}/product-profiles",
                            headers=user_headers, json=[{
                                "product_id": ids["product"]["id"],
                                "product_variant_id": variant["id"],
                                "frequency": "monthly", "min_quantity": "200",
                                "max_quantity": "400", "current_supplier": "Old Vendor",
                                "current_rate": "14.00",
                            }])
    assert resp.status_code == 200

    # --- 4. Sample -----------------------------------------------------------
    resp = await client.post(f"/api/v1/prospects/{org_id}/samples", headers=user_headers,
                             json={"product_id": ids["product"]["id"],
                                   "product_variant_id": variant["id"], "quantity": "20",
                                   "receiver_name": "Matron"})
    sample = resp.json()["data"]
    await client.patch(f"/api/v1/prospects/samples/{sample['id']}/feedback",
                       headers=user_headers,
                       json={"status": "feedback_received", "feedback": "Approved"})

    # --- 5. Quote → revise → send → accept ----------------------------------
    resp = await client.post("/api/v1/quotations", headers=user_headers, json={
        "organization_id": org_id, "valid_until": "2099-01-01",
        "items": [{"product_variant_id": variant["id"], "quantity": "300",
                   "unit_price": "13.00"}],
    })
    quote1 = resp.json()["data"]
    await client.post(f"/api/v1/quotations/{quote1['id']}/send",
                      headers={**user_headers, **IDEM()})
    resp = await client.post(f"/api/v1/quotations/{quote1['id']}/revise", headers=user_headers)
    quote2 = resp.json()["data"]
    await client.put(f"/api/v1/quotations/{quote2['id']}", headers=user_headers, json={
        "items": [{"product_variant_id": variant["id"], "quantity": "300",
                   "unit_price": "12.50"}],
    })
    resp = await client.post(f"/api/v1/quotations/{quote2['id']}/send",
                             headers={**user_headers, **IDEM()})
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/quotations/{quote2['id']}/accept", headers=user_headers)
    assert resp.status_code == 200

    # --- 6. Convert (atomic customer + first order) --------------------------
    resp = await client.post(f"/api/v1/quotations/{quote2['id']}/convert-to-order",
                             headers={**user_headers, **IDEM()})
    assert resp.status_code == 201, resp.text
    order = resp.json()["data"]["order"]
    resp = await client.get(f"/api/v1/customers/{org_id}", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["prospect_profile"]["stage"] == "won"

    # --- 7. Confirm reserves stock -------------------------------------------
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm",
                             headers={**user_headers, **IDEM()}, json={})
    assert resp.status_code == 200

    # --- 8. Invoice (before delivery is allowed) -----------------------------
    resp = await client.post("/api/v1/invoices/from-order", headers=user_headers,
                             json={"sales_order_id": order["id"]})
    invoice = resp.json()["data"]
    resp = await client.post(f"/api/v1/invoices/{invoice['id']}/issue",
                             headers={**user_headers, **IDEM()})
    invoice = resp.json()["data"]
    assert invoice["derived_status"] == "issued"

    # --- 9. Two partial deliveries with POD ----------------------------------
    async def deliver(qty: str):
        resp = await client.post("/api/v1/deliveries", headers=user_headers, json={
            "sales_order_id": order["id"],
            "items": [{"sales_order_item_id": order["items"][0]["id"], "quantity": qty}],
        })
        delivery = resp.json()["data"]
        doc = await client.post(
            "/api/v1/documents/upload", headers=user_headers,
            files={"file": ("signed.pdf", PDF_BYTES, "application/pdf")},
            data={"entity_type": "delivery", "entity_id": delivery["id"],
                  "document_type": "signed_challan"},
        )
        resp = await client.post(
            f"/api/v1/deliveries/{delivery['id']}/complete",
            headers={**user_headers, **IDEM()},
            json={"receiver_name": "Store Incharge",
                  "signed_challan_document_id": doc.json()["data"]["id"]},
        )
        assert resp.status_code == 200, resp.text

    await deliver("180")
    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "partially_delivered"
    await deliver("120")
    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "fully_delivered"

    # --- 10. Partial then final payment + receipt ----------------------------
    total = float(invoice["grand_total"])
    resp = await client.post("/api/v1/payments", headers=user_headers, json={
        "organization_id": org_id, "payment_date": datetime.now(UTC).date().isoformat(),
        "amount": "2000.00", "method": "bank_transfer", "reference": "UAT-1",
    })
    p1 = resp.json()["data"]
    await client.post(f"/api/v1/payments/{p1['id']}/allocate",
                      headers={**user_headers, **IDEM()},
                      json={"allocations": [{"invoice_id": invoice["id"], "amount": "2000.00"}]})
    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    assert resp.json()["data"]["derived_status"] == "partially_paid"

    remainder = f"{total - 2000:.2f}"
    resp = await client.post("/api/v1/payments", headers=user_headers, json={
        "organization_id": org_id, "payment_date": datetime.now(UTC).date().isoformat(),
        "amount": remainder, "method": "cheque", "reference": "UAT-2",
    })
    p2 = resp.json()["data"]
    resp = await client.post(f"/api/v1/payments/{p2['id']}/allocate",
                             headers={**user_headers, **IDEM()},
                             json={"allocations": [{"invoice_id": invoice["id"],
                                                    "amount": remainder}]})
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/invoices/{invoice['id']}", headers=user_headers)
    assert resp.json()["data"]["derived_status"] == "paid"

    resp = await client.post(f"/api/v1/payments/{p2['id']}/receipt", headers=user_headers)
    assert resp.status_code == 201
    assert resp.json()["data"]["receipt"]["receipt_number"].startswith("RCP-")

    # --- 11. Statement closes at zero; dashboards reconcile ------------------
    resp = await client.get(f"/api/v1/customers/{org_id}/statement", headers=user_headers)
    assert float(resp.json()["data"]["closing_balance"]) == 0.0

    resp = await client.get("/api/v1/dashboard/summary", headers=admin_headers)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/reports/sales", headers=admin_headers)
    assert any(r["order_number"] == order["order_number"]
               for r in resp.json()["data"]["rows"])

    # Full audit trail exists for the journey.
    resp = await client.get("/api/v1/admin/audit", headers=admin_headers,
                            params={"entity_id": org_id})
    actions = {r["action"] for r in resp.json()["data"]}
    assert "prospect.created" in actions and "prospect.converted" in actions
