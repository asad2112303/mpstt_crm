"""M6: sales order endpoints — direct PO orders, confirm/reserve, cancel,
fulfilment statuses."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.orders import SalesOrder
from app.models.organization import Organization
from app.schemas.customers import OrderItemIn, OrderOut
from app.services.audit import write_audit
from app.services.conversion import OrderItemInput, build_order_items
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.inventory import confirm_order, release_order_reservations
from app.services.money import sum_lines
from app.services.numbering import allocate_number

router = APIRouter(prefix="/orders", tags=["orders"])


class DirectOrderIn(BaseModel):
    organization_id: uuid.UUID
    items: list[OrderItemIn] = Field(min_length=1)
    branch_id: uuid.UUID | None = None
    customer_po_number: str | None = Field(default=None, max_length=100)
    customer_po_document_id: uuid.UUID | None = None
    expected_delivery_date: date | None = None
    notes: str | None = None


class ConfirmIn(BaseModel):
    warehouse_id: uuid.UUID | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


async def _get_order(db: AsyncSession, order_id: uuid.UUID, *, for_update: bool = False) -> SalesOrder:
    stmt = (
        select(SalesOrder)
        .options(selectinload(SalesOrder.items))
        .where(SalesOrder.id == order_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=SalesOrder)
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    return order


def order_out(order: SalesOrder) -> dict:
    return OrderOut.model_validate(order).model_dump(mode="json")


@router.get("")
async def list_orders(
    params: ListParams = Depends(list_params),
    organization_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(SalesOrder).options(selectinload(SalesOrder.items))
    if organization_id:
        stmt = stmt.where(SalesOrder.organization_id == organization_id)
    if params.status:
        stmt = stmt.where(SalesOrder.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        org_ids = select(Organization.id).where(Organization.name.ilike(needle))
        stmt = stmt.where(
            SalesOrder.order_number.ilike(needle)
            | SalesOrder.customer_po_number.ilike(needle)
            | SalesOrder.organization_id.in_(org_ids)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(SalesOrder.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok([order_out(o) for o in rows], page=params.page, page_size=params.page_size, total=total)


@router.post("", status_code=201)
async def create_direct_order(
    payload: DirectOrderIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Direct customer-PO order (reorder). First orders for prospects go
    through the conversion endpoint instead."""
    org = await db.get(Organization, payload.organization_id)
    if org is None or not org.is_active:
        raise ValidationFailedError("Organization not found or inactive.")
    if org.lifecycle_status != "customer":
        raise ConflictError(
            "This organization is still a prospect. Use first-order conversion instead.",
            code="NOT_A_CUSTOMER",
        )

    items, amounts = await build_order_items(
        db,
        [
            OrderItemInput(
                product_variant_id=i.product_variant_id,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount_percent=i.discount_percent,
            )
            for i in payload.items
        ],
    )
    totals = sum_lines(amounts)
    order = SalesOrder(
        order_number=await allocate_number(db, "ORD"),
        organization_id=org.id,
        branch_id=payload.branch_id,
        is_direct_po=True,
        customer_po_number=payload.customer_po_number,
        customer_po_document_id=payload.customer_po_document_id,
        expected_delivery_date=payload.expected_delivery_date,
        status="draft",
        subtotal=totals.subtotal,
        discount_total=totals.discount_total,
        tax_total=totals.tax_total,
        grand_total=totals.grand_total,
        notes=payload.notes,
        created_by=uuid.UUID(user.id),
        items=items,
    )
    db.add(order)
    await db.flush()
    await write_audit(db, action="order.created", entity_type="sales_order",
                      entity_id=order.id,
                      new={"order_number": order.order_number, "direct_po": True})
    await db.commit()
    return ok(order_out(await _get_order(db, order.id)))


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(order_out(await _get_order(db, order_id)))


