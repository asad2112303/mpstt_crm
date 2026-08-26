"""Customer endpoints and the atomic first-order conversion."""
import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.orders import SalesOrder
from app.models.organization import Activity, CustomerProfile, Organization, Sample
from app.schemas.customers import ConvertIn, CustomerUpdate, OrderOut, TimelineEvent
from app.schemas.organization import OrganizationOut
from app.services.audit import write_audit
from app.services.conversion import (
    ConversionInput,
    OrderItemInput,
    convert_prospect_to_customer_order,
)
from app.services.idempotency import require_idempotency_key, run_idempotent

router = APIRouter(tags=["customers"])


def _org_out(org: Organization) -> dict:
    return OrganizationOut.model_validate(org).model_dump(mode="json")


async def _get_customer(db: AsyncSession, organization_id: uuid.UUID) -> Organization:
    org = (
        await db.execute(
            select(Organization)
            .options(
                selectinload(Organization.prospect_profile),
                selectinload(Organization.customer_profile),
            )
            .where(Organization.id == organization_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if org is None or org.lifecycle_status != "customer":
        raise NotFoundError("Customer not found.")
    return org


@router.get("/customers")
async def list_customers(
    params: ListParams = Depends(list_params),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Organization)
        .join(CustomerProfile, CustomerProfile.organization_id == Organization.id)
        .options(
            selectinload(Organization.prospect_profile),
            selectinload(Organization.customer_profile),
        )
        .where(Organization.lifecycle_status == "customer")
    )
    if params.search:
        needle = f"%{params.search.strip()}%"
        stmt = stmt.where(
            or_(
                Organization.name.ilike(needle),
                Organization.org_code.ilike(needle),
                CustomerProfile.customer_code.ilike(needle),
                Organization.city.ilike(needle),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(CustomerProfile.customer_since.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok([_org_out(o) for o in rows], page=params.page, page_size=params.page_size, total=total)


@router.get("/customers/{organization_id}")
async def get_customer(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_customer(db, organization_id)
    return ok(_org_out(org))


@router.patch("/customers/{organization_id}")
async def update_customer(
    organization_id: uuid.UUID,
    payload: CustomerUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_customer(db, organization_id)
    profile = org.customer_profile
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")
    old = {k: str(getattr(profile, k)) for k in changes}
    for field, value in changes.items():
        setattr(profile, field, value)
    await db.flush()
    await write_audit(db, action="customer.updated", entity_type="organization",
                      entity_id=org.id, old=old, new={k: str(v) for k, v in changes.items()})
    await db.commit()
    org = await _get_customer(db, organization_id)
    return ok(_org_out(org))


@router.get("/customers/{organization_id}/timeline")
async def customer_timeline(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await _get_customer(db, organization_id)
    events: list[TimelineEvent] = []

    for a in (
        await db.execute(
            select(Activity).where(Activity.organization_id == org.id)
            .order_by(Activity.happened_at.desc()).limit(100)
        )
    ).scalars():
        events.append(TimelineEvent(
            kind=f"activity.{a.activity_type}", at=a.happened_at,
            title=a.outcome or a.activity_type.replace("_", " ").title(),
            detail=a.notes, reference_id=str(a.id),
        ))
    for s in (
        await db.execute(
            select(Sample).where(Sample.organization_id == org.id)
            .order_by(Sample.issued_at.desc()).limit(50)
        )
    ).scalars():
        events.append(TimelineEvent(
            kind="sample", at=s.issued_at, title=f"Sample issued ({s.quantity})",
            detail=s.feedback, reference_id=str(s.id),
        ))
    for o in (
        await db.execute(
            select(SalesOrder).where(SalesOrder.organization_id == org.id)
            .order_by(SalesOrder.created_at.desc()).limit(50)
        )
    ).scalars():
        events.append(TimelineEvent(
            kind="order", at=o.created_at, title=f"Order {o.order_number} ({o.status})",
            detail=f"PKR {o.grand_total}", reference_id=str(o.id),
        ))

    events.sort(key=lambda e: e.at, reverse=True)
    return ok([e.model_dump(mode="json") for e in events[:150]])


@router.post("/prospects/{organization_id}/convert-to-customer-order", status_code=201)
async def convert_to_customer_order(
    organization_id: uuid.UUID,
    payload: ConvertIn,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    key = require_idempotency_key(request)

    async def do_convert() -> dict:
        _, order = await convert_prospect_to_customer_order(
            db,
            organization_id=organization_id,
            user_id=user.id,
            data=ConversionInput(
                items=[
                    OrderItemInput(
                        product_variant_id=i.product_variant_id,
                        quantity=i.quantity,
                        unit_price=i.unit_price,
                        discount_percent=i.discount_percent,
                    )
                    for i in payload.items
                ],
                branch_id=payload.branch_id,
                customer_po_number=payload.customer_po_number,
                is_direct_po=payload.is_direct_po,
                source_quotation_id=payload.source_quotation_id,
                expected_delivery_date=payload.expected_delivery_date,
                payment_terms_days=payload.payment_terms_days,
                credit_limit=payload.credit_limit,
                order_notes=payload.order_notes,
            ),
        )
        fresh = (
            await db.execute(
                select(Organization)
                .options(
                    selectinload(Organization.prospect_profile),
                    selectinload(Organization.customer_profile),
                )
                .where(Organization.id == organization_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        return {
            "organization": _org_out(fresh),
            "order": OrderOut.model_validate(order).model_dump(mode="json"),
        }

    body, status_code, replayed = await run_idempotent(
        db,
        user_id=user.id,
        action="prospect.convert",
        key=key,
        payload=payload.model_dump(mode="json"),
        fn=do_convert,
        status_code=201,
    )
    await db.commit()
    response.status_code = status_code
    return ok(body)
