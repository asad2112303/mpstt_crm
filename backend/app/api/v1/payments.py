"""M9: payment, allocation, receipt, and receivables endpoints."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_admin_mfa, require_user
from app.models.invoices import Invoice
from app.models.organization import Organization
from app.models.payments import Payment, Receipt
from app.services.audit import write_audit
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.numbering import allocate_number
from app.services.payments import allocate_payment, allocated_total, reverse_payment
from app.services.pdf import freeze_context, render_html, render_pdf

router = APIRouter(tags=["payments"])


class PaymentIn(BaseModel):
    organization_id: uuid.UUID
    payment_date: date
    amount: Decimal = Field(gt=0)
    method: str = Field(pattern="^(cash|bank_transfer|cheque|online|other)$")
    reference: str | None = Field(default=None, max_length=150)
    proof_document_id: uuid.UUID | None = None
    notes: str | None = None


class AllocationLineIn(BaseModel):
    invoice_id: uuid.UUID
    amount: Decimal = Field(gt=0)


class AllocateIn(BaseModel):
    allocations: list[AllocationLineIn] = Field(min_length=1)


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    invoice_id: uuid.UUID
    allocated_amount: Decimal
    created_at: datetime


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    receipt_number: str
    issued_at: datetime
    pdf_document_id: uuid.UUID | None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    payment_number: str
    organization_id: uuid.UUID
    payment_date: date
    amount: Decimal
    method: str
    reference: str | None
    proof_document_id: uuid.UUID | None
    status: str
    notes: str | None
    reversal_reason: str | None
    reversed_at: datetime | None
    created_at: datetime
    allocations: list[AllocationOut] = []
    receipt: ReceiptOut | None = None


def payment_out(p: Payment) -> dict:
    data = PaymentOut.model_validate(p).model_dump(mode="json")
    data["unallocated"] = str(p.amount - allocated_total(p))
    return data


async def _get_payment(db: AsyncSession, payment_id: uuid.UUID) -> Payment:
    p = (
        await db.execute(
            select(Payment)
            .options(selectinload(Payment.allocations), selectinload(Payment.receipt))
            .where(Payment.id == payment_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if p is None:
        raise NotFoundError("Payment not found.")
    return p


# ---------- payments ----------

@router.get("/payments")
async def list_payments(
    params: ListParams = Depends(list_params),
    organization_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Payment).options(
        selectinload(Payment.allocations), selectinload(Payment.receipt)
    )
    if organization_id:
        stmt = stmt.where(Payment.organization_id == organization_id)
    if params.status:
        stmt = stmt.where(Payment.status == params.status)
    if params.search:
        needle = f"%{params.search.strip()}%"
        org_ids = select(Organization.id).where(Organization.name.ilike(needle))
        stmt = stmt.where(
            Payment.payment_number.ilike(needle)
            | Payment.reference.ilike(needle)
            | Payment.organization_id.in_(org_ids)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Payment.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok([payment_out(p) for p in rows], page=params.page, page_size=params.page_size, total=total)


@router.post("/payments", status_code=201)
async def record_payment(
    payload: PaymentIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await db.get(Organization, payload.organization_id)
    if org is None:
        raise ValidationFailedError("Organization not found.")
    payment = Payment(
        payment_number=await allocate_number(db, "PAY"),
        **payload.model_dump(),
        created_by=uuid.UUID(user.id),
    )
    db.add(payment)
    await db.flush()
    await write_audit(db, action="payment.recorded", entity_type="payment",
                      entity_id=payment.id,
                      new={"number": payment.payment_number, "amount": str(payment.amount)})
    await db.commit()
    return ok(payment_out(await _get_payment(db, payment.id)))


@router.get("/payments/{payment_id}")
async def get_payment(
    payment_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return ok(payment_out(await _get_payment(db, payment_id)))


@router.post("/payments/{payment_id}/allocate")
async def allocate(
    payment_id: uuid.UUID,
    payload: AllocateIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    key = require_idempotency_key(request)

    async def do_allocate() -> dict:
        payment = await allocate_payment(
            db, payment_id=payment_id, user_id=user.id,
            allocations=[line.model_dump() for line in payload.allocations],
        )
        return payment_out(payment)

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="payment.allocate", key=key,
        payload={"payment_id": str(payment_id), "allocations": payload.model_dump(mode="json")},
        fn=do_allocate,
    )
    await db.commit()
    return ok(body)


@router.post("/payments/{payment_id}/reverse")
async def reverse(
    payment_id: uuid.UUID,
    payload: dict,
    admin: CurrentUser = Depends(require_admin_mfa),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin + MFA only. The payment is never deleted — it is neutralized."""
    reason = (payload or {}).get("reason", "").strip()
    if not reason:
        raise ValidationFailedError("A reason is required to reverse a payment.",
                                    field_errors={"reason": ["Required"]})
    payment = await reverse_payment(db, payment_id=payment_id, user_id=admin.id, reason=reason)
    await db.commit()
    return ok(payment_out(payment))


# ---------- receipts ----------

