"""Atomic prospect → customer conversion with the first order.

Frozen rules:
- The SAME organization row becomes a Customer — never duplicated.
- All history (contacts, branches, activities, samples, requirements, prices,
  documents) is preserved because nothing is copied or deleted.
- Runs in ONE transaction: lock org → verify prospect → validate order →
  allocate CUST + ORD numbers → create customer profile → set lifecycle →
  stage=won → create order+items → audit → commit (or roll back everything).
- The router wraps this in the idempotency service; retries replay the result.
"""
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, selectinload

from app.core.errors import ConflictError, ValidationFailedError
from app.models.catalogue import ProductVariant
from app.models.orders import SalesOrder, SalesOrderItem
from app.models.organization import CustomerProfile, Organization, ProspectProfile, Task
from app.services.audit import write_audit
from app.services.money import calculate_line, sum_lines
from app.services.numbering import allocate_number


@dataclass
class OrderItemInput:
    product_variant_id: uuid.UUID
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal = Decimal("0")


@dataclass
class ConversionInput:
    items: list[OrderItemInput]
    branch_id: uuid.UUID | None = None
    customer_po_number: str | None = None
    is_direct_po: bool = True
    source_quotation_id: uuid.UUID | None = None
    expected_delivery_date: date | None = None
    payment_terms_days: int = 30
    credit_limit: Decimal | None = None
    order_notes: str | None = None


async def build_order_items(
    session: AsyncSession, items: list[OrderItemInput]
) -> tuple[list[SalesOrderItem], list]:
    """Validate variants and freeze description/spec/tax snapshots."""
    if not items:
        raise ValidationFailedError("An order needs at least one item.",
                                    field_errors={"items": ["Empty"]})
    variant_ids = [item.product_variant_id for item in items]
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
    order_items: list[SalesOrderItem] = []
    amounts = []
    for index, item in enumerate(items):
        variant = variants.get(item.product_variant_id)
        if variant is None or not variant.is_active or not variant.product.is_active:
            raise ValidationFailedError(
                "One of the selected variants does not exist or is inactive.",
                field_errors={f"items.{index}.product_variant_id": ["Invalid variant"]},
            )
        tax_rate = variant.product.tax_rate
        line = calculate_line(item.quantity, item.unit_price, item.discount_percent, tax_rate)
        amounts.append(line)
        order_items.append(
            SalesOrderItem(
                product_id=variant.product_id,
                product_variant_id=variant.id,
                description_snapshot=f"{variant.product.name} — {variant.variant_name}",
                specification_snapshot=variant.attributes,
                quantity=item.quantity,
                uom_code=variant.uom.code,
                unit_price=item.unit_price,
                discount_percent=item.discount_percent,
                tax_rate=tax_rate,
                line_net=line.net,
                line_tax=line.tax,
                line_total=line.total,
                sort_order=index,
            )
        )
    return order_items, amounts


async def convert_prospect_to_customer_order(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: str,
    data: ConversionInput,
) -> tuple[Organization, SalesOrder]:
    # 1. Lock the organization row (lazyload("*") keeps the SELECT join-free so
    # FOR UPDATE is legal; related rows are loaded separately when needed).
    org = (
        await session.execute(
            select(Organization)
            .options(lazyload("*"))
            .where(Organization.id == organization_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if org is None:
        raise ValidationFailedError("Organization not found.")

    # 2. Verify it is still a prospect (a concurrent conversion loses here).
    if org.lifecycle_status != "prospect":
        raise ConflictError(
            "This organization has already been converted to a customer.",
            code="ALREADY_CUSTOMER",
        )

    # 3. Validate the complete first order (also freezes snapshots).
    order_items, amounts = await build_order_items(session, data.items)
    totals = sum_lines(amounts)

    # 4. Allocate numbers inside the same transaction (row-locked sequences).
    customer_code = await allocate_number(session, "CUST")
    order_number = await allocate_number(session, "ORD")

    now = datetime.now(UTC)

    # 5. Customer profile appears exactly once (org PK guarantees it).
    session.add(
        CustomerProfile(
            organization_id=org.id,
            customer_code=customer_code,
            customer_since=now.date(),
            payment_terms_days=data.payment_terms_days,
            credit_limit=data.credit_limit,
        )
    )

    # 6-7. Same organization row becomes the customer; prospect history closes as Won.
    org.lifecycle_status = "customer"
    org.converted_at = now
    org.updated_by = uuid.UUID(user_id)
    profile = (
        await session.execute(
            select(ProspectProfile)
            .where(ProspectProfile.organization_id == org.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if profile is not None:
        profile.stage = "won"

    # 8. Close open prospect tasks.
    open_tasks = (
        await session.execute(
            select(Task).where(Task.organization_id == org.id, Task.status == "open")
        )
    ).scalars().all()
    for task in open_tasks:
        task.status = "done"
        task.completed_at = now
        task.completion_outcome = "Closed by first-order conversion"

    # 9. Create the first order.
    order = SalesOrder(
        order_number=order_number,
        organization_id=org.id,
        branch_id=data.branch_id,
        source_quotation_id=data.source_quotation_id,
        is_direct_po=data.is_direct_po,
        customer_po_number=data.customer_po_number,
        expected_delivery_date=data.expected_delivery_date,
        status="draft",
        subtotal=totals.subtotal,
        discount_total=totals.discount_total,
        tax_total=totals.tax_total,
        grand_total=totals.grand_total,
        notes=data.order_notes,
        created_by=uuid.UUID(user_id),
        items=order_items,
    )
    session.add(order)
    await session.flush()

    # 10. Stock reservation happens at order confirmation (M6).

    # 11. Audit both effects in the same transaction.
    await write_audit(
        session, action="prospect.converted", entity_type="organization", entity_id=org.id,
        old={"lifecycle_status": "prospect"},
        new={"lifecycle_status": "customer", "customer_code": customer_code},
    )
    await write_audit(
        session, action="order.created", entity_type="sales_order", entity_id=order.id,
        new={"order_number": order_number, "grand_total": str(totals.grand_total),
             "first_order": True},
    )
    return org, order
