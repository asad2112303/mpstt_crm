"""M6 inventory rules: confirm-with-reservation, release, fulfilment, adjustments.

Lock ordering (frozen): number sequences → order row → stock balances sorted by
(warehouse_id, product_variant_id). Every multi-row transaction acquires locks
in that order to avoid deadlocks.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.inventory import StockBalance, StockMovement, StockReservation, Warehouse
from app.models.orders import SalesOrder
from app.services.audit import write_audit


async def get_default_warehouse(session: AsyncSession) -> Warehouse:
    wh = (
        await session.execute(
            select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.created_at)
        )
    ).scalars().first()
    if wh is None:
        raise ConflictError(
            "No active warehouse exists. Create one under Inventory before confirming orders.",
            code="NO_WAREHOUSE",
        )
    return wh


async def lock_balances(
    session: AsyncSession, warehouse_id: uuid.UUID, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, StockBalance]:
    """Create missing balance rows, then lock them all in a stable order."""
    for variant_id in sorted(set(variant_ids)):
        await session.execute(
            pg_insert(StockBalance)
            .values(warehouse_id=warehouse_id, product_variant_id=variant_id)
            .on_conflict_do_nothing(index_elements=["warehouse_id", "product_variant_id"])
        )
    rows = (
        await session.execute(
            select(StockBalance)
            .where(
                StockBalance.warehouse_id == warehouse_id,
                StockBalance.product_variant_id.in_(variant_ids),
            )
            .order_by(StockBalance.warehouse_id, StockBalance.product_variant_id)
            .with_for_update()
        )
    ).scalars().all()
    return {b.product_variant_id: b for b in rows}


async def confirm_order(
    session: AsyncSession, *, order_id: uuid.UUID, user_id: str,
    warehouse_id: uuid.UUID | None = None,
) -> SalesOrder:
    """Reserve available stock line by line; all-or-nothing."""
    order = (
        await session.execute(
            select(SalesOrder).where(SalesOrder.id == order_id).with_for_update(of=SalesOrder)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    if order.status != "draft":
        raise ConflictError("Only a draft order can be confirmed.", code="ORDER_NOT_DRAFT")
    await session.refresh(order, ["items"])
    if not order.items:
        raise ValidationFailedError("The order has no items.")

    warehouse = (
        await session.get(Warehouse, warehouse_id) if warehouse_id
        else await get_default_warehouse(session)
    )
    if warehouse is None or not warehouse.is_active:
        raise ValidationFailedError("Warehouse not found or inactive.")

    balances = await lock_balances(
        session, warehouse.id, [i.product_variant_id for i in order.items]
    )

    shortages: dict[str, list[str]] = {}
    for index, item in enumerate(order.items):
        balance = balances[item.product_variant_id]
        available = balance.on_hand - balance.reserved
        if item.quantity > available:
            shortages[f"items.{index}"] = [
                f"Requested {item.quantity}, available {available} in {warehouse.code}"
            ]
    if shortages:
        raise ConflictError(
            "Insufficient available stock to confirm this order.",
            code="INSUFFICIENT_STOCK",
            field_errors=shortages,
        )

    for item in order.items:
        balance = balances[item.product_variant_id]
        balance.reserved += item.quantity
        balance.version += 1
        session.add(
            StockReservation(
                sales_order_item_id=item.id,
                warehouse_id=warehouse.id,
                product_variant_id=item.product_variant_id,
                quantity=item.quantity,
            )
        )

    order.status = "confirmed"
    order.updated_by = uuid.UUID(user_id)
    await session.flush()
    await write_audit(
        session, action="order.confirmed", entity_type="sales_order", entity_id=order.id,
        new={"order_number": order.order_number, "warehouse": warehouse.code},
    )
    return order


async def release_order_reservations(
    session: AsyncSession, order: SalesOrder, *, reason: str
) -> None:
    """Release active reservations (order cancel). Locks balances first."""
    item_ids = [i.id for i in order.items]
    reservations = (
        await session.execute(
            select(StockReservation)
            .where(
                StockReservation.sales_order_item_id.in_(item_ids),
                StockReservation.status == "active",
            )
            .order_by(StockReservation.warehouse_id, StockReservation.product_variant_id)
            .with_for_update()
        )
    ).scalars().all()
    if not reservations:
        return
    by_wh: dict[uuid.UUID, list[StockReservation]] = {}
    for r in reservations:
        by_wh.setdefault(r.warehouse_id, []).append(r)
    for warehouse_id, rows in by_wh.items():
        balances = await lock_balances(session, warehouse_id, [r.product_variant_id for r in rows])
        for r in rows:
            balance = balances[r.product_variant_id]
            balance.reserved -= r.quantity
            balance.version += 1
            r.status = "released"
            r.released_at = datetime.now(UTC)
    await session.flush()


async def admin_adjust_stock(
    session: AsyncSession, *, warehouse_id: uuid.UUID, product_variant_id: uuid.UUID,
    quantity: Decimal, reason: str, reference: str | None, user_id: str,
    movement_type: str = "adjustment",
) -> StockBalance:
    """Signed adjustment; never lets on_hand fall below reserved."""
    if quantity == 0:
        raise ValidationFailedError("Adjustment quantity cannot be zero.")
    balances = await lock_balances(session, warehouse_id, [product_variant_id])
    balance = balances[product_variant_id]
    new_on_hand = balance.on_hand + quantity
    if new_on_hand < 0:
        raise ConflictError("Adjustment would make on-hand negative.", code="NEGATIVE_STOCK")
    if new_on_hand < balance.reserved:
        raise ConflictError(
            "Adjustment would make on-hand fall below reserved stock.",
            code="RESERVED_EXCEEDS_ON_HAND",
        )
    balance.on_hand = new_on_hand
    balance.version += 1
    session.add(
        StockMovement(
            warehouse_id=warehouse_id,
            product_variant_id=product_variant_id,
            quantity=quantity,
            movement_type=movement_type,
            reference_type="manual",
            reference_id=reference,
            notes=reason,
            created_by=uuid.UUID(user_id),
        )
    )
    await session.flush()
    await write_audit(
        session, action="stock.adjusted", entity_type="stock_balance",
        entity_id=f"{warehouse_id}:{product_variant_id}",
        new={"quantity": str(quantity), "movement_type": movement_type},
        reason=reason,
    )
    return balance
