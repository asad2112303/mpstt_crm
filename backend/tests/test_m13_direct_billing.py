"""Direct billing: Quick Bill, Sell from Stock, costing and the profit figures.

These map onto the acceptance criteria for the billing brief: bill without
inventory, reuse a product created while billing, stock untouched unless
tracking was asked for, exact deduction on finalize, mixed invoices, per-variant
balances, one dashboard for both modes, visible cost gaps, partial payments,
and consistent behaviour across drafts, cancellations and repeat submissions.
"""
import asyncio
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from tests.helpers import auth_headers, seed_profile
from tests.test_m6_orders_inventory import ensure_warehouse


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


def idem(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": str(uuid.uuid4())}


async def quick_line(name: str, qty: str, price: str, **extra) -> dict:
    product = {"name": name, "uom_code": "PCS", **extra}
    return {"new_product": product, "quantity": qty, "unit_price": price}


async def make_tracked_variant(client, admin_headers, db_session, *, colour: str = "Yellow"):
    """A normal catalogue product: stock-tracked by default.

    Seeds its own category so every colour in these tests is a valid option.
    """
    suffix = uuid.uuid4().hex[:6]
    resp = await client.post(
        "/api/v1/catalogue/categories", headers=admin_headers,
        json={
            "name": f"Billing Bins {suffix}",
            "attribute_schema": {"attributes": [
                {"key": "colour", "label": "Colour", "type": "select", "required": True,
                 "options": ["Yellow", "Red", "White", "Green", "Blue", "Amber"]},
                {"key": "capacity_litres", "label": "Capacity", "type": "number",
                 "min": 1, "max": 1100},
            ]},
        },
    )
    assert resp.status_code == 201, resp.text
    category = resp.json()["data"]

    resp = await client.post(
        "/api/v1/catalogue/uoms", headers=admin_headers,
        json={"code": f"PC{suffix[:4]}", "name": "Pieces"},
    )
    assert resp.status_code == 201, resp.text
    uom = resp.json()["data"]

    resp = await client.post(
        "/api/v1/catalogue/products", headers=admin_headers,
        json={"sku": f"BIN-{suffix}", "name": f"Pedal Bin {suffix}",
              "category_id": category["id"], "base_uom_id": uom["id"], "tax_rate": "0"},
    )
    assert resp.status_code == 201, resp.text
    product = resp.json()["data"]
    assert product["track_stock"] is True  # catalogue products track stock by default

    resp = await client.post(
        f"/api/v1/catalogue/products/{product['id']}/variants", headers=admin_headers,
        json={
            "variant_code": f"V{uuid.uuid4().hex[:8]}",
            "variant_name": f"{colour} 45L {uuid.uuid4().hex[:4]}",
            "attributes": {"colour": colour, "capacity_litres": 45},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def receive(client, headers, warehouse_id, variant_id, qty, cost=None):
    resp = await client.post(
        "/api/v1/inventory/receipts", headers=headers,
        json={"warehouse_id": warehouse_id, "product_variant_id": variant_id,
              "quantity": qty, "unit_cost": cost, "movement_type": "opening"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def available(client, headers, variant_id) -> Decimal:
    resp = await client.get(
        "/api/v1/inventory/balances", headers=headers,
        params={"product_variant_id": variant_id},
    )
    assert resp.status_code == 200, resp.text
    rows = [r for r in resp.json()["data"] if r["product_variant_id"] == variant_id]
    return Decimal(rows[0]["available"]) if rows else Decimal("0")


# --- 1. bill with no inventory set up at all -------------------------------

async def test_quick_bill_needs_no_inventory_setup(client, user_headers):
    """Acceptance 1: open the app, type a product, bill it, get a document."""
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={
            "walk_in": True,
            "walk_in_name": "Counter sale",
            "items": [
                await quick_line("Blue Dustbin 45L", "2", "1500"),
                await quick_line("Floor Cleaner 5L", "3", "900"),
            ],
        },
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()["data"]
    assert body["status"] == "draft"
    assert body["is_direct"] is True and body["is_walk_in"] is True
    assert body["grand_total"] == "5700.00"  # 2*1500 + 3*900
    assert [i["line_source"] for i in body["items"]] == ["quick_bill", "quick_bill"]

    final = await client.post(
        f"/api/v1/billing/invoices/{body['id']}/finalize", headers=idem(user_headers),
        json={"amount_paid": "5700"},
    )
    assert final.status_code == 200, final.text
    issued = final.json()["data"]
    assert issued["status"] == "issued"
    assert issued["invoice_number"].startswith("INV-")
    assert issued["derived_status"] == "paid"
    assert issued["stock"]["stock_moved"] is False

    pdf = await client.get(f"/api/v1/invoices/{body['id']}/pdf", headers=user_headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"


# --- 2 & 3. the product is reusable, and it holds no stock -----------------

async def test_quick_product_is_reusable_and_holds_no_stock(client, user_headers):
    """Acceptance 2 and 3."""
    name = f"Mop Head {uuid.uuid4().hex[:6]}"
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "items": [await quick_line(name, "4", "250")]},
    )
    assert draft.status_code == 201, draft.text
    variant_id = draft.json()["data"]["items"][0]["product_variant_id"]

    # Reusable: it now shows up in the billing product search.
    found = await client.get(
        "/api/v1/billing/products", headers=user_headers, params={"search": name}
    )
    assert found.status_code == 200
    hits = found.json()["data"]
    assert len(hits) == 1
    assert hits[0]["track_stock"] is False
    assert hits[0]["available"] is None  # untracked: no stock figure at all

    await client.post(
        f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "1000"},
    )
    # Selling it never created a stock balance.
    assert await available(client, user_headers, variant_id) == Decimal("0")


async def test_quantity_sold_is_never_treated_as_stock_received(client, user_headers, admin_headers):
    """Enabling tracking later asks for opening stock; it does not back-fill sales."""
    name = f"Bin Liner {uuid.uuid4().hex[:6]}"
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "items": [await quick_line(name, "10", "50")]},
    )
    data = draft.json()["data"]
    product_id = data["items"][0]["product_id"]
    variant_id = data["items"][0]["product_variant_id"]
    await client.post(
        f"/api/v1/billing/invoices/{data['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "500"},
    )
    await ensure_warehouse(client, admin_headers)

    resp = await client.post(
        f"/api/v1/inventory/products/{product_id}/enable-tracking", headers=user_headers,
        json={"opening_quantity": "25", "unit_cost": "30", "reorder_level": "5"},
    )
    assert resp.status_code == 200, resp.text
    # Exactly the 25 declared, not 25 + the 10 already sold.
    assert await available(client, user_headers, variant_id) == Decimal("25")


# --- 4 & 6. exact deduction, per-variant balances --------------------------

async def test_finalizing_deducts_exactly_what_was_sold(client, user_headers, admin_headers, db_session):
    """Acceptance 4: selling two units reduces stock by exactly two."""
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "10", "40")
    assert await available(client, user_headers, variant["id"]) == Decimal("10")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "2",
                         "unit_price": "100"}]},
    )
    assert draft.status_code == 201, draft.text
    invoice = draft.json()["data"]
    assert invoice["items"][0]["line_source"] == "stock"
    # A draft must not move stock.
    assert await available(client, user_headers, variant["id"]) == Decimal("10")

    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "200"},
    )
    assert resp.status_code == 200, resp.text
    assert await available(client, user_headers, variant["id"]) == Decimal("8")


