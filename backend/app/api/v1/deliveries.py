"""M8: delivery endpoints — challans, dispatch, POD-gated completion."""
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.deliveries import Delivery
from app.models.orders import SalesOrder
from app.models.organization import Organization
from app.services.audit import write_audit
from app.services.deliveries import complete_delivery, create_delivery, remaining_for_order
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.numbering import allocate_number
from app.services.pdf import render_pdf

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


class DeliveryLineIn(BaseModel):
    sales_order_item_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class DeliveryCreateIn(BaseModel):
    sales_order_id: uuid.UUID
    items: list[DeliveryLineIn] = Field(min_length=1)
    scheduled_date: datetime | None = None
    delivery_person: str | None = Field(default=None, max_length=150)
    vehicle: str | None = Field(default=None, max_length=100)
    branch_id: uuid.UUID | None = None


class LineResultIn(BaseModel):
    delivery_item_id: uuid.UUID
    delivered_quantity: Decimal = Field(ge=0)
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    rejection_remarks: str | None = None


class CompleteIn(BaseModel):
    receiver_name: str = Field(min_length=2, max_length=150)
    receiver_designation: str | None = Field(default=None, max_length=100)
    received_at: datetime | None = None
    signed_challan_document_id: uuid.UUID | None = None
    signature_document_id: uuid.UUID | None = None
    photo_document_id: uuid.UUID | None = None
    line_results: list[LineResultIn] = Field(default_factory=list)


class DeliveryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sales_order_item_id: uuid.UUID
    product_variant_id: uuid.UUID
    description_snapshot: str
    uom_code: str
    dispatched_quantity: Decimal
    delivered_quantity: Decimal
    rejected_quantity: Decimal
    rejection_remarks: str | None


class PodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    receiver_name: str
    receiver_designation: str | None
    received_at: datetime
    signed_challan_document_id: uuid.UUID | None
    signature_document_id: uuid.UUID | None
    photo_document_id: uuid.UUID | None


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    challan_number: str
    sales_order_id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None
    status: str
    scheduled_date: datetime | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    delivery_person: str | None
    vehicle: str | None
    remarks: str | None
    cancelled_reason: str | None
    created_at: datetime
    items: list[DeliveryItemOut] = []
    pod: PodOut | None = None


def delivery_out(d: Delivery) -> dict:
    return DeliveryOut.model_validate(d).model_dump(mode="json")