class DraftOrderUpdateIn(BaseModel):
    items: list[OrderItemIn] | None = None
    branch_id: uuid.UUID | None = None
    customer_po_number: str | None = Field(default=None, max_length=100)
    expected_delivery_date: date | None = None
    notes: str | None = None


@router.put("/{order_id}")
async def update_draft_order(
    order_id: uuid.UUID,
    payload: DraftOrderUpdateIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Draft orders stay editable; confirmed+ orders are frozen snapshots."""
    order = await _get_order(db, order_id, for_update=True)
    if order.status != "draft":
        raise ConflictError(
            "Only a draft order can be edited. Confirmed orders are frozen.",
            code="ORDER_NOT_DRAFT",
        )
    for field in ("branch_id", "customer_po_number", "expected_delivery_date", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(order, field, value)
    if payload.items is not None:
        items, amounts = await build_order_items(
            db,
            [
                OrderItemInput(
                    product_variant_id=i.product_variant_id,
                    quantity=i.quantity,
                    unit_price=i.unit_price,
                    discount_percent=i.discount_percent,
                )
                for i in payload.items
            ],
        )
        totals = sum_lines(amounts)
        order.items.clear()
        await db.flush()
        order.items.extend(items)
        order.subtotal = totals.subtotal
        order.discount_total = totals.discount_total
        order.tax_total = totals.tax_total
        order.grand_total = totals.grand_total
    order.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="order.draft_updated", entity_type="sales_order",
                      entity_id=order.id, new={"order_number": order.order_number})
    await db.commit()
    return ok(order_out(await _get_order(db, order_id)))


@router.post("/{order_id}/confirm")
async def confirm(
    order_id: uuid.UUID,
    payload: ConfirmIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    key = require_idempotency_key(request)

    async def do_confirm() -> dict:
        order = await confirm_order(
            db, order_id=order_id, user_id=user.id, warehouse_id=payload.warehouse_id
        )
        return order_out(order)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="order.confirm", key=key,
        payload={"order_id": str(order_id)}, fn=do_confirm,
    )
    await db.commit()
    return ok(body)


@router.post("/{order_id}/cancel")
async def cancel(
    order_id: uuid.UUID,
    payload: CancelIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    order = await _get_order(db, order_id, for_update=True)
    if order.status in ("partially_delivered", "fully_delivered", "completed", "cancelled"):
        raise ConflictError(
            f"An order in status '{order.status}' cannot be cancelled.",
            code="ORDER_NOT_CANCELLABLE",
        )
    await release_order_reservations(db, order, reason=payload.reason)
    old_status = order.status
    order.status = "cancelled"
    order.cancelled_reason = payload.reason
    order.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="order.cancelled", entity_type="sales_order",
                      entity_id=order.id, old={"status": old_status},
                      new={"status": "cancelled"}, reason=payload.reason)
    await db.commit()
    return ok(order_out(order))


@router.post("/{order_id}/mark-preparing")
async def mark_preparing(
    order_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _manual_transition(db, order_id, user, from_statuses=("confirmed",),
                                    to_status="preparing")


@router.post("/{order_id}/mark-ready")
async def mark_ready(
    order_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _manual_transition(db, order_id, user, from_statuses=("confirmed", "preparing"),
                                    to_status="ready")


async def _manual_transition(
    db: AsyncSession, order_id: uuid.UUID, user: CurrentUser,
    *, from_statuses: tuple, to_status: str,
) -> dict:
    order = await _get_order(db, order_id, for_update=True)
    if order.status not in from_statuses:
        raise ConflictError(
            f"Cannot move an order from '{order.status}' to '{to_status}'. "
            "Delivery-driven statuses are derived automatically.",
            code="INVALID_STATE_TRANSITION",
        )
    old = order.status
    order.status = to_status
    order.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action=f"order.{to_status}", entity_type="sales_order",
                      entity_id=order.id, old={"status": old}, new={"status": to_status})
    await db.commit()
    return ok(order_out(order))
