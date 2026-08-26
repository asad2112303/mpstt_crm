"""M7: invoice endpoints — create from order, issue (freeze + PDF), cancel.

The invoice answers WHAT IS OWED. Delivery/POD (M8) answers what physically
moved. The UI must never imply an invoice proves delivery.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.invoices import Invoice, InvoiceItem
from app.models.orders import SalesOrder
from app.models.organization import CustomerProfile, Organization
from app.services.audit import write_audit
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.numbering import allocate_number
from app.services.pdf import render_pdf

router = APIRouter(prefix="/invoices", tags=["invoices"])


class InvoiceFromOrderIn(BaseModel):
    sales_order_id: uuid.UUID
    # Custom due date needs explicit intent; otherwise terms drive it.
    custom_due_date: date | None = None
    notes: str | None = None


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sales_order_item_id: uuid.UUID | None
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


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    invoice_number: str | None
    organization_id: uuid.UUID
    sales_order_id: uuid.UUID | None
    invoice_date: date | None
    due_date: date | None
    payment_terms_days: int
    status: str
    origin: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    notes: str | None
    cancelled_reason: str | None
    issued_at: datetime | None
    pdf_document_id: uuid.UUID | None
    created_at: datetime
    items: list[InvoiceItemOut] = []


def derived_status(invoice: Invoice, allocated: Decimal = Decimal("0")) -> str:
    if invoice.status != "issued":
        return invoice.status
    outstanding = invoice.grand_total - allocated
    if outstanding <= 0:
        return "paid"
    if allocated > 0:
        return "partially_paid"
    if invoice.due_date and invoice.due_date < date.today():
        return "overdue"
    return "issued"


async def allocated_amount(db: AsyncSession, invoice_id: uuid.UUID) -> Decimal:
    """Sum of valid allocations. Zero until M9 creates the allocations table."""
    from sqlalchemy import text as sql_text

    exists = (
        await db.execute(sql_text("SELECT to_regclass('crm.payment_allocations') IS NOT NULL"))
    ).scalar()
    if not exists:
        return Decimal("0")
    value = (
        await db.execute(
            sql_text(
                "SELECT COALESCE(SUM(pa.allocated_amount), 0) FROM crm.payment_allocations pa "
                "JOIN crm.payments p ON p.id = pa.payment_id "
                "WHERE pa.invoice_id = :inv AND p.status <> 'reversed'"
            ),
            {"inv": str(invoice_id)},
        )
    ).scalar_one()
    return Decimal(value)


async def invoice_out(db: AsyncSession, invoice: Invoice) -> dict:
    allocated = await allocated_amount(db, invoice.id)
    data = InvoiceOut.model_validate(invoice).model_dump(mode="json")
    data["allocated"] = str(allocated)
    data["outstanding"] = str(
        invoice.grand_total - allocated if invoice.status == "issued" else Decimal("0")
    )
    data["derived_status"] = derived_status(invoice, allocated)
    return data


async def _get_invoice(db: AsyncSession, invoice_id: uuid.UUID, *, for_update: bool = False) -> Invoice:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Invoice)
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found.")
    return invoice


@router.get("")
async def list_invoices(
    params: ListParams = Depends(list_params),
    organization_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Invoice).options(selectinload(Invoice.items))
    if organization_id:
        stmt = stmt.where(Invoice.organization_id == organization_id)
    if params.status:
        stmt = stmt.where(Invoice.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        org_ids = select(Organization.id).where(Organization.name.ilike(needle))
        stmt = stmt.where(
            Invoice.invoice_number.ilike(needle) | Invoice.organization_id.in_(org_ids)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Invoice.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [await invoice_out(db, i) for i in rows],
        page=params.page, page_size=params.page_size, total=total,
    )


@router.post("/from-order", status_code=201)
async def create_from_order(
    payload: InvoiceFromOrderIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    order = (
        await db.execute(
            select(SalesOrder)
            .options(selectinload(SalesOrder.items))
            .where(SalesOrder.id == payload.sales_order_id)
            .with_for_update(of=SalesOrder)
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    if order.status in ("draft", "cancelled"):
        raise ConflictError(
            "Only a confirmed order can be invoiced. Confirm the order first.",
            code="ORDER_NOT_CONFIRMED",
        )
    existing = (
        await db.execute(
            select(Invoice).where(
                Invoice.sales_order_id == order.id, Invoice.status != "cancelled"
            )
        )
    ).scalars().first()
    if existing:
        raise ConflictError(
            "An invoice already exists for this order.", code="INVOICE_EXISTS"
        )

    profile = await db.get(CustomerProfile, order.organization_id)
    terms = profile.payment_terms_days if profile else 30

    invoice = Invoice(
        organization_id=order.organization_id,
        sales_order_id=order.id,
        payment_terms_days=terms,
        due_date=payload.custom_due_date,
        status="draft",
        subtotal=order.subtotal,
        discount_total=order.discount_total,
        tax_total=order.tax_total,
        grand_total=order.grand_total,
        notes=payload.notes,
        created_by=uuid.UUID(user.id),
        items=[
            InvoiceItem(
                sales_order_item_id=item.id,
                product_id=item.product_id,
                product_variant_id=item.product_variant_id,
                description_snapshot=item.description_snapshot,
                specification_snapshot=item.specification_snapshot,
                quantity=item.quantity,
                uom_code=item.uom_code,
                unit_price=item.unit_price,
                discount_percent=item.discount_percent,
                tax_rate=item.tax_rate,
                line_net=item.line_net,
                line_tax=item.line_tax,
                line_total=item.line_total,
                sort_order=item.sort_order,
            )
            for item in order.items
        ],
    )
    db.add(invoice)
    await db.flush()
    await write_audit(db, action="invoice.created", entity_type="invoice",
                      entity_id=invoice.id, new={"order": order.order_number})
    await db.commit()
    return ok(await invoice_out(db, await _get_invoice(db, invoice.id)))


@router.get("/{invoice_id}")
async def get_invoice(
    invoice_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(await invoice_out(db, await _get_invoice(db, invoice_id)))


@router.post("/{invoice_id}/issue")
async def issue_invoice(
    invoice_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    key = require_idempotency_key(request)

    async def do_issue() -> dict:
        invoice = await _get_invoice(db, invoice_id, for_update=True)
        if invoice.status != "draft":
            raise ConflictError("Only a draft invoice can be issued.", code="INVOICE_NOT_DRAFT")
        if not invoice.items:
            raise ValidationFailedError("The invoice has no items.")

        today = date.today()
        invoice.invoice_date = today
        if invoice.due_date is None:
            invoice.due_date = today + timedelta(days=invoice.payment_terms_days)
        invoice.invoice_number = await allocate_number(db, "INV")
        invoice.status = "issued"
        invoice.issued_at = datetime.now(UTC)
        invoice.updated_by = uuid.UUID(user.id)

        # Frozen PDF
        from app.api.v1.documents import store_document
        from app.api.v1.quotations import _company_dict

        company = await _company_dict(db)
        org = await db.get(Organization, invoice.organization_id)
        context = {
            "company": company,
            "invoice": {
                "number": invoice.invoice_number,
                "date": invoice.invoice_date.isoformat(),
                "due_date": invoice.due_date.isoformat(),
                "terms_days": invoice.payment_terms_days,
                "subtotal": invoice.subtotal,
                "discount_total": invoice.discount_total,
                "tax_total": invoice.tax_total,
                "grand_total": invoice.grand_total,
                "currency": company.get("default_currency", "PKR"),
                "notes": invoice.notes,
            },
            "customer": {
                "name": org.name, "code": org.org_code, "city": org.city,
                "phone": org.phone, "ntn": org.ntn,
            },
            "order_number": None,
            "items": [
                {
                    "sn": i.sort_order + 1,
                    "description": i.description_snapshot,
                    "specification": i.specification_snapshot,
                    "quantity": i.quantity,
                    "uom": i.uom_code,
                    "unit_price": i.unit_price,
                    "line_total": i.line_total,
                }
                for i in invoice.items
            ],
        }
        if invoice.sales_order_id:
            order = await db.get(SalesOrder, invoice.sales_order_id)
            context["order_number"] = order.order_number if order else None

        pdf_bytes = render_pdf("invoice.html", context)
        doc = await store_document(
            db, settings,
            content=pdf_bytes,
            filename=f"{invoice.invoice_number}.pdf",
            claimed_mime="application/pdf",
            entity_type="invoice",
            entity_id=str(invoice.id),
            document_type="invoice_pdf",
            organization_id=invoice.organization_id,
            uploaded_by=uuid.UUID(user.id),
        )
        invoice.pdf_document_id = doc.id
        await db.flush()
        await write_audit(db, action="invoice.issued", entity_type="invoice",
                          entity_id=invoice.id,
                          new={"number": invoice.invoice_number,
                               "due_date": str(invoice.due_date),
                               "grand_total": str(invoice.grand_total)})
        return await invoice_out(db, invoice)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="invoice.issue", key=key,
        payload={"invoice_id": str(invoice_id)}, fn=do_issue,
    )
    await db.commit()
    return ok(body)


@router.post("/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: uuid.UUID,
    payload: dict,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    reason = (payload or {}).get("reason", "").strip()
    if not reason:
        raise ValidationFailedError("A reason is required to cancel an invoice.",
                                    field_errors={"reason": ["Required"]})
    invoice = await _get_invoice(db, invoice_id, for_update=True)
    if invoice.status == "cancelled":
        raise ConflictError("The invoice is already cancelled.")
    allocated = await allocated_amount(db, invoice.id)
    if allocated > 0:
        raise ConflictError(
            "This invoice has payments allocated. Reverse the allocations first.",
            code="INVOICE_HAS_PAYMENTS",
        )
    old = invoice.status
    invoice.status = "cancelled"
    invoice.cancelled_reason = reason
    invoice.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="invoice.cancelled", entity_type="invoice",
                      entity_id=invoice.id, old={"status": old}, reason=reason)
    await db.commit()
    return ok(await invoice_out(db, invoice))


@router.get("/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    invoice = await _get_invoice(db, invoice_id)
    if not invoice.pdf_document_id:
        raise ConflictError("The invoice has not been issued yet.", code="INVOICE_NOT_ISSUED")
    from app.models.documents import Document
    from app.services.storage import get_storage

    doc = await db.get(Document, invoice.pdf_document_id)
    content = await get_storage(settings).get(doc.bucket, doc.storage_path)
    return RawResponse(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.original_filename}"',
                 "Cache-Control": "no-store"},
    )
