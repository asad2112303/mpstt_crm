"""The frozen invoice document, shared by both ways of selling.

Order-driven invoices and direct (Quick Bill / Sell from Stock) invoices
render the same template from the same context builder, so the customer sees
one consistent document no matter how the sale was entered.

The context is frozen onto the invoice at issue. Payment figures are the one
exception: they are merged in live at download time, because what has been
paid keeps changing after the invoice is issued.
"""
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoices import Invoice
from app.models.orders import SalesOrder
from app.models.organization import Organization

WALK_IN_LABEL = "Walk-in Customer"


def payment_context(grand_total: Decimal, allocated: Decimal) -> dict:
    """Live payment figures, merged over the frozen document at render time."""
    paid = allocated or Decimal("0")
    return {
        "amount_paid": paid,
        "balance_due": grand_total - paid,
        "fully_paid": paid >= grand_total,
    }


async def build_pdf_context(db: AsyncSession, invoice: Invoice) -> dict:
    """Everything the invoice template needs, resolved once at issue."""
    from app.api.v1.quotations import _company_dict

    company = await _company_dict(db)
    org = await db.get(Organization, invoice.organization_id)

    if invoice.is_walk_in:
        customer_name = invoice.walk_in_name or WALK_IN_LABEL
        customer_code = None
    else:
        customer_name = org.name if org else WALK_IN_LABEL
        customer_code = org.org_code if org else None

    context = {
        "company": company,
        "invoice": {
            "number": invoice.invoice_number,
            "date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "terms_days": invoice.payment_terms_days,
            "reference": invoice.reference_number,
            "subtotal": invoice.subtotal,
            "discount_total": invoice.discount_total,
            "overall_discount": invoice.overall_discount_amount,
            "tax_total": invoice.tax_total,
            "delivery_charge": invoice.delivery_charge,
            "grand_total": invoice.grand_total,
            "currency": company.get("default_currency", "PKR"),
            "notes": invoice.notes,
            "payment_terms_note": invoice.payment_terms_note,
            "is_direct": invoice.is_direct,
        },
        "customer": {
            "name": customer_name,
            "code": customer_code,
            "city": None if invoice.is_walk_in else (org.city if org else None),
            "phone": invoice.contact_phone or (None if invoice.is_walk_in else (org.phone if org else None)),
            "ntn": None if invoice.is_walk_in else (org.ntn if org else None),
            "contact_person": invoice.contact_person,
            "billing_address": invoice.billing_address,
            "delivery_address": invoice.delivery_address,
        },
        "order_number": None,
        # Placeholder so the template always has the key: the real figures are
        # merged in at download time, because payment keeps moving after issue.
        "payment": payment_context(invoice.grand_total, Decimal("0")),
        "items": [
            {
                "sn": item.sort_order + 1,
                "description": item.description_snapshot,
                "specification": item.specification_snapshot,
                "quantity": item.quantity,
                "uom": item.uom_code,
                "unit_price": item.unit_price,
                "discount_percent": item.discount_percent,
                "line_total": item.line_total,
            }
            for item in invoice.items
        ],
    }
    if invoice.sales_order_id:
        order = await db.get(SalesOrder, invoice.sales_order_id)
        context["order_number"] = order.order_number if order else None
    return context


def walk_in_organization_code() -> str:
    return "WALK-IN"


async def get_walk_in_organization(db: AsyncSession) -> Organization:
    """The reserved system customer used for counter sales."""
    from sqlalchemy import select

    from app.core.errors import ConflictError

    org = (
        await db.execute(
            select(Organization).where(
                Organization.org_code == walk_in_organization_code(),
                Organization.is_system.is_(True),
            )
        )
    ).scalar_one_or_none()
    if org is None:
        raise ConflictError(
            "The reserved Walk-in Customer record is missing. Re-run migrations.",
            code="NO_WALK_IN_CUSTOMER",
        )
    return org


def is_walk_in(organization_id: uuid.UUID | None, walk_in_id: uuid.UUID) -> bool:
    return organization_id == walk_in_id