async def test_colour_variants_hold_separate_balances(client, user_headers, admin_headers, db_session):
    """Acceptance 6: a red and a white variant are different stock."""
    red = await make_tracked_variant(client, admin_headers, db_session, colour="Red")
    white = await make_tracked_variant(client, admin_headers, db_session, colour="White")
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], red["id"], "10", "40")
    await receive(client, user_headers, wh["id"], white["id"], "10", "40")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": red["id"], "quantity": "3", "unit_price": "100"}]},
    )
    await client.post(
        f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "300"},
    )
    assert await available(client, user_headers, red["id"]) == Decimal("7")
    assert await available(client, user_headers, white["id"]) == Decimal("10")


# --- 5. mixed invoice ------------------------------------------------------

async def test_one_invoice_mixes_tracked_and_quick_bill_lines(
    client, user_headers, admin_headers, db_session
):
    """Acceptance 5."""
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "20", "40")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={
            "walk_in": True, "warehouse_id": wh["id"],
            "items": [
                {"product_variant_id": variant["id"], "quantity": "5", "unit_price": "100"},
                await quick_line("Ad-hoc Scrub Pads", "2", "150"),
            ],
        },
    )
    assert draft.status_code == 201, draft.text
    invoice = draft.json()["data"]
    assert sorted(i["line_source"] for i in invoice["items"]) == ["quick_bill", "stock"]

    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "800"},
    )
    assert resp.status_code == 200, resp.text
    # Only the tracked line moved stock.
    assert await available(client, user_headers, variant["id"]) == Decimal("15")
    assert resp.json()["data"]["stock"]["lines_stocked"] == 1