async def _get_delivery(db: AsyncSession, delivery_id: uuid.UUID) -> Delivery:
    d = (
        await db.execute(
            select(Delivery)
            .options(selectinload(Delivery.items), selectinload(Delivery.pod))
            .where(Delivery.id == delivery_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if d is None:
        raise NotFoundError("Delivery not found.")
    return d


@router.get("")
async def list_deliveries(
    params: ListParams = Depends(list_params),
    sales_order_id: uuid.UUID | None = Query(None),
    missing_pod: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Delivery).options(selectinload(Delivery.items), selectinload(Delivery.pod))
    if sales_order_id:
        stmt = stmt.where(Delivery.sales_order_id == sales_order_id)
    if params.status:
        stmt = stmt.where(Delivery.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        org_ids = select(Organization.id).where(Organization.name.ilike(needle))
        stmt = stmt.where(
            Delivery.challan_number.ilike(needle) | Delivery.organization_id.in_(org_ids)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Delivery.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    data = [delivery_out(d) for d in rows]
    if missing_pod:
        data = [d for d in data if d["status"] == "delivered" and d["pod"] is None]
    return ok(data, page=params.page, page_size=params.page_size, total=total)


@router.get("/order/{order_id}/remaining")
async def order_remaining(
    order_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    order = (
        await db.execute(
            select(SalesOrder)
            .options(selectinload(SalesOrder.items))
            .where(SalesOrder.id == order_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    remaining = await remaining_for_order(db, order)
    return ok([
        {
            "sales_order_item_id": str(item.id),
            "description": item.description_snapshot,
            "uom_code": item.uom_code,
            "ordered": str(info["ordered"]),
            "delivered": str(info["delivered"]),
            "pending": str(info["pending"]),
            "remaining": str(info["remaining"]),
        }
        for item, info in ((i, remaining[i.id]) for i in order.items)
    ])


@router.post("", status_code=201)
async def create_challan(
    payload: DeliveryCreateIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    challan_number = await allocate_number(db, "DC")
    delivery = await create_delivery(
        db,
        order_id=payload.sales_order_id,
        user_id=user.id,
        lines=[line.model_dump() for line in payload.items],
        challan_number=challan_number,
        scheduled_date=payload.scheduled_date,
        delivery_person=payload.delivery_person,
        vehicle=payload.vehicle,
        branch_id=payload.branch_id,
    )
    await db.commit()
    return ok(delivery_out(await _get_delivery(db, delivery.id)))


@router.get("/{delivery_id}")
async def get_delivery(
    delivery_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(delivery_out(await _get_delivery(db, delivery_id)))


@router.post("/{delivery_id}/dispatch")
async def dispatch(
    delivery_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    delivery = await _get_delivery(db, delivery_id)
    if delivery.status != "draft":
        raise ConflictError("Only a draft challan can be dispatched.", code="DELIVERY_NOT_DRAFT")
    from datetime import UTC

    delivery.status = "dispatched"
    delivery.dispatched_at = datetime.now(UTC)
    delivery.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="delivery.dispatched", entity_type="delivery",
                      entity_id=delivery.id, new={"challan": delivery.challan_number})
    await db.commit()
    return ok(delivery_out(delivery))


@router.post("/{delivery_id}/complete")
async def complete(
    delivery_id: uuid.UUID,
    payload: CompleteIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    key = require_idempotency_key(request)

    async def do_complete() -> dict:
        delivery = await complete_delivery(
            db,
            delivery_id=delivery_id,
            user_id=user.id,
            line_results=[r.model_dump() for r in payload.line_results],
            pod=payload.model_dump(exclude={"line_results"}),
        )
        return delivery_out(delivery)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="delivery.complete", key=key,
        payload={"delivery_id": str(delivery_id)}, fn=do_complete,
    )
    await db.commit()
    return ok(body)


@router.post("/{delivery_id}/cancel")
async def cancel(
    delivery_id: uuid.UUID,
    payload: dict,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reason = (payload or {}).get("reason", "").strip()
    if not reason:
        raise ValidationFailedError("A reason is required to cancel a challan.",
                                    field_errors={"reason": ["Required"]})
    delivery = await _get_delivery(db, delivery_id)
    if delivery.status not in ("draft", "dispatched"):
        raise ConflictError("A completed delivery cannot be cancelled — use a reversal process.",
                            code="DELIVERY_NOT_OPEN")
    delivery.status = "cancelled"
    delivery.cancelled_reason = reason
    delivery.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="delivery.cancelled", entity_type="delivery",
                      entity_id=delivery.id, reason=reason)
    await db.commit()
    return ok(delivery_out(delivery))


@router.get("/{delivery_id}/challan")
async def challan_pdf(
    delivery_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    delivery = await _get_delivery(db, delivery_id)
    from app.api.v1.quotations import _company_dict

    company = await _company_dict(db)
    org = await db.get(Organization, delivery.organization_id)
    order = await db.get(SalesOrder, delivery.sales_order_id)
    context = {
        "company": company,
        "challan": {
            "number": delivery.challan_number,
            "date": (delivery.scheduled_date or delivery.created_at).date().isoformat(),
            "order_number": order.order_number if order else "",
            "delivery_person": delivery.delivery_person,
            "vehicle": delivery.vehicle,
            "status": delivery.status,
        },
        "customer": {"name": org.name, "city": org.city, "phone": org.phone},
        "items": [
            {
                "sn": index + 1,
                "description": item.description_snapshot,
                "uom": item.uom_code,
                "quantity": item.dispatched_quantity,
            }
            for index, item in enumerate(delivery.items)
        ],
        "pod": {
            "receiver_name": delivery.pod.receiver_name if delivery.pod else None,
            "receiver_designation": delivery.pod.receiver_designation if delivery.pod else None,
            "received_at": delivery.pod.received_at.isoformat() if delivery.pod else None,
        },
    }
    content = render_pdf("challan.html", context)
    return RawResponse(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{delivery.challan_number}.pdf"',
                 "Cache-Control": "no-store"},
    )
