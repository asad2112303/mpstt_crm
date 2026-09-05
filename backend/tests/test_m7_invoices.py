"""M7 exit-gate tests: due dates, issue idempotency, immutability, overdue."""
import uuid
from datetime import date, timedelta

import pytest

from tests.helpers import auth_headers, seed_profile
from tests.test_m4_conversion import make_sellable_variant
from tests.test_m6_orders_inventory import (
    ensure_warehouse,
    make_customer_with_order,
    stock_up,
)


@pytest.fixture()
async def user_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="user"))


@pytest.fixture()
async def admin_headers(db_session):
    return auth_headers(await seed_profile(db_session, role="admin"))


async def confirmed_order(client, user_headers, admin_headers, db_session) -> dict:
    variant = await make_sellable_variant(client, db_session)
    wh = await ensure_warehouse(client, admin_headers)
    await stock_up(client, admin_headers, wh["id"], variant["id"], "500")
    data = await make_customer_with_order(client, user_headers, db_session, variant["id"])
    resp = await client.post(
        f"/api/v1/orders/{data['order']['id']}/confirm",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())}, json={},
    )
    assert resp.status_code == 200
    return data


async def test_invoice_lifecycle_from_order(client, user_headers, admin_headers, db_session):
    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    order = data["order"]

    # Draft order cannot be invoiced twice etc.; create draft invoice
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": order["id"]},
    )
    assert resp.status_code == 201, resp.text
    invoice = resp.json()["data"]
    assert invoice["status"] == "draft"
    assert invoice["invoice_number"] is None
    assert invoice["grand_total"] == order["grand_total"]
    # Terms came from the customer profile created at conversion (45 days).
    assert invoice["payment_terms_days"] == 45

    # Duplicate invoice blocked.
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": order["id"]},
    )
    assert resp.status_code == 409

    # Issue: number allocated, due date derived, PDF stored, receivable live.
    key = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": key},
    )
    assert resp.status_code == 200, resp.text
    issued = resp.json()["data"]
    assert issued["invoice_number"].startswith("INV-")
    assert issued["status"] == "issued"
    expected_due = date.today() + timedelta(days=45)
    assert issued["due_date"] == expected_due.isoformat()
    resp = await client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=user_headers)
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF-")
    assert issued["outstanding"] == issued["grand_total"]
    assert issued["derived_status"] == "issued"

    # Idempotent retry returns the same number.
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": key},
    )
    assert resp.json()["data"]["invoice_number"] == issued["invoice_number"]

    # A new key hits the status guard instead of double-issuing.
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 409

    # PDF is retrievable.
    resp = await client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=user_headers)
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


async def test_custom_due_date_and_overdue_derivation(
    client, user_headers, admin_headers, db_session
):
    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"],
              "custom_due_date": (date.today() - timedelta(days=5)).isoformat()},
    )
    invoice = resp.json()["data"]
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    issued = resp.json()["data"]
    # Custom (already past) due date → derived overdue immediately.
    assert issued["derived_status"] == "overdue"


async def test_invoice_before_delivery_is_allowed(client, user_headers, admin_headers, db_session):
    """V1 rule: invoicing does not require delivery. They are separate records."""
    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"]},
    )
    assert resp.status_code == 201
    invoice = resp.json()["data"]
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200
    # The order is still only 'confirmed' — no delivery happened.
    resp = await client.get(f"/api/v1/orders/{data['order']['id']}", headers=user_headers)
    assert resp.json()["data"]["status"] == "confirmed"


async def test_cancel_rules(client, user_headers, admin_headers, db_session):
    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"]},
    )
    invoice = resp.json()["data"]

    # Reason required.
    resp = await client.post(f"/api/v1/invoices/{invoice['id']}/cancel",
                             headers=user_headers, json={})
    assert resp.status_code == 422

    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/cancel", headers=user_headers,
        json={"reason": "Order re-negotiated"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    # A cancelled invoice frees the order for a fresh invoice.
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"]},
    )
    assert resp.status_code == 201


async def test_issue_and_download_do_not_touch_object_storage(
    client, user_headers, admin_headers, db_session, monkeypatch
):
    """Issuing used to upload the PDF, so an unreachable bucket blocked billing.

    The document is now frozen as a render context on the invoice and the file
    is produced on demand, so both operations work with storage broken.
    """
    import app.services.storage as storage_module

    def explode(*args, **kwargs):
        raise AssertionError("object storage must not be used for generated PDFs")

    monkeypatch.setattr(storage_module, "get_storage", explode)

    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"]},
    )
    assert resp.status_code == 201, resp.text
    invoice = resp.json()["data"]

    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    issued = resp.json()["data"]
    assert issued["status"] == "issued"

    resp = await client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=user_headers)
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF-")
    assert issued["invoice_number"] in resp.headers["content-disposition"]


async def test_issued_invoice_pdf_ignores_later_company_edits(
    client, user_headers, admin_headers, db_session
):
    """An issued invoice is immutable: its PDF must not pick up later changes."""
    from app.services.pdf import render_html

    data = await confirmed_order(client, user_headers, admin_headers, db_session)
    resp = await client.post(
        "/api/v1/invoices/from-order", headers=user_headers,
        json={"sales_order_id": data["order"]["id"]},
    )
    invoice = resp.json()["data"]
    resp = await client.post(
        f"/api/v1/invoices/{invoice['id']}/issue",
        headers={**user_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.put(
        "/api/v1/admin/settings", headers=admin_headers,
        json={"company_name": "Renamed After Issue (Pvt) Ltd"},
    )
    assert resp.status_code == 200, resp.text

    from sqlalchemy import select

    from app.models.invoices import Invoice

    row = (
        await db_session.execute(select(Invoice).where(Invoice.id == uuid.UUID(invoice["id"])))
    ).scalar_one()
    await db_session.refresh(row)
    html = render_html("invoice.html", row.pdf_context)
    assert "Renamed After Issue" not in html