# --- 8. cost gaps are visible, never assumed zero --------------------------

async def test_missing_cost_is_reported_not_assumed_zero(client, user_headers, admin_headers, db_session):
    """Acceptance 8: an uncosted line must not read as 100% profit."""
    costed = await make_tracked_variant(client, admin_headers, db_session, colour="Green")
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], costed["id"], "10", "60")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={
            "walk_in": True, "warehouse_id": wh["id"],
            "items": [
                {"product_variant_id": costed["id"], "quantity": "1", "unit_price": "100"},
                await quick_line("Unknown Cost Item", "1", "500"),
            ],
        },
    )
    invoice = draft.json()["data"]
    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "600"},
    )
    body = resp.json()["data"]
    sources = {i["description_snapshot"]: i["cost_source"] for i in body["items"]}
    assert "missing" in sources.values()
    assert "weighted_average" in sources.values()

    profit = body["profit"]
    assert profit["cost_complete"] is False
    # Profit counts only the costed line: 100 - 60 = 40. Not 600 - 60.
    assert profit["gross_profit"] == "40.00"
    assert profit["sales_missing_cost"] == "500.00"


async def test_weighted_average_moves_on_receipts_only(client, user_headers, admin_headers, db_session):
    variant = await make_tracked_variant(client, admin_headers, db_session, colour="Blue")
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "10", "100")
    second = await receive(client, user_headers, wh["id"], variant["id"], "10", "200")
    # (10*100 + 10*200) / 20
    assert Decimal(second["avg_cost"]) == Decimal("150.0000")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "4",
                         "unit_price": "250"}]},
    )
    resp = await client.post(
        f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "1000"},
    )
    body = resp.json()["data"]
    assert body["items"][0]["cost_source"] == "weighted_average"
    # 4 * (250 - 150)
    assert body["profit"]["gross_profit"] == "400.00"


async def test_cost_typed_on_the_line_wins(client, user_headers):
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "items": [
            {**await quick_line("Priced Item", "2", "500"), "unit_cost": "300"},
        ]},
    )
    resp = await client.post(
        f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "1000"},
    )
    body = resp.json()["data"]
    assert body["items"][0]["cost_source"] == "manual"
    assert body["profit"]["gross_profit"] == "400.00"  # 1000 - 600
    assert body["profit"]["cost_complete"] is True


# --- 9 & 10. payments, drafts, cancellation, retries -----------------------

async def test_partial_payment_leaves_the_right_balance(client, user_headers, admin_headers, db_session):
    """Acceptance 9. A saved customer is required to carry a balance."""
    from tests.test_m2_prospects import create_prospect

    prospect = await create_prospect(client, user_headers)
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"organization_id": prospect["id"],
              "items": [await quick_line("Service Item", "1", "1000")]},
    )
    invoice = draft.json()["data"]
    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "400"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["derived_status"] == "partially_paid"
    assert body["outstanding"] == "600.00"


