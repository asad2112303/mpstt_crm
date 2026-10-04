"""Rate quotations — publish what things cost per unit.

Pick products, set the rate for each, print it. There is no quantity to enter
and nothing to total: the document answers "what do you charge?", and the
order that may follow is raised separately.

Issued complete rather than drafted: a rate list is short enough to get right
in one pass, and freezing it at creation means a reprint months later shows
the rates that were actually quoted.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.catalogue import ProductVariant
from app.models.organization import Organization
from app.models.rate_quotes import RateQuotation, RateQuotationItem
from app.services.audit import write_audit
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.money import money
from app.services.numbering import allocate_number
from app.services.pdf import freeze_context, render_html, render_pdf

router = APIRouter(prefix="/rate-quotations", tags=["rate-quotations"])


class RateLineIn(BaseModel):
    product_variant_id: uuid.UUID
    # The rate for one unit. Quantity is deliberately absent.
    unit_price: Decimal = Field(ge=0)
    description: str | None = Field(default=None, max_length=500)


class RateQuotationIn(BaseModel):
    organization_id: uuid.UUID | None = None
    customer_name: str | None = Field(default=None, max_length=200)
    contact_person: str | None = Field(default=None, max_length=150)
    contact_phone: str | None = Field(default=None, max_length=50)
    quote_date: date | None = None
    valid_until: date | None = None
    notes: str | None = None
    items: list[RateLineIn] = Field(min_length=1)


class RateItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    product_variant_id: uuid.UUID
    description_snapshot: str
    specification_snapshot: dict
    uom_code: str
    unit_price: Decimal
    sort_order: int


class RateQuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    quotation_number: str
    organization_id: uuid.UUID | None
    customer_name: str | None
    contact_person: str | None
    contact_phone: str | None
    quote_date: date
    valid_until: date | None
    status: str
    notes: str | None
    cancelled_reason: str | None
    created_at: datetime
    items: list[RateItemOut] = []


async def _get(db: AsyncSession, quote_id: uuid.UUID) -> RateQuotation:
    quote = (
        await db.execute(
            select(RateQuotation)
            .options(selectinload(RateQuotation.items))
            .where(RateQuotation.id == quote_id)
        )
    ).scalar_one_or_none()
    if quote is None:
        raise NotFoundError("Rate quotation not found.")
    return quote


def _out(quote: RateQuotation) -> dict:
    return RateQuotationOut.model_validate(quote).model_dump(mode="json")


async def _build_context(db: AsyncSession, quote: RateQuotation) -> dict:
    from app.api.v1.quotations import _company_dict

    company = await _company_dict(db)
    org = (
        await db.get(Organization, quote.organization_id)
        if quote.organization_id
        else None
    )
    name = quote.customer_name or (org.name if org else None)
    return {
        "company": company,
        "quote": {
            "number": quote.quotation_number,
            "date": quote.quote_date.isoformat(),
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "currency": company.get("default_currency", "PKR"),
            "notes": quote.notes,
        },
        "customer": {
            "name": name,
            "contact_person": quote.contact_person,
            "city": org.city if org else None,
            "phone": quote.contact_phone or (org.phone if org else None),
        },
        "items": [
            {
                "sn": item.sort_order + 1,
                "description": item.description_snapshot,
                "specification": item.specification_snapshot,
                "uom": item.uom_code,
                "unit_price": item.unit_price,
            }
            for item in quote.items
        ],
    }


@router.get("")
async def list_rate_quotations(
    params: ListParams = Depends(list_params),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(RateQuotation).options(selectinload(RateQuotation.items))
    if params.status:
        stmt = stmt.where(RateQuotation.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        stmt = stmt.where(
            or_(
                RateQuotation.quotation_number.ilike(needle),
                RateQuotation.customer_name.ilike(needle),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(RateQuotation.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return ok([_out(r) for r in rows], page=params.page,
              page_size=params.page_size, total=total)


@router.post("", status_code=201)
async def create_rate_quotation(
    payload: RateQuotationIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create and issue a rate list in one step."""
    key = require_idempotency_key(request)

    async def do_create() -> dict:
        org = None
        if payload.organization_id:
            org = await db.get(Organization, payload.organization_id)
            if org is None:
                raise NotFoundError("Customer not found.")

        quote = RateQuotation(
            quotation_number=await allocate_number(db, "RQ"),
            organization_id=org.id if org else None,
            customer_name=(payload.customer_name or "").strip() or None,
            contact_person=payload.contact_person,
            contact_phone=payload.contact_phone,
            quote_date=payload.quote_date or date.today(),
            valid_until=payload.valid_until,
            notes=payload.notes,
            created_by=uuid.UUID(user.id),
        )
        db.add(quote)
        await db.flush()

        for index, line in enumerate(payload.items):
            variant = (
                await db.execute(
                    select(ProductVariant)
                    .options(selectinload(ProductVariant.product))
                    .where(ProductVariant.id == line.product_variant_id)
                )
            ).scalar_one_or_none()
            if variant is None:
                raise ValidationFailedError(f"Line {index + 1}: product not found.")
            db.add(
                RateQuotationItem(
                    rate_quotation_id=quote.id,
                    product_id=variant.product_id,
                    product_variant_id=variant.id,
                    description_snapshot=(
                        line.description.strip()
                        if line.description
                        else f"{variant.product.name} — {variant.variant_name}"
                    ),
                    specification_snapshot=variant.attributes or {},
                    uom_code=variant.uom.code,
                    unit_price=money(line.unit_price),
                    sort_order=index,
                )
            )
        await db.flush()
        await db.refresh(quote, ["items"])

        context = freeze_context(await _build_context(db, quote))
        # Render now so a broken template fails before the number is burned.
        render_html("rate-quotation.html", context)
        quote.pdf_context = context
        await db.flush()

        await write_audit(
            db, action="rate_quotation.issued", entity_type="rate_quotation",
            entity_id=quote.id,
            new={"number": quote.quotation_number, "lines": len(payload.items)},
        )
        return _out(quote)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="rate_quotation.create", key=key,
        payload={"items": len(payload.items), "customer": payload.customer_name or ""},
        fn=do_create, status_code=201,
    )
    await db.commit()
    return ok(body)


@router.get("/{quote_id}")
async def get_rate_quotation(
    quote_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(_out(await _get(db, quote_id)))


@router.post("/{quote_id}/cancel")
async def cancel_rate_quotation(
    quote_id: uuid.UUID,
    payload: dict,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reason = (payload or {}).get("reason", "").strip()
    if not reason:
        raise ValidationFailedError("A reason is required.",
                                    field_errors={"reason": ["Required"]})
    quote = await _get(db, quote_id)
    if quote.status == "cancelled":
        raise ConflictError("This rate list is already cancelled.")
    quote.status = "cancelled"
    quote.cancelled_reason = reason
    quote.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="rate_quotation.cancelled", entity_type="rate_quotation",
                      entity_id=quote.id, reason=reason)
    await db.commit()
    return ok(_out(quote))


@router.get("/{quote_id}/pdf")
async def rate_quotation_pdf(
    quote_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    quote = await _get(db, quote_id)
    context = quote.pdf_context or freeze_context(await _build_context(db, quote))
    content = render_pdf("rate-quotation.html", context)
    return RawResponse(
        content=content, media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{quote.quotation_number}.pdf"',
            "Cache-Control": "no-store",
        },
    )
