"""M8 delivery rules: remaining quantities, completion transaction, POD gate."""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.deliveries import Delivery, DeliveryItem, ProofOfDelivery
from app.models.inventory import StockMovement, StockReservation
from app.models.orders import SalesOrder
from app.services.audit import write_audit
from app.services.inventory import get_default_warehouse, lock_balances


async def delivered_by_order_item(session: AsyncSession, order_item_ids: list[uuid.UUID]) -> dict:
    """Delivered qty per order item across COMPLETED deliveries."""
    rows = (
        await session.execute(
            select(
                DeliveryItem.sales_order_item_id,
                func.coalesce(func.sum(DeliveryItem.delivered_quantity), 0),
            )
            .join(Delivery, DeliveryItem.delivery_id == Delivery.id)
            .where(
                DeliveryItem.sales_order_item_id.in_(order_item_ids),
                Delivery.status == "delivered",
            )
            .group_by(DeliveryItem.sales_order_item_id)
        )
    ).all()
    return {row[0]: Decimal(row[1]) for row in rows}


async def pending_by_order_item(session: AsyncSession, order_item_ids: list[uuid.UUID]) -> dict:
    """Dispatched-but-not-yet-completed qty per order item (open challans)."""
    rows = (
        await session.execute(
            select(
                DeliveryItem.sales_order_item_id,
                func.coalesce(func.sum(DeliveryItem.dispatched_quantity), 0),
            )
            .join(Delivery, DeliveryItem.delivery_id == Delivery.id)
            .where(
                DeliveryItem.sales_order_item_id.in_(order_item_ids),
                Delivery.status.in_(("draft", "dispatched")),
            )
            .group_by(DeliveryItem.sales_order_item_id)
        )
    ).all()
    return {row[0]: Decimal(row[1]) for row in rows}


async def remaining_for_order(session: AsyncSession, order: SalesOrder) -> dict:
    item_ids = [i.id for i in order.items]
    delivered = await delivered_by_order_item(session, item_ids)
    pending = await pending_by_order_item(session, item_ids)
    return {
        item.id: {
            "ordered": item.quantity,
            "delivered": delivered.get(item.id, Decimal("0")),
            "pending": pending.get(item.id, Decimal("0")),
            "remaining": item.quantity
            - delivered.get(item.id, Decimal("0"))
            - pending.get(item.id, Decimal("0")),
        }
        for item in order.items
    }