async def test_walk_in_cannot_leave_a_balance(client, user_headers):
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "items": [await quick_line("Counter Item", "1", "1000")]},
    )
    resp = await client.post(
        f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
        headers=idem(user_headers), json={"amount_paid": "250"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "WALK_IN_REQUIRES_FULL_PAYMENT"


async def test_finalize_is_idempotent_under_retry(client, user_headers, admin_headers, db_session):
    """Acceptance 10: a retried submission must not deduct stock twice."""
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "10", "40")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "3",
                         "unit_price": "100"}]},
    )
    invoice_id = draft.json()["data"]["id"]
    headers = idem(user_headers)

    first = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/finalize", headers=headers,
        json={"amount_paid": "300"},
    )
    assert first.status_code == 200, first.text
    replay = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/finalize", headers=headers,
        json={"amount_paid": "300"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["invoice_number"] == first.json()["data"]["invoice_number"]
    # Deducted once, not twice.
    assert await available(client, user_headers, variant["id"]) == Decimal("7")


async def test_double_click_finalize_deducts_once(client, user_headers, admin_headers, db_session):
    """Two concurrent finalize calls with different keys: still one deduction."""
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "10", "40")
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "3",
                         "unit_price": "100"}]},
    )
    invoice_id = draft.json()["data"]["id"]

    from app.main import create_app

    async def finalize():
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            return await c.post(
                f"/api/v1/billing/invoices/{invoice_id}/finalize",
                headers=idem(user_headers), json={"amount_paid": "300"},
            )

    first, second = await asyncio.gather(finalize(), finalize(), return_exceptions=True)
    codes = sorted(
        r.status_code for r in (first, second) if not isinstance(r, Exception)
    )
    # One succeeds; the other is refused as already finalized.
    assert 200 in codes
    assert await available(client, user_headers, variant["id"]) == Decimal("7")


async def test_cancelling_a_finalized_invoice_returns_stock(
    client, user_headers, admin_headers, db_session
):
    from tests.test_m2_prospects import create_prospect

    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "10", "40")
    # A saved customer, not walk-in: cancellation is blocked once money is
    # allocated, and a walk-in sale must be paid in full to finalize.
    customer = await create_prospect(client, user_headers)
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"organization_id": customer["id"], "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "4",
                         "unit_price": "100"}]},
    )
    invoice_id = draft.json()["data"]["id"]
    finalized = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/finalize", headers=idem(user_headers),
        json={},
    )
    assert finalized.status_code == 200, finalized.text
    assert await available(client, user_headers, variant["id"]) == Decimal("6")

    resp = await client.post(
        f"/api/v1/invoices/{invoice_id}/cancel", headers=user_headers,
        json={"reason": "Customer changed their mind"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["stock"]["stock_returned"] is True
    assert await available(client, user_headers, variant["id"]) == Decimal("10")


async def test_overselling_is_refused_and_leaves_the_draft_alone(
    client, user_headers, admin_headers, db_session
):
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "2", "40")

    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "warehouse_id": wh["id"],
              "items": [{"product_variant_id": variant["id"], "quantity": "5",
                         "unit_price": "100"}]},
    )
    invoice_id = draft.json()["data"]["id"]
    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/finalize", headers=idem(user_headers),
        json={"amount_paid": "500"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INSUFFICIENT_STOCK"

    # Still a draft, still no number burned, stock untouched.
    check = await client.get(f"/api/v1/invoices/{invoice_id}", headers=user_headers)
    assert check.json()["data"]["status"] == "draft"
    assert await available(client, user_headers, variant["id"]) == Decimal("2")


# --- totals ---------------------------------------------------------------

async def test_overall_discount_and_delivery_charge(client, user_headers):
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={
            "walk_in": True,
            "overall_discount_type": "percent",
            "overall_discount_value": "10",
            "delivery_charge": "250",
            "items": [await quick_line("Discounted Item", "10", "100")],
        },
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()["data"]
    # 1000 gross - 10% = 900, + 250 delivery
    assert body["overall_discount_amount"] == "100.00"
    assert body["delivery_charge"] == "250.00"
    assert body["grand_total"] == "1150.00"


async def test_discount_larger_than_the_invoice_is_refused(client, user_headers):
    resp = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={
            "walk_in": True,
            "overall_discount_type": "amount",
            "overall_discount_value": "5000",
            "items": [await quick_line("Small Item", "1", "100")],
        },
    )
    assert resp.status_code == 422


