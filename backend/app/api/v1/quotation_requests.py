"""Website quotation requests — the inbox for public.quotation_requests.

Read-only intake plus a small workflow: the website owns every submitted
field, the CRM owns only ``status``, ``internal_notes`` and ``contacted_at``.
Nothing here ever inserts a request — that is /api/quote's job on the website.
"""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.website import OPEN_STATUSES, QUOTATION_REQUEST_STATUSES, QuotationRequest
from app.schemas.website import QuotationRequestOut, QuotationRequestUpdate
from app.services.audit import write_audit

router = APIRouter(prefix="/quotation-requests", tags=["quotation-requests"])


def _out(row: QuotationRequest) -> dict:
    return QuotationRequestOut.model_validate(row).model_dump(mode="json")


async def _get_request(
    db: AsyncSession, request_id: uuid.UUID, *, for_update: bool = False
) -> QuotationRequest:
    stmt = select(QuotationRequest).where(QuotationRequest.id == request_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Quotation request not found.")
    return row


@router.get("")
async def list_quotation_requests(
    params: ListParams = Depends(list_params),
    intent: str | None = Query(None, max_length=20),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(QuotationRequest)
    if params.status:
        if params.status == "open":
            stmt = stmt.where(QuotationRequest.status.in_(OPEN_STATUSES))
        elif params.status not in QUOTATION_REQUEST_STATUSES:
            raise ValidationFailedError(
                "Unknown status filter.", field_errors={"status": ["Unknown status"]}
            )
        else:
            stmt = stmt.where(QuotationRequest.status == params.status)
    if intent:
        stmt = stmt.where(QuotationRequest.intent == intent)
    if params.search:
        needle = f"%{params.search.strip()}%"
        stmt = stmt.where(
            or_(
                QuotationRequest.reference.ilike(needle),
                QuotationRequest.full_name.ilike(needle),
                QuotationRequest.organization.ilike(needle),
                QuotationRequest.email.ilike(needle),
                QuotationRequest.phone.ilike(needle),
                QuotationRequest.product_name.ilike(needle),
            )
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(QuotationRequest.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [_out(r) for r in rows],
        page=params.page,
        page_size=params.page_size,
        total=total,
    )


@router.get("/summary")
async def quotation_request_summary(
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(QuotationRequest.status, func.count()).group_by(QuotationRequest.status)
        )
    ).all()
    counts = {status: 0 for status in QUOTATION_REQUEST_STATUSES}
    for status, count in rows:
        counts[status] = count
    return ok(
        {
            "total": sum(counts.values()),
            "by_status": counts,
            "new_count": counts["new"],
            "open_count": sum(counts[s] for s in OPEN_STATUSES),
        }
    )


@router.get("/{request_id}")
async def get_quotation_request(
    request_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(_out(await _get_request(db, request_id)))


@router.patch("/{request_id}")
async def update_quotation_request(
    request_id: uuid.UUID,
    payload: QuotationRequestUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise ValidationFailedError("Nothing to update.")

    row = await _get_request(db, request_id, for_update=True)
    before = {"status": row.status, "internal_notes": row.internal_notes}

    if "internal_notes" in fields:
        notes = (fields["internal_notes"] or "").strip()
        row.internal_notes = notes or None
    if "status" in fields and fields["status"] is not None:
        row.status = fields["status"]
        # Stamp first pickup once; re-opening a request keeps the original date.
        if row.status != "new" and row.contacted_at is None:
            row.contacted_at = datetime.now(UTC)

    await db.flush()
    await write_audit(
        db,
        action="quotation_request.updated",
        entity_type="quotation_request",
        entity_id=row.id,
        old=before,
        new={"status": row.status, "internal_notes": row.internal_notes},
    )
    await db.commit()
    await db.refresh(row)
    return ok(_out(row))
