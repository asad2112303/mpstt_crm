"""M9 payment rules: allocation transaction, status derivation, reversal.

Lock order (frozen): payment row first, then invoices sorted by UUID.
Over-allocation is impossible: unallocated payment balance and each invoice's
outstanding are validated inside the same locked transaction.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models.invoices import Invoice
from app.models.payments import Payment, PaymentAllocation
from app.services.audit import write_audit


def allocated_total(payment: Payment) -> Decimal:
    return sum((a.allocated_amount for a in payment.allocations), Decimal("0"))


def derive_payment_status(payment: Payment) -> str:
    if payment.status == "reversed":
        return "reversed"
    total = allocated_total(payment)
    if total >= payment.amount:
        return "allocated"
    if total > 0:
        return "partially_allocated"
    return "recorded"


async def get_payment_locked(session: AsyncSession, payment_id: uuid.UUID) -> Payment:
    payment = (
        await session.execute(
            select(Payment)
            .options(selectinload(Payment.allocations), selectinload(Payment.receipt))
            .where(Payment.id == payment_id)
            .with_for_update(of=Payment)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment not found.")
    return payment


async def invoice_outstanding(session: AsyncSession, invoice: Invoice) -> Decimal:
    from app.api.v1.invoices import allocated_amount

    return invoice.grand_total - await allocated_amount(session, invoice.id)


async def allocate_payment(
    session: AsyncSession, *, payment_id: uuid.UUID, user_id: str,
    allocations: list[dict],
) -> Payment:
    if not allocations:
        raise ValidationFailedError("Provide at least one allocation line.")

    payment = await get_payment_locked(session, payment_id)
    if payment.status == "reversed":
        raise ConflictError("A reversed payment cannot be allocated.", code="PAYMENT_REVERSED")

    requested = {}
    for line in allocations:
        invoice_id = uuid.UUID(str(line["invoice_id"]))
        amount = Decimal(str(line["amount"]))
        if amount <= 0:
            raise ValidationFailedError("Allocation amounts must be positive.")
        requested[invoice_id] = requested.get(invoice_id, Decimal("0")) + amount

    unallocated = payment.amount - allocated_total(payment)
    total_requested = sum(requested.values(), Decimal("0"))
    if total_requested > unallocated:
        raise ConflictError(
            f"Allocation exceeds the unallocated payment balance ({unallocated}).",
            code="OVER_ALLOCATION",
        )

    # Lock invoices in sorted UUID order (deadlock-safe).
    invoices: dict[uuid.UUID, Invoice] = {}
    for invoice_id in sorted(requested):
        invoice = (
            await session.execute(
                select(Invoice)
                .options(selectinload(Invoice.items))
                .where(Invoice.id == invoice_id)
                .with_for_update(of=Invoice)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if invoice is None:
            raise ValidationFailedError(f"Invoice {invoice_id} not found.")
        if invoice.status != "issued":
            raise ConflictError(
                "Payments can only be allocated to issued invoices.",
                code="INVOICE_NOT_ISSUED",
            )
        if invoice.organization_id != payment.organization_id:
            raise ConflictError(
                "The invoice belongs to a different organization than the payment.",
                code="ORGANIZATION_MISMATCH",
            )
        outstanding = await invoice_outstanding(session, invoice)
        if requested[invoice_id] > outstanding:
            raise ConflictError(
                f"Allocation to {invoice.invoice_number} exceeds its outstanding "
                f"balance ({outstanding}).",
                code="OVER_ALLOCATION",
            )
        invoices[invoice_id] = invoice

    existing = {a.invoice_id: a for a in payment.allocations}
    for invoice_id, amount in requested.items():
        if invoice_id in existing:
            existing[invoice_id].allocated_amount += amount
        else:
            session.add(
                PaymentAllocation(
                    payment_id=payment.id,
                    invoice_id=invoice_id,
                    allocated_amount=amount,
                    created_by=uuid.UUID(user_id),
                )
            )
    await session.flush()
    await session.refresh(payment, ["allocations"])
    payment.status = derive_payment_status(payment)
    await session.flush()
    await write_audit(
        session, action="payment.allocated", entity_type="payment", entity_id=payment.id,
        new={
            "payment_number": payment.payment_number,
            "allocations": {str(k): str(v) for k, v in requested.items()},
            "status": payment.status,
        },
    )
    return payment


async def reverse_payment(
    session: AsyncSession, *, payment_id: uuid.UUID, user_id: str, reason: str,
) -> Payment:
    payment = await get_payment_locked(session, payment_id)
    if payment.status == "reversed":
        raise ConflictError("The payment is already reversed.")
    old_status = payment.status
    payment.status = "reversed"
    payment.reversal_reason = reason
    payment.reversed_at = datetime.now(UTC)
    payment.reversed_by = uuid.UUID(user_id)
    # Allocations are retained for history; every balance view excludes
    # reversed payments, so invoice outstandings recalculate automatically.
    await session.flush()
    await write_audit(
        session, action="payment.reversed", entity_type="payment", entity_id=payment.id,
        old={"status": old_status},
        new={"status": "reversed",
             "allocations_neutralized": [str(a.invoice_id) for a in payment.allocations]},
        reason=reason,
    )
    return payment