# --- 7. one dashboard for both modes --------------------------------------

async def test_both_billing_modes_feed_one_dashboard(
    client, user_headers, admin_headers, db_session
):
    """Acceptance 7."""
    variant = await make_tracked_variant(client, admin_headers, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "50", "40")

    before = await client.get(
        "/api/v1/dashboard/business", headers=user_headers, params={"preset": "month"}
    )
    assert before.status_code == 200, before.text
    base = Decimal(before.json()["data"]["sales"]["net_sales"])

    for payload in (
        {"product_variant_id": variant["id"], "quantity": "2", "unit_price": "100"},
        await quick_line("Dashboard Quick Item", "1", "300"),
    ):
        draft = await client.post(
            "/api/v1/billing/invoices", headers=user_headers,
            json={"walk_in": True, "warehouse_id": wh["id"], "items": [payload]},
        )
        total = draft.json()["data"]["grand_total"]
        resp = await client.post(
            f"/api/v1/billing/invoices/{draft.json()['data']['id']}/finalize",
            headers=idem(user_headers), json={"amount_paid": total},
        )
        assert resp.status_code == 200, resp.text

    after = await client.get(
        "/api/v1/dashboard/business", headers=user_headers, params={"preset": "month"}
    )
    data = after.json()["data"]
    assert Decimal(data["sales"]["net_sales"]) == base + Decimal("500")
    # Both modes are visible, and separable.
    assert Decimal(data["sales"]["from_stock"]) >= Decimal("200")
    assert Decimal(data["sales"]["quick_bill"]) >= Decimal("300")
    assert data["profit"]["cost_complete"] is False  # the quick item has no cost
    assert data["profit"]["cost_coverage_percent"] is not None

    breakdown = await client.get(
        "/api/v1/dashboard/business/breakdown", headers=user_headers,
        params={"preset": "month"},
    )
    assert breakdown.status_code == 200, breakdown.text
    bd = breakdown.json()["data"]
    assert bd["trend"] and bd["top_products"]
    assert any(r["payment_status"] == "paid" for r in bd["recent_invoices"])


async def test_low_stock_uses_the_reorder_level(client, user_headers, admin_headers, db_session):
    variant = await make_tracked_variant(client, admin_headers, db_session, colour="Amber")
    wh = await ensure_warehouse(client, admin_headers)
    await receive(client, user_headers, wh["id"], variant["id"], "3", "40")

    resp = await client.patch(
        f"/api/v1/catalogue/variants/{variant['id']}", headers=admin_headers,
        json={"reorder_level": "5"},
    )
    assert resp.status_code == 200, resp.text

    low = await client.get("/api/v1/inventory/low-stock", headers=user_headers)
    assert low.status_code == 200, low.text
    assert any(r["product_variant_id"] == variant["id"] for r in low.json()["data"])


async def test_draft_can_be_edited_then_finalized(client, user_headers):
    draft = await client.post(
        "/api/v1/billing/invoices", headers=user_headers,
        json={"walk_in": True, "items": [await quick_line("First Draft Item", "1", "100")]},
    )
    invoice_id = draft.json()["data"]["id"]

    updated = await client.put(
        f"/api/v1/billing/invoices/{invoice_id}", headers=user_headers,
        json={"walk_in": True, "items": [
            await quick_line("Replacement Item", "2", "250"),
        ]},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert len(body["items"]) == 1
    assert body["grand_total"] == "500.00"

    resp = await client.post(
        f"/api/v1/billing/invoices/{invoice_id}/finalize", headers=idem(user_headers),
        json={"amount_paid": "500"},
    )
    assert resp.status_code == 200
    # An issued invoice is no longer editable.
    locked = await client.put(
        f"/api/v1/billing/invoices/{invoice_id}", headers=user_headers,
        json={"walk_in": True, "items": [await quick_line("Too Late", "1", "1")]},
    )
    assert locked.status_code == 409
