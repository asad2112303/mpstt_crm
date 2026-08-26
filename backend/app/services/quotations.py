"""Quotation domain rules: build items, freeze on send, revise, PDF context."""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, ValidationFailedError
from app.models.catalogue import ProductVariant
from app.models.organization import Organization, OrganizationBranch, OrganizationContact
from app.models.quotes import Quotation, QuotationItem
from app.services.money import calculate_line, sum_lines


def effective_status(quote: Quotation, today: date | None = None) -> str:
    """'expired' is derived, never stored."""
    today = today or date.today()
    if quote.status == "sent" and quote.valid_until and quote.valid_until < today:
        return "expired"
    return quote.status


async def build_quote_items(
    session: AsyncSession, items: list[dict]
) -> tuple[list[QuotationItem], list]:
    if not items:
        raise ValidationFailedError("A quotation needs at least one item.",
                                    field_errors={"items": ["Empty"]})
    variant_ids = [uuid.UUID(str(i["product_variant_id"])) for i in items]
    variants = {
        v.id: v
        for v in (
            await session.execute(
                select(ProductVariant)
                .options(selectinload(ProductVariant.product))
                .where(ProductVariant.id.in_(variant_ids))
            )
        ).scalars()
    }
    out: list[QuotationItem] = []
    amounts = []
    for index, item in enumerate(items):
        variant = variants.get(uuid.UUID(str(item["product_variant_id"])))
        if variant is None or not variant.is_active or not variant.product.is_active:
            raise ValidationFailedError(
                "One of the selected variants does not exist or is inactive.",
                field_errors={f"items.{index}.product_variant_id": ["Invalid variant"]},
            )
        quantity = Decimal(str(item["quantity"]))
        unit_price = Decimal(str(item["unit_price"]))
        discount = Decimal(str(item.get("discount_percent") or "0"))
        description = item.get("description") or f"{variant.product.name} — {variant.variant_name}"
        tax_rate = variant.product.tax_rate
        line = calculate_line(quantity, unit_price, discount, tax_rate)
        amounts.append(line)
        out.append(
            QuotationItem(
                product_id=variant.product_id,
                product_variant_id=variant.id,
                description_snapshot=description,
                specification_snapshot=variant.attributes,
                quantity=quantity,
                uom_code=variant.uom.code,
                unit_price=unit_price,
                discount_percent=discount,
                tax_rate=tax_rate,
                line_net=line.net,
                line_tax=line.tax,
                line_total=line.total,
                sort_order=index,
            )
        )
    return out, amounts


def apply_totals(quote: Quotation, amounts: list) -> None:
    totals = sum_lines(amounts)
    quote.subtotal = totals.subtotal
    quote.discount_total = totals.discount_total
    quote.tax_total = totals.tax_total
    quote.grand_total = totals.grand_total


def ensure_editable(quote: Quotation) -> None:
    if quote.status != "draft":
        raise ConflictError(
            "The quotation has already been sent and cannot be edited. Create a revision instead.",
            code="QUOTE_NOT_EDITABLE",
        )


async def pdf_context(session: AsyncSession, quote: Quotation, company: dict) -> dict:
    """Frozen data for the PDF — everything comes from the quotation row itself."""
    org = await session.get(Organization, quote.organization_id)
    branch = await session.get(OrganizationBranch, quote.branch_id) if quote.branch_id else None
    contact = await session.get(OrganizationContact, quote.contact_id) if quote.contact_id else None
    return {
        "company": company,
        "quote": {
            "number": quote.quotation_number,
            "revision_no": quote.revision_no,
            "date": quote.quote_date.isoformat(),
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "terms": quote.terms,
            "notes": quote.notes,
            "subtotal": quote.subtotal,
            "discount_total": quote.discount_total,
            "tax_total": quote.tax_total,
            "grand_total": quote.grand_total,
            "currency": company.get("default_currency", "PKR"),
        },
        "customer": {
            "name": org.name if org else "",
            "code": org.org_code if org else "",
            "city": org.city if org else None,
            "phone": org.phone if org else None,
            "ntn": org.ntn if org else None,
            "branch_name": branch.branch_name if branch else None,
            "address": (branch.billing_address or branch.delivery_address) if branch else None,
            "contact_name": contact.full_name if contact else None,
            "contact_phone": contact.phone_primary if contact else None,
        },
        "items": [
            {
                "sn": i.sort_order + 1,
                "description": i.description_snapshot,
                "specification": i.specification_snapshot,
                "quantity": i.quantity,
                "uom": i.uom_code,
                "unit_price": i.unit_price,
                "discount_percent": i.discount_percent,
                "tax_rate": i.tax_rate,
                "line_total": i.line_total,
            }
            for i in quote.items
        ],
    }
