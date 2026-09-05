"""M5: quotation endpoints — draft, send (freeze + PDF), revise, accept,
reject, convert-to-order."""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.organization import Organization, ProspectProfile
from app.models.quotes import Quotation
from app.schemas.customers import OrderOut
from app.services.audit import write_audit
from app.services.conversion import (
    ConversionInput,
    OrderItemInput,
    build_order_items,
    convert_prospect_to_customer_order,
)
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.money import sum_lines
from app.services.numbering import allocate_number
from app.services.pdf import freeze_context, render_html, render_pdf
from app.services.prospects import advance_stage
from app.services.quotations import (
    apply_totals,
    build_quote_items,
    effective_status,
    ensure_editable,
    pdf_context,
)

router = APIRouter(prefix="/quotations", tags=["quotations"])


class QuoteItemIn(BaseModel):
    product_variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    description: str | None = Field(default=None, max_length=500)


class QuoteDraftIn(BaseModel):
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    valid_until: date | None = None
    terms: str | None = None
    notes: str | None = None
    items: list[QuoteItemIn] = Field(default_factory=list)


class QuoteUpdateIn(BaseModel):
    branch_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    valid_until: date | None = None
    terms: str | None = None
    notes: str | None = None
    items: list[QuoteItemIn] | None = None


class QuoteItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    product_id: uuid.UUID
    product_variant_id: uuid.UUID
    description_snapshot: str
    specification_snapshot: dict
    quantity: Decimal
    uom_code: str
    unit_price: Decimal
    discount_percent: Decimal
    tax_rate: Decimal
    line_net: Decimal
    line_tax: Decimal
    line_total: Decimal
    sort_order: int


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    quotation_number: str
    revision_no: int
    parent_quotation_id: uuid.UUID | None
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    quote_date: date
    valid_until: date | None
    status: str
    terms: str | None
    notes: str | None
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    pdf_document_id: uuid.UUID | None
    sent_at: datetime | None
    accepted_at: datetime | None
    rejected_reason: str | None
    converted_order_id: uuid.UUID | None
    created_at: datetime
    items: list[QuoteItemOut] = []


def quote_out(quote: Quotation) -> dict:
    data = QuoteOut.model_validate(quote).model_dump(mode="json")
    data["effective_status"] = effective_status(quote)
    return data