@router.post("/payments/{payment_id}/receipt", status_code=201)
async def create_receipt(
    payment_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    payment = await _get_payment(db, payment_id)
    if payment.status == "reversed":
        raise ConflictError("A reversed payment cannot produce a receipt.")
    if payment.receipt is not None:
        return ok(payment_out(payment))

    org = await db.get(Organization, payment.organization_id)
    from app.api.v1.quotations import _company_dict

    company = await _company_dict(db)

    invoice_numbers = []
    for allocation in payment.allocations:
        invoice = await db.get(Invoice, allocation.invoice_id)
        if invoice:
            invoice_numbers.append(
                {"number": invoice.invoice_number, "amount": allocation.allocated_amount}
            )

    receipt = Receipt(
        receipt_number=await allocate_number(db, "RCP"),
        payment_id=payment.id,
        created_by=uuid.UUID(user.id),
    )
    db.add(receipt)
    await db.flush()
    await db.refresh(receipt)

    context = {
        "company": company,
        "receipt": {
            "number": receipt.receipt_number,
            "date": receipt.issued_at.date().isoformat(),
            "currency": company.get("default_currency", "PKR"),
        },
        "payment": {
            "number": payment.payment_number,
            "date": payment.payment_date.isoformat(),
            "amount": payment.amount,
            "method": payment.method.replace("_", " ").title(),
            "reference": payment.reference,
        },
        "customer": {"name": org.name, "city": org.city},
        "allocations": invoice_numbers,
    }
    # Frozen inputs; the PDF renders on demand rather than being uploaded.
    context = freeze_context(context)
    render_html("receipt.html", context)  # fail here, not at download
    receipt.pdf_context = context
    await db.flush()
    await write_audit(db, action="receipt.issued", entity_type="receipt",
                      entity_id=receipt.id, new={"number": receipt.receipt_number})
    await db.commit()
    return ok(payment_out(await _get_payment(db, payment_id)))


@router.get("/payments/{payment_id}/receipt/pdf")
async def receipt_pdf(
    payment_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    payment = await _get_payment(db, payment_id)
    receipt = payment.receipt
    if receipt is None or (receipt.pdf_context is None and receipt.pdf_document_id is None):
        raise NotFoundError("No receipt has been issued for this payment.")
    if receipt.pdf_context:
        content = render_pdf("receipt.html", receipt.pdf_context)
        filename = f"{receipt.receipt_number}.pdf"
    else:
        # Receipts issued before snapshots: still served from storage.
        from app.models.documents import Document
        from app.services.storage import get_storage

        doc = await db.get(Document, receipt.pdf_document_id)
        content = await get_storage(settings).get(doc.bucket, doc.storage_path)
        filename = doc.original_filename
    return RawResponse(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"',
                 "Cache-Control": "no-store"},
    )


# ---------- receivables / statements ----------

@router.get("/receivables")
async def receivables(
    bucket: str | None = Query(None, pattern="^(current|0-30|31-60|61-90|90\\+)$"),
    organization_id: uuid.UUID | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conditions, params = ["1=1"], {}
    if bucket:
        conditions.append("bucket = :bucket")
        params["bucket"] = bucket
    if organization_id:
        conditions.append("organization_id = :org")
        params["org"] = str(organization_id)
    rows = (
        await db.execute(
            text(
                "SELECT * FROM crm.v_receivables_aging "
                f"WHERE {' AND '.join(conditions)} "
                "ORDER BY days_overdue DESC, outstanding DESC LIMIT 500"
            ),
            params,
        )
    ).mappings().all()
    data = [
        {
            **dict(r),
            "invoice_id": str(r["invoice_id"]),
            "organization_id": str(r["organization_id"]),
            "invoice_date": r["invoice_date"].isoformat() if r["invoice_date"] else None,
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "grand_total": str(r["grand_total"]),
            "allocated": str(r["allocated"]),
            "outstanding": str(r["outstanding"]),
        }
        for r in rows
    ]
    totals = {
        "outstanding_total": str(sum(Decimal(d["outstanding"]) for d in data) or Decimal("0")),
        "count": len(data),
    }
    return ok({"rows": data, "totals": totals})


@router.get("/customers/{organization_id}/statement")
async def customer_statement(
    organization_id: uuid.UUID,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org = await db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")

    events: list[dict] = []
    invoices = (
        await db.execute(
            select(Invoice).where(
                Invoice.organization_id == organization_id, Invoice.status == "issued"
            )
        )
    ).scalars().all()
    for invoice in invoices:
        events.append({
            "date": invoice.invoice_date.isoformat(),
            "kind": "invoice",
            "reference": invoice.invoice_number,
            "debit": str(invoice.grand_total),
            "credit": "0",
        })
    payments = (
        await db.execute(
            select(Payment).where(
                Payment.organization_id == organization_id, Payment.status != "reversed"
            )
        )
    ).scalars().all()
    for payment in payments:
        events.append({
            "date": payment.payment_date.isoformat(),
            "kind": "payment",
            "reference": payment.payment_number,
            "debit": "0",
            "credit": str(payment.amount),
        })

    events.sort(key=lambda e: (e["date"], e["kind"]))
    if date_from:
        events = [e for e in events if e["date"] >= date_from.isoformat()]
    if date_to:
        events = [e for e in events if e["date"] <= date_to.isoformat()]

    balance = Decimal("0")
    for event in events:
        balance += Decimal(event["debit"]) - Decimal(event["credit"])
        event["balance"] = str(balance)

    return ok({
        "organization": {"id": str(org.id), "name": org.name},
        "rows": events,
        "closing_balance": str(balance),
    })