async def create_delivery(
    session: AsyncSession, *, order_id: uuid.UUID, user_id: str,
    lines: list[dict], challan_number: str,
    scheduled_date: datetime | None, delivery_person: str | None,
    vehicle: str | None, branch_id: uuid.UUID | None,
) -> Delivery:
    order = (
        await session.execute(
            select(SalesOrder)
            .options(selectinload(SalesOrder.items))
            .where(SalesOrder.id == order_id)
            .with_for_update(of=SalesOrder)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    if order.status not in ("confirmed", "preparing", "ready", "partially_delivered"):
        raise ConflictError(
            f"Deliveries cannot be created for an order in status '{order.status}'.",
            code="ORDER_NOT_DELIVERABLE",
        )
    if not lines:
        raise ValidationFailedError("A delivery needs at least one line.")

    remaining = await remaining_for_order(session, order)
    order_items = {i.id: i for i in order.items}
    field_errors: dict[str, list[str]] = {}
    delivery_items: list[DeliveryItem] = []
    for index, line in enumerate(lines):
        item_id = uuid.UUID(str(line["sales_order_item_id"]))
        quantity = Decimal(str(line["quantity"]))
        item = order_items.get(item_id)
        if item is None:
            field_errors[f"items.{index}"] = ["Not an item of this order"]
            continue
        if quantity <= 0:
            field_errors[f"items.{index}.quantity"] = ["Must be positive"]
            continue
        rem = remaining[item_id]["remaining"]
        if quantity > rem:
            field_errors[f"items.{index}.quantity"] = [
                f"Exceeds remaining quantity ({rem} left, incl. open challans)"
            ]
            continue
        delivery_items.append(
            DeliveryItem(
                sales_order_item_id=item_id,
                product_variant_id=item.product_variant_id,
                description_snapshot=item.description_snapshot,
                uom_code=item.uom_code,
                dispatched_quantity=quantity,
            )
        )
    if field_errors:
        raise ValidationFailedError(
            "Delivery quantities exceed what remains on the order.",
            field_errors=field_errors,
        )

    warehouse = await get_default_warehouse(session)
    delivery = Delivery(
        challan_number=challan_number,
        sales_order_id=order.id,
        organization_id=order.organization_id,
        branch_id=branch_id or order.branch_id,
        warehouse_id=warehouse.id,
        scheduled_date=scheduled_date,
        delivery_person=delivery_person,
        vehicle=vehicle,
        created_by=uuid.UUID(user_id),
        items=delivery_items,
    )
    session.add(delivery)
    await session.flush()
    await write_audit(session, action="delivery.created", entity_type="delivery",
                      entity_id=delivery.id,
                      new={"challan": challan_number, "order": order.order_number})
    return delivery


def _derive_order_status(order: SalesOrder, delivered: dict) -> str:
    fully = all(
        delivered.get(item.id, Decimal("0")) >= item.quantity for item in order.items
    )
    any_delivered = any(delivered.get(item.id, Decimal("0")) > 0 for item in order.items)
    if fully:
        return "fully_delivered"
    if any_delivered:
        return "partially_delivered"
    return order.status


async def complete_delivery(
    session: AsyncSession, *, delivery_id: uuid.UUID, user_id: str,
    line_results: list[dict], pod: dict,
) -> Delivery:
    """POD-gated completion: stock out, reservations fulfilled, statuses derived.

    Lock order: delivery -> order -> order items -> reservations -> balances.
    """
    delivery = (
        await session.execute(
            select(Delivery)
            .options(selectinload(Delivery.items), selectinload(Delivery.pod))
            .where(Delivery.id == delivery_id)
            .with_for_update(of=Delivery)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if delivery is None:
        raise NotFoundError("Delivery not found.")
    if delivery.status not in ("draft", "dispatched"):
        raise ConflictError("This delivery has already been completed or cancelled.",
                            code="DELIVERY_NOT_OPEN")

    # POD gate: receiver identity + received time + signed challan or signature.
    receiver_name = (pod.get("receiver_name") or "").strip()
    if not receiver_name:
        raise ValidationFailedError(
            "POD is required: receiver name is missing.",
            field_errors={"pod.receiver_name": ["Required"]},
        )
    if not pod.get("signed_challan_document_id") and not pod.get("signature_document_id"):
        raise ValidationFailedError(
            "POD is required: attach the signed challan or a signature capture.",
            field_errors={"pod.signed_challan_document_id": ["Signed challan or signature required"]},
        )

    order = (
        await session.execute(
            select(SalesOrder)
            .options(selectinload(SalesOrder.items))
            .where(SalesOrder.id == delivery.sales_order_id)
            .with_for_update(of=SalesOrder)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    results = {uuid.UUID(str(r["delivery_item_id"])): r for r in line_results}
    field_errors: dict[str, list[str]] = {}
    for index, item in enumerate(delivery.items):
        result = results.get(item.id)
        if result is None:
            # Default: everything dispatched was delivered.
            item.delivered_quantity = item.dispatched_quantity
            continue
        delivered_q = Decimal(str(result.get("delivered_quantity", item.dispatched_quantity)))
        rejected_q = Decimal(str(result.get("rejected_quantity", 0)))
        if delivered_q < 0 or rejected_q < 0:
            field_errors[f"items.{index}"] = ["Quantities cannot be negative"]
        elif delivered_q + rejected_q > item.dispatched_quantity:
            field_errors[f"items.{index}"] = [
                "delivered + rejected cannot exceed the dispatched quantity"
            ]
        else:
            item.delivered_quantity = delivered_q
            item.rejected_quantity = rejected_q
            item.rejection_remarks = result.get("rejection_remarks")
    if field_errors:
        raise ValidationFailedError("Invalid delivery result quantities.",
                                    field_errors=field_errors)

    # Stock out + reservation fulfilment for DELIVERED quantities only.
    warehouse_id = delivery.warehouse_id
    variant_ids = [i.product_variant_id for i in delivery.items if i.delivered_quantity > 0]
    if variant_ids:
        balances = await lock_balances(session, warehouse_id, variant_ids)
        for item in delivery.items:
            if item.delivered_quantity <= 0:
                continue
            balance = balances[item.product_variant_id]
            if balance.on_hand < item.delivered_quantity:
                raise ConflictError(
                    "Stock reconciliation error: on-hand is lower than the delivered "
                    "quantity. Check adjustments before completing.",
                    code="STOCK_RECONCILIATION",
                )
            reservation = (
                await session.execute(
                    select(StockReservation)
                    .where(
                        StockReservation.sales_order_item_id == item.sales_order_item_id,
                        StockReservation.status == "active",
                    )
                    .with_for_update()
                )
            ).scalars().first()
            release_from_reserved = Decimal("0")
            if reservation is not None:
                release_from_reserved = min(reservation.quantity, item.delivered_quantity)
                reservation.quantity -= release_from_reserved
                if reservation.quantity <= 0:
                    reservation.status = "fulfilled"
                    reservation.fulfilled_at = datetime.now(UTC)
            balance.on_hand -= item.delivered_quantity
            balance.reserved -= release_from_reserved
            balance.version += 1
            session.add(
                StockMovement(
                    warehouse_id=warehouse_id,
                    product_variant_id=item.product_variant_id,
                    quantity=-item.delivered_quantity,
                    movement_type="delivery_out",
                    reference_type="delivery",
                    reference_id=delivery.challan_number,
                    created_by=uuid.UUID(user_id),
                )
            )

    received_at = pod.get("received_at") or datetime.now(UTC)
    session.add(
        ProofOfDelivery(
            delivery_id=delivery.id,
            receiver_name=receiver_name,
            receiver_designation=pod.get("receiver_designation"),
            received_at=received_at,
            signed_challan_document_id=pod.get("signed_challan_document_id"),
            signature_document_id=pod.get("signature_document_id"),
            photo_document_id=pod.get("photo_document_id"),
        )
    )

    delivery.status = "delivered"
    delivery.delivered_at = received_at
    delivery.updated_by = uuid.UUID(user_id)
    await session.flush()

    delivered = await delivered_by_order_item(session, [i.id for i in order.items])
    new_status = _derive_order_status(order, delivered)
    if new_status != order.status:
        order.status = new_status
    await session.flush()
    await write_audit(session, action="delivery.completed", entity_type="delivery",
                      entity_id=delivery.id,
                      new={"challan": delivery.challan_number, "order_status": order.status,
                           "receiver": receiver_name})
    return delivery
