"""Direct-sale billing: header totals, and moving stock at finalize.

Two ways to sell now coexist:

* Order-driven — quotation, order, delivery, invoice. Stock leaves at delivery
  dispatch. Those invoices carry ``is_direct = False`` and this module never
  touches their stock.
* Direct — Quick Bill and Sell from Stock. There is no order and no delivery,
  so stock leaves when the invoice is finalized.

``invoice.stock_committed_at`` is the guard that keeps the second path exactly
once: a double-click, a retry after a dropped connection, or a replayed
idempotent request all find it already set and move no stock.

Totals order (header discount after tax) is deliberate and documented on
``calculate_totals``.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import StockMovement
from app.models.invoices import Invoice, InvoiceItem
from app.services.costing import balances_for, cost, resolve_unit_cost
from app.services.inventory import lock_balances
from app.services.money import LineAmounts, money


class InvoiceTotals(NamedTuple):
    subtotal: Decimal            # sum of line gross, before any discount
    line_discount_total: Decimal
    overall_discount_amount: Decimal
    discount_total: Decimal      # line + overall, what the invoice shows
    tax_total: Decimal
    delivery_charge: Decimal
    grand_total: Decimal


def resolve_overall_discount(
    base: Decimal, discount_type: str | None, value: Decimal
) -> Decimal:
    if not discount_type or value is None or value == 0:
        return money(0)
    if value < 0:
        raise ValidationFailedError("Discount cannot be negative.")
    if discount_type == "percent":
        if value > 100:
            raise ValidationFailedError(
                "A percentage discount cannot exceed 100%.",
                field_errors={"overall_discount_value": ["Must be 100 or less"]},
            )
        return money(base * value / Decimal("100"))
    if discount_type == "amount":
        return money(value)
    raise ValidationFailedError("Discount type must be 'percent' or 'amount'.")


def calculate_totals(
    lines: list[LineAmounts],
    *,
    overall_discount_type: str | None = None,
    overall_discount_value: Decimal = Decimal("0"),
    delivery_charge: Decimal = Decimal("0"),
) -> InvoiceTotals:
    """Header totals for an invoice.

    Line discounts and tax are computed per line by ``money.calculate_line``.
    Any overall discount then comes off the taxed line totals, and delivery is
    added last:

        grand_total = sum(line totals) - overall discount + delivery

    Taking the header discount after tax keeps each line's own tax figure
    intact and auditable, rather than silently restating it.
    """
    if delivery_charge < 0:
        raise ValidationFailedError("Delivery charge cannot be negative.")

    subtotal = money(sum((line.gross for line in lines), Decimal("0")))
    line_discount_total = money(sum((line.discount for line in lines), Decimal("0")))
    tax_total = money(sum((line.tax for line in lines), Decimal("0")))
    lines_total = money(sum((line.total for line in lines), Decimal("0")))

    overall = resolve_overall_discount(lines_total, overall_discount_type, overall_discount_value)
    if overall > lines_total:
        raise ValidationFailedError(
            "The discount is larger than the invoice total.",
            field_errors={"overall_discount_value": ["Exceeds the invoice total"]},
        )

    grand_total = money(lines_total - overall + money(delivery_charge))
    return InvoiceTotals(
        subtotal=subtotal,
        line_discount_total=line_discount_total,
        overall_discount_amount=overall,
        discount_total=money(line_discount_total + overall),
        tax_total=tax_total,
        delivery_charge=money(delivery_charge),
        grand_total=grand_total,
    )


def apply_totals(invoice: Invoice, totals: InvoiceTotals) -> None:
    invoice.subtotal = totals.subtotal
    invoice.discount_total = totals.discount_total
    invoice.overall_discount_amount = totals.overall_discount_amount
    invoice.tax_total = totals.tax_total
    invoice.delivery_charge = totals.delivery_charge
    invoice.grand_total = totals.grand_total


async def _load_catalogue(
    session: AsyncSession, items: list[InvoiceItem]
) -> tuple[dict[uuid.UUID, Product], dict[uuid.UUID, ProductVariant]]:
    product_ids = {i.product_id for i in items}
    variant_ids = {i.product_variant_id for i in items}
    products = {
        p.id: p
        for p in (
            await session.execute(select(Product).where(Product.id.in_(product_ids)))
        ).scalars().all()
    }
    variants = {
        v.id: v
        for v in (
            await session.execute(
                select(ProductVariant).where(ProductVariant.id.in_(variant_ids))
            )
        ).scalars().all()
    }
    return products, variants


async def commit_stock_and_cost(
    session: AsyncSession, invoice: Invoice, *, user_id: str
) -> dict:
    """Deduct stock for tracked lines and freeze every line's cost.

    Runs once per invoice. Cost is frozen for *all* lines, tracked or not, so
    a later price or cost change never rewrites the profit on an issued
    invoice. Stock moves only for tracked products on ``stock`` lines.
    """
    if invoice.stock_committed_at is not None:
        return {"stock_moved": False, "already_committed": True, "lines_costed": 0}

    items = list(invoice.items)
    if not items:
        raise ValidationFailedError("The invoice has no items.")
    products, variants = await _load_catalogue(session, items)

    # Which lines actually move inventory. A Quick Bill line never does, even
    # when the product is stock-tracked.
    stock_items = [
        i
        for i in items
        if i.line_source == "stock" and products[i.product_id].track_stock
    ]

    balances = {}
    if stock_items:
        if invoice.warehouse_id is None:
            raise ValidationFailedError(
                "This invoice sells tracked stock but has no warehouse set.",
                code="NO_WAREHOUSE",
            )
        balances = await lock_balances(
            session, invoice.warehouse_id, [i.product_variant_id for i in stock_items]
        )
    # Costing reads the weighted average of every tracked line, including the
    # Quick Bill ones we are not deducting: not moving stock is no reason to
    # report the sale as having no cost.
    uncosted_tracked = [
        i.product_variant_id
        for i in items
        if products[i.product_id].track_stock and i.product_variant_id not in balances
    ]
    if uncosted_tracked and invoice.warehouse_id is not None:
        balances = {
            **await balances_for(session, invoice.warehouse_id, uncosted_tracked),
            **balances,
        }

    # Validate the whole invoice before moving anything: all or nothing. This
    # guards the deducting lines only — Quick Bill lines are not checked
    # because they never leave the shelf.
    shortfalls = []
    for item in stock_items:
        balance = balances[item.product_variant_id]
        available = balance.on_hand - balance.reserved
        if available < item.quantity:
            shortfalls.append(
                f"{item.description_snapshot} — need {item.quantity}, "
                f"{available} available"
            )
    if shortfalls:
        raise ConflictError(
            "Not enough stock to finalize this invoice: " + "; ".join(shortfalls),
            code="INSUFFICIENT_STOCK",
        )

    for item in items:
        product = products[item.product_id]
        variant = variants[item.product_variant_id]
        balance = balances.get(item.product_variant_id)
        # A cost typed on the line during billing is the operator's explicit
        # figure for this sale; never override it with a catalogue value.
        if not (item.cost_source == "manual" and item.unit_cost is not None):
            unit_cost, source = await resolve_unit_cost(
                session, product=product, variant=variant, balance=balance
            )
            item.unit_cost = unit_cost
            item.cost_source = source
        # Remember what it last sold for, so the next bill can suggest it.
        variant.last_sale_price = item.unit_price

    for item in stock_items:
        balance = balances[item.product_variant_id]
        balance.on_hand -= item.quantity
        balance.version += 1
        session.add(
            StockMovement(
                warehouse_id=invoice.warehouse_id,
                product_variant_id=item.product_variant_id,
                quantity=-item.quantity,
                movement_type="invoice_out",
                unit_cost=cost(item.unit_cost) if item.unit_cost is not None else None,
                reference_type="invoice",
                reference_id=str(invoice.id),
                notes=f"Invoice {invoice.invoice_number or invoice.id}",
                created_by=uuid.UUID(user_id),
            )
        )

    invoice.stock_committed_at = datetime.now(UTC)
    await session.flush()
    return {
        "stock_moved": bool(stock_items),
        "already_committed": False,
        "lines_costed": len(items),
        "lines_stocked": len(stock_items),
    }


async def reverse_stock(
    session: AsyncSession, invoice: Invoice, *, user_id: str, reason: str
) -> dict:
    """Put deducted stock back when a finalized direct invoice is cancelled."""
    if invoice.stock_committed_at is None or invoice.stock_reversed_at is not None:
        return {"stock_returned": False}

    moved = (
        await session.execute(
            select(StockMovement).where(
                StockMovement.reference_type == "invoice",
                StockMovement.reference_id == str(invoice.id),
                StockMovement.movement_type == "invoice_out",
            )
        )
    ).scalars().all()
    if not moved:
        invoice.stock_reversed_at = datetime.now(UTC)
        return {"stock_returned": False}

    balances = await lock_balances(
        session, invoice.warehouse_id, [m.product_variant_id for m in moved]
    )
    for movement in moved:
        balance = balances[movement.product_variant_id]
        quantity = -movement.quantity  # stored negative on the way out
        balance.on_hand += quantity
        balance.version += 1
        session.add(
            StockMovement(
                warehouse_id=movement.warehouse_id,
                product_variant_id=movement.product_variant_id,
                quantity=quantity,
                movement_type="invoice_return",
                unit_cost=movement.unit_cost,
                reference_type="invoice",
                reference_id=str(invoice.id),
                notes=reason,
                created_by=uuid.UUID(user_id),
            )
        )
    invoice.stock_reversed_at = datetime.now(UTC)
    await session.flush()
    return {"stock_returned": True, "lines": len(moved)}