async def _get_quote(db: AsyncSession, quotation_id: uuid.UUID, *, for_update: bool = False) -> Quotation:
    stmt = (
        select(Quotation)
        .options(selectinload(Quotation.items))
        .where(Quotation.id == quotation_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Quotation)
    quote = (await db.execute(stmt)).scalar_one_or_none()
    if quote is None:
        raise NotFoundError("Quotation not found.")
    return quote


async def _company_dict(db: AsyncSession) -> dict:
    from app.api.v1.settings import get_company_settings

    s = await get_company_settings(db)
    return {
        "company_name": s.company_name, "legal_name": s.legal_name, "phone": s.phone,
        "email": s.email, "website": s.website, "ntn": s.ntn, "strn": s.strn,
        "address": s.address, "city": s.city, "bank_details": s.bank_details,
        "default_currency": s.default_currency, "document_footer": s.document_footer,
        "quotation_terms": s.quotation_terms,
    }


# ---------- list / create / read / update ----------

@router.get("")
async def list_quotations(
    params: ListParams = Depends(list_params),
    organization_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Quotation).options(selectinload(Quotation.items))
    if organization_id:
        stmt = stmt.where(Quotation.organization_id == organization_id)
    if params.status:
        stmt = stmt.where(Quotation.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        org_ids = select(Organization.id).where(Organization.name.ilike(needle))
        stmt = stmt.where(
            or_(Quotation.quotation_number.ilike(needle), Quotation.organization_id.in_(org_ids))
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Quotation.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok([quote_out(q) for q in rows], page=params.page, page_size=params.page_size, total=total)


@router.post("", status_code=201)
async def create_quotation(
    payload: QuoteDraftIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await db.get(Organization, payload.organization_id)
    if org is None or not org.is_active:
        raise ValidationFailedError("Organization not found or inactive.",
                                    field_errors={"organization_id": ["Invalid"]})

    number = await allocate_number(db, "QT")
    quote = Quotation(
        quotation_number=number,
        organization_id=payload.organization_id,
        branch_id=payload.branch_id,
        contact_id=payload.contact_id,
        valid_until=payload.valid_until,
        terms=payload.terms,
        notes=payload.notes,
        created_by=uuid.UUID(user.id),
    )
    if payload.items:
        items, amounts = await build_quote_items(db, [i.model_dump() for i in payload.items])
        quote.items = items
        apply_totals(quote, amounts)
    db.add(quote)
    await db.flush()
    await write_audit(db, action="quotation.created", entity_type="quotation",
                      entity_id=quote.id, new={"number": number})
    await db.commit()
    return ok(quote_out(await _get_quote(db, quote.id)))


@router.get("/{quotation_id}")
async def get_quotation(
    quotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(quote_out(await _get_quote(db, quotation_id)))


@router.get("/{quotation_id}/revisions")
async def quotation_revisions(
    quotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    quote = await _get_quote(db, quotation_id)
    rows = (
        (
            await db.execute(
                select(Quotation)
                .options(selectinload(Quotation.items))
                .where(Quotation.quotation_number == quote.quotation_number)
                .order_by(Quotation.revision_no)
            )
        )
        .scalars()
        .all()
    )
    return ok([quote_out(q) for q in rows])


@router.put("/{quotation_id}")
async def update_quotation(
    quotation_id: uuid.UUID,
    payload: QuoteUpdateIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    quote = await _get_quote(db, quotation_id, for_update=True)
    ensure_editable(quote)

    for field in ("branch_id", "contact_id", "valid_until", "terms", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(quote, field, value)
    if payload.items is not None:
        items, amounts = await build_quote_items(db, [i.model_dump() for i in payload.items])
        quote.items.clear()
        await db.flush()
        quote.items.extend(items)
        apply_totals(quote, amounts)
    quote.updated_by = uuid.UUID(user.id)
    await db.flush()
    await db.commit()
    return ok(quote_out(await _get_quote(db, quotation_id)))


# ---------- transitions ----------

@router.post("/{quotation_id}/send")
async def send_quotation(
    quotation_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Freeze the quotation: totals, snapshots, and the branded PDF."""
    key = require_idempotency_key(request)

    async def do_send() -> dict:
        quote = await _get_quote(db, quotation_id, for_update=True)
        if quote.status != "draft":
            raise ConflictError("Only a draft quotation can be sent.", code="QUOTE_NOT_DRAFT")
        if not quote.items:
            raise ValidationFailedError("Add at least one item before sending.")

        company = await _company_dict(db)
        if not quote.terms and company.get("quotation_terms"):
            quote.terms = company["quotation_terms"]

        quote.status = "sent"
        quote.sent_at = datetime.now(UTC)
        quote.updated_by = uuid.UUID(user.id)

        # The previous revision (if any) is now superseded.
        if quote.parent_quotation_id:
            parent = await db.get(Quotation, quote.parent_quotation_id)
            if parent and parent.status in ("sent", "draft"):
                parent.status = "superseded"

        # Freeze the exact inputs the PDF is rendered from. The file itself is
        # produced on demand, so sending never depends on object storage.
        frozen = freeze_context(await pdf_context(db, quote, company))
        render_html("quotation.html", frozen)  # fail here, not at download
        quote.pdf_context = frozen

        # Prospect stage moves forward automatically.
        profile = (
            await db.execute(
                select(ProspectProfile).where(ProspectProfile.organization_id == quote.organization_id)
            )
        ).scalar_one_or_none()
        if profile is not None:
            advance_stage(profile, "quotation_sent")
            profile.last_activity_at = datetime.now(UTC)

        await db.flush()
        await write_audit(db, action="quotation.sent", entity_type="quotation",
                          entity_id=quote.id,
                          new={"number": quote.quotation_number, "revision": quote.revision_no,
                               "grand_total": str(quote.grand_total)})
        return quote_out(quote)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="quotation.send", key=key,
        payload={"quotation_id": str(quotation_id)}, fn=do_send,
    )
    await db.commit()
    return ok(body)


@router.post("/{quotation_id}/revise", status_code=201)
async def revise_quotation(
    quotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    quote = await _get_quote(db, quotation_id, for_update=True)
    if quote.status not in ("sent", "rejected"):
        raise ConflictError(
            "Only a sent or rejected quotation can be revised.", code="QUOTE_NOT_REVISABLE"
        )
    existing_draft = (
        await db.execute(
            select(Quotation).where(
                Quotation.quotation_number == quote.quotation_number,
                Quotation.status == "draft",
            )
        )
    ).scalar_one_or_none()
    if existing_draft:
        raise ConflictError("A draft revision already exists for this quotation.",
                            code="REVISION_EXISTS")

    max_rev = (
        await db.execute(
            select(func.max(Quotation.revision_no)).where(
                Quotation.quotation_number == quote.quotation_number
            )
        )
    ).scalar_one()

    revision = Quotation(
        quotation_number=quote.quotation_number,
        revision_no=max_rev + 1,
        parent_quotation_id=quote.id,
        organization_id=quote.organization_id,
        branch_id=quote.branch_id,
        contact_id=quote.contact_id,
        valid_until=quote.valid_until,
        terms=quote.terms,
        notes=quote.notes,
        created_by=uuid.UUID(user.id),
    )
    items, amounts = await build_quote_items(
        db,
        [
            {
                "product_variant_id": i.product_variant_id,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "discount_percent": i.discount_percent,
                "description": i.description_snapshot,
            }
            for i in quote.items
        ],
    )
    revision.items = items
    apply_totals(revision, amounts)
    db.add(revision)
    await db.flush()
    await write_audit(db, action="quotation.revised", entity_type="quotation",
                      entity_id=revision.id,
                      new={"number": quote.quotation_number, "revision": revision.revision_no})
    await db.commit()
    return ok(quote_out(await _get_quote(db, revision.id)))


@router.post("/{quotation_id}/accept")
async def accept_quotation(
    quotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    quote = await _get_quote(db, quotation_id, for_update=True)
    status = effective_status(quote)
    if status == "expired":
        raise ConflictError("This quotation has expired. Create a revision with new validity.",
                            code="QUOTE_EXPIRED")
    if status != "sent":
        raise ConflictError("Only a sent quotation can be accepted.", code="QUOTE_NOT_SENT")
    quote.status = "accepted"
    quote.accepted_at = datetime.now(UTC)
    quote.updated_by = uuid.UUID(user.id)

    profile = (
        await db.execute(
            select(ProspectProfile).where(ProspectProfile.organization_id == quote.organization_id)
        )
    ).scalar_one_or_none()
    if profile is not None:
        advance_stage(profile, "negotiation")

    await db.flush()
    await write_audit(db, action="quotation.accepted", entity_type="quotation",
                      entity_id=quote.id, new={"number": quote.quotation_number})
    await db.commit()
    return ok(quote_out(quote))


@router.post("/{quotation_id}/reject")
async def reject_quotation(
    quotation_id: uuid.UUID,
    payload: dict,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reason = (payload or {}).get("reason", "").strip()
    if not reason:
        raise ValidationFailedError("A reason is required to reject a quotation.",
                                    field_errors={"reason": ["Required"]})
    quote = await _get_quote(db, quotation_id, for_update=True)
    if effective_status(quote) not in ("sent", "expired"):
        raise ConflictError("Only a sent quotation can be rejected.", code="QUOTE_NOT_SENT")
    quote.status = "rejected"
    quote.rejected_reason = reason
    quote.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="quotation.rejected", entity_type="quotation",
                      entity_id=quote.id, reason=reason)
    await db.commit()
    return ok(quote_out(quote))


@router.post("/{quotation_id}/convert-to-order", status_code=201)
async def convert_quotation_to_order(
    quotation_id: uuid.UUID,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accepted quote → order. Converts the organization too if still a prospect."""
    key = require_idempotency_key(request)

    async def do_convert() -> dict:
        quote = await _get_quote(db, quotation_id, for_update=True)
        if quote.status != "accepted":
            raise ConflictError("Only an accepted quotation can be converted to an order.",
                                code="QUOTE_NOT_ACCEPTED")

        item_inputs = [
            OrderItemInput(
                product_variant_id=i.product_variant_id,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount_percent=i.discount_percent,
            )
            for i in quote.items
        ]

        org = await db.get(Organization, quote.organization_id)
        if org.lifecycle_status == "prospect":
            _, order = await convert_prospect_to_customer_order(
                db, organization_id=quote.organization_id, user_id=user.id,
                data=ConversionInput(
                    items=item_inputs,
                    branch_id=quote.branch_id,
                    is_direct_po=False,
                    source_quotation_id=quote.id,
                ),
            )
        else:
            from app.models.orders import SalesOrder

            order_items, amounts = await build_order_items(db, item_inputs)
            totals = sum_lines(amounts)
            order = SalesOrder(
                order_number=await allocate_number(db, "ORD"),
                organization_id=quote.organization_id,
                branch_id=quote.branch_id,
                source_quotation_id=quote.id,
                is_direct_po=False,
                status="draft",
                subtotal=totals.subtotal,
                discount_total=totals.discount_total,
                tax_total=totals.tax_total,
                grand_total=totals.grand_total,
                created_by=uuid.UUID(user.id),
                items=order_items,
            )
            db.add(order)
            await db.flush()
            await write_audit(db, action="order.created", entity_type="sales_order",
                              entity_id=order.id,
                              new={"order_number": order.order_number,
                                   "from_quotation": quote.quotation_number})

        quote.status = "converted"
        quote.converted_order_id = order.id
        await db.flush()
        return {"quotation": quote_out(quote),
                "order": OrderOut.model_validate(order).model_dump(mode="json")}

    body, status_code, _replayed = await run_idempotent(
        db, user_id=user.id, action="quotation.convert", key=key,
        payload={"quotation_id": str(quotation_id)}, fn=do_convert, status_code=201,
    )
    await db.commit()
    response.status_code = status_code
    return ok(body)


@router.get("/{quotation_id}/pdf")
async def quotation_pdf(
    quotation_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Sent+: streams the frozen stored PDF. Draft: renders a live preview."""
    quote = await _get_quote(db, quotation_id)
    if quote.pdf_context:
        content = render_pdf("quotation.html", quote.pdf_context)
        filename = f"{quote.quotation_number}-rev{quote.revision_no}.pdf"
    elif quote.pdf_document_id:
        # Quotations sent before snapshots: still served from storage.
        from app.models.documents import Document
        from app.services.storage import get_storage

        doc = await db.get(Document, quote.pdf_document_id)
        content = await get_storage(settings).get(doc.bucket, doc.storage_path)
        filename = doc.original_filename
    else:
        company = await _company_dict(db)
        content = render_pdf("quotation.html", await pdf_context(db, quote, company))
        filename = f"{quote.quotation_number}-preview.pdf"
    return RawResponse(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"',
                 "Cache-Control": "no-store"},
    )
