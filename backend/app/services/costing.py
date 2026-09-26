"""Cost of goods: moving weighted average, and the cost frozen onto a sale.

The schema had nowhere to record what stock cost, so profit could not be
calculated at all. Costing here is deliberately conservative: when no cost is
known the line is marked ``missing`` rather than defaulted to zero, because a
zero cost silently reports the full sale price as profit.

Weighted average is held per (warehouse, variant) on ``stock_balances`` and
moves only on the way in:

    new_avg = (on_hand * avg_cost + received_qty * received_cost)
              / (on_hand + received_qty)

Selling does not change the average; it copies the current one onto the sale.
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import StockBalance, StockMovement
from app.services.inventory import lock_balances

FOUR_PLACES = Decimal("0.0001")

# Where a line's cost came from, best first.
WEIGHTED_AVERAGE = "weighted_average"
MANUAL = "manual"
PRODUCT_DEFAULT = "product_default"
MISSING = "missing"


def cost(value: Decimal | str | int) -> Decimal:
    """Costs carry four decimals: unit costs divide badly at two."""
    return Decimal(value).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def new_average(
    on_hand: Decimal, avg_cost: Decimal | None, received_qty: Decimal, received_cost: Decimal
) -> Decimal:
    """Moving weighted average after a costed receipt."""
    if received_qty <= 0:
        raise ValueError("received_qty must be positive")
    # No prior average, or stock ran to zero: the receipt sets the cost outright.
    if avg_cost is None or on_hand <= 0:
        return cost(received_cost)
    total_value = (on_hand * avg_cost) + (received_qty * received_cost)
    return cost(total_value / (on_hand + received_qty))


async def receive_stock(
    session: AsyncSession,
    *,
    warehouse_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    quantity: Decimal,
    unit_cost: Decimal | None,
    user_id: str,
    movement_type: str = "receipt_in",
    reference_type: str | None = None,
    reference_id: str | None = None,
    notes: str | None = None,
) -> StockBalance:
    """Book stock in and roll the weighted average forward.

    A receipt with no cost still adds quantity; it just leaves the average
    where it was, and the shortfall shows up as incomplete cost coverage.
    """
    if quantity <= 0:
        raise ValidationFailedError("Received quantity must be greater than zero.")
    if unit_cost is not None and unit_cost < 0:
        raise ValidationFailedError("Purchase cost cannot be negative.")

    balance = (await lock_balances(session, warehouse_id, [product_variant_id]))[
        product_variant_id
    ]
    if unit_cost is not None:
        balance.avg_cost = new_average(balance.on_hand, balance.avg_cost, quantity, unit_cost)
    balance.on_hand += quantity
    balance.version += 1

    session.add(
        StockMovement(
            warehouse_id=warehouse_id,
            product_variant_id=product_variant_id,
            quantity=quantity,
            movement_type=movement_type,
            unit_cost=cost(unit_cost) if unit_cost is not None else None,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            created_by=uuid.UUID(user_id),
        )
    )
    await session.flush()
    return balance


async def resolve_unit_cost(
    session: AsyncSession,
    *,
    product: Product,
    variant: ProductVariant,
    balance: StockBalance | None,
) -> tuple[Decimal | None, str]:
    """The cost to freeze onto a sale, and where it came from.

    Tracked stock is costed at its weighted average. Untracked (Quick Bill)
    products hold no balance, so they fall back to the cost captured on the
    variant, then the product default. When none exists the caller must record
    ``missing`` and report the profit as incomplete.
    """
    if product.track_stock and balance is not None and balance.avg_cost is not None:
        return cost(balance.avg_cost), WEIGHTED_AVERAGE
    if variant.standard_cost is not None:
        return cost(variant.standard_cost), MANUAL
    if product.default_purchase_cost is not None:
        return cost(product.default_purchase_cost), PRODUCT_DEFAULT
    return None, MISSING


async def balances_for(
    session: AsyncSession, warehouse_id: uuid.UUID, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, StockBalance]:
    """Read-only balance lookup; does not create or lock rows."""
    if not variant_ids:
        return {}
    rows = (
        await session.execute(
            select(StockBalance).where(
                StockBalance.warehouse_id == warehouse_id,
                StockBalance.product_variant_id.in_(variant_ids),
            )
        )
    ).scalars().all()
    return {b.product_variant_id: b for b in rows}
