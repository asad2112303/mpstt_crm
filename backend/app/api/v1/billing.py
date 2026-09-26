"""Direct billing: Quick Bill and Sell from Stock.

The point of this module is that a user can open the app and raise a bill
without setting up inventory first. A line can name a product that does not
exist yet — it is created in the one central catalogue as it is billed, with
stock tracking off, so the same product is reusable next time without ever
becoming a phantom stock balance.

Stock only moves for tracked products on ``stock`` lines, and only when the
invoice is finalized. See ``services/billing.py`` for why that cannot happen
twice.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.catalogue import Product, ProductCategory, ProductVariant, UnitOfMeasure
from app.models.inventory import Warehouse
from app.models.invoices import Invoice, InvoiceItem
from app.models.organization import CustomerProfile, Organization
from app.services.audit import write_audit
from app.services.billing import apply_totals, calculate_totals, commit_stock_and_cost
from app.services.costing import balances_for
from app.services.idempotency import require_idempotency_key, run_idempotent
from app.services.inventory import get_default_warehouse
from app.services.invoicing import build_pdf_context, get_walk_in_organization
from app.services.money import calculate_line, money
from app.services.numbering import allocate_number
from app.services.pdf import freeze_context, render_html

router = APIRouter(prefix="/billing", tags=["billing"])

QUICK_BILL_CATEGORY = "Other Supplies"


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------

class LineIn(BaseModel):
    """One invoice line.

    Either names an existing variant, or supplies ``new_product`` to create one
    on the fly. Quick Bill asks for the minimum: name, unit, quantity, price.
    """

    product_variant_id: uuid.UUID | None = None
    new_product: "QuickProductIn | None" = None
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    # Overrides the description that would come from the catalogue.
    description: str | None = Field(default=None, max_length=500)
    # Internal only; never rendered on the customer's invoice.
    unit_cost: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_source(self):
        if (self.product_variant_id is None) == (self.new_product is None):
            raise ValueError("Each line needs either product_variant_id or new_product.")
        return self


class QuickProductIn(BaseModel):
    """The least we can ask for and still have a reusable catalogue product."""

    name: str = Field(min_length=1, max_length=200)
    uom_code: str = Field(min_length=1, max_length=20)
    category_id: uuid.UUID | None = None
    # Optional descriptors; only shown when the category asks for them.
    colour: str | None = Field(default=None, max_length=60)
    size: str | None = Field(default=None, max_length=60)
    sale_price: Decimal | None = Field(default=None, ge=0)
    purchase_cost: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    # Off by default: a Quick Bill product must not invent a stock balance.
    track_stock: bool = False
    opening_quantity: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _opening_needs_tracking(self):
        if self.opening_quantity and not self.track_stock:
            raise ValueError("Opening stock requires track_stock to be enabled.")
        return self


LineIn.model_rebuild()


class InvoiceDraftIn(BaseModel):
    organization_id: uuid.UUID | None = None
    walk_in: bool = False
    walk_in_name: str | None = Field(default=None, max_length=200)
    warehouse_id: uuid.UUID | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    reference_number: str | None = Field(default=None, max_length=100)
    contact_person: str | None = Field(default=None, max_length=150)
    contact_phone: str | None = Field(default=None, max_length=50)
    billing_address: str | None = None
    delivery_address: str | None = None
    notes: str | None = None
    payment_terms_note: str | None = None
    overall_discount_type: str | None = None
    overall_discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    delivery_charge: Decimal = Field(default=Decimal("0"), ge=0)
    items: list[LineIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _customer_required(self):
        if not self.walk_in and self.organization_id is None:
            raise ValueError("Choose a customer, or mark the sale as walk-in.")
        return self


# --------------------------------------------------------------------------
# pickers
# --------------------------------------------------------------------------

@router.get("/products")
async def billing_products(
    search: str | None = Query(None, max_length=200),
    warehouse_id: uuid.UUID | None = Query(None),
    only_tracked: bool = Query(False),
    tracked: str = Query("all", pattern="^(all|tracked|untracked)$"),
    limit: int = Query(20, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Searchable picker: one row per sellable variant, with stock and price."""
    stmt = (
        select(ProductVariant)
        .join(Product, Product.id == ProductVariant.product_id)
        .options(selectinload(ProductVariant.product))
        .where(ProductVariant.is_active.is_(True), Product.is_active.is_(True))
    )
    if only_tracked or tracked == "tracked":
        stmt = stmt.where(Product.track_stock.is_(True))
    elif tracked == "untracked":
        stmt = stmt.where(Product.track_stock.is_(False))
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(needle),
                Product.sku.ilike(needle),
                ProductVariant.variant_name.ilike(needle),
                ProductVariant.variant_code.ilike(needle),
            )
        )
    variants = (
        (await db.execute(stmt.order_by(Product.name, ProductVariant.variant_name).limit(limit)))
        .scalars()
        .all()
    )

    warehouse = None
    if tracked != "untracked" and any(v.product.track_stock for v in variants):
        warehouse = (
            await db.get(Warehouse, warehouse_id)
            if warehouse_id
            else await get_default_warehouse(db)
        )
    balances = (
        await balances_for(db, warehouse.id, [v.id for v in variants]) if warehouse else {}
    )

    rows = []
    for v in variants:
        balance = balances.get(v.id)
        on_hand = balance.on_hand if balance else Decimal("0")
        reserved = balance.reserved if balance else Decimal("0")
        rows.append(
            {
                "product_variant_id": str(v.id),
                "product_id": str(v.product_id),
                "sku": v.product.sku,
                "variant_code": v.variant_code,
                "label": f"{v.product.name} — {v.variant_name}",
                "product_name": v.product.name,
                "variant_name": v.variant_name,
                "category": v.product.category.name if v.product.category else None,
                "attributes": v.attributes,
                "uom_code": v.uom.code if v.uom else None,
                "tax_rate": str(v.product.tax_rate),
                "track_stock": v.product.track_stock,
                "available": str(on_hand - reserved) if v.product.track_stock else None,
                "on_hand": str(on_hand) if v.product.track_stock else None,
                "suggested_price": str(
                    v.last_sale_price or v.product.default_sale_price or Decimal("0")
                ),
                "has_cost": bool(
                    (balance and balance.avg_cost is not None)
                    or v.standard_cost is not None
                    or v.product.default_purchase_cost is not None
                ),
                "avg_cost": str(balance.avg_cost) if balance and balance.avg_cost else None,
                "standard_cost": str(v.standard_cost) if v.standard_cost is not None else None,
                "default_purchase_cost": (
                    str(v.product.default_purchase_cost)
                    if v.product.default_purchase_cost is not None
                    else None
                ),
                "reorder_level": str(v.reorder_level) if v.reorder_level is not None else None,
                "low_stock": bool(
                    v.product.track_stock
                    and v.reorder_level is not None
                    and (on_hand - reserved) <= v.reorder_level
                ),
                "created_via": v.product.created_via,
            }
        )
    return ok(rows)


@router.get("/customers")
async def billing_customers(
    search: str | None = Query(None, max_length=200),
    limit: int = Query(15, ge=1, le=50),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Customers and prospects for the bill-to picker; system rows excluded."""
    stmt = select(Organization).where(
        Organization.is_active.is_(True), Organization.is_system.is_(False)
    )
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Organization.name.ilike(needle),
                Organization.org_code.ilike(needle),
                Organization.city.ilike(needle),
                Organization.phone.ilike(needle),
            )
        )
    rows = (
        (await db.execute(stmt.order_by(Organization.name).limit(limit))).scalars().all()
    )
    return ok(
        [
            {
                "id": str(o.id),
                "name": o.name,
                "org_code": o.org_code,
                "city": o.city,
                "phone": o.phone,
                "lifecycle_status": o.lifecycle_status,
            }
            for o in rows
        ]
    )


# --------------------------------------------------------------------------
# inline product creation
# --------------------------------------------------------------------------

async def _resolve_uom(db: AsyncSession, code: str) -> UnitOfMeasure:
    """Find the unit, or create it.

    Blocking a sale because someone typed a unit that is not in master data
    would defeat the point of billing without setup. The standard selling
    units are seeded by migration 0016; anything else the user types is added
    to the catalogue as they go. No conversion factor is ever inferred between
    units — a packet never silently becomes pieces.
    """
    cleaned = code.strip()
    uom = (
        await db.execute(
            select(UnitOfMeasure).where(func.lower(UnitOfMeasure.code) == cleaned.lower())
        )
    ).scalar_one_or_none()
    if uom is not None:
        return uom
    uom = UnitOfMeasure(
        code=cleaned.upper()[:20], name=cleaned.title()[:80], category="count", decimal_scale=0
    )
    db.add(uom)
    await db.flush()
    return uom


async def _quick_bill_category(db: AsyncSession) -> ProductCategory:
    category = (
        await db.execute(
            select(ProductCategory).where(ProductCategory.name == QUICK_BILL_CATEGORY)
        )
    ).scalar_one_or_none()
    if category is None:
        category = ProductCategory(
            name=QUICK_BILL_CATEGORY,
            description="Default home for products created while billing.",
            attribute_schema={"attributes": []},
        )
        db.add(category)
        await db.flush()
    return category


async def _next_quick_sku(db: AsyncSession) -> str:
    """SKUs must be unique; Quick Bill products get their own readable series."""
    count = (
        await db.execute(
            select(func.count()).select_from(Product).where(Product.created_via == "quick_bill")
        )
    ).scalar_one()
    candidate = f"QB-{count + 1:05d}"
    while (
        await db.execute(select(Product.id).where(Product.sku == candidate))
    ).scalar_one_or_none() is not None:
        count += 1
        candidate = f"QB-{count + 1:05d}"
    return candidate


async def create_quick_product(
    db: AsyncSession, payload: QuickProductIn, *, user_id: str
) -> ProductVariant:
    """Create a catalogue product + its variant from the billing screen."""
    uom = await _resolve_uom(db, payload.uom_code)
    category = (
        await db.get(ProductCategory, payload.category_id)
        if payload.category_id
        else await _quick_bill_category(db)
    )
    if category is None:
        raise NotFoundError("Category not found.")

    sku = await _next_quick_sku(db)
    product = Product(
        sku=sku,
        name=payload.name.strip(),
        category_id=category.id,
        base_uom_id=uom.id,
        tax_rate=payload.tax_rate,
        track_stock=payload.track_stock,
        default_sale_price=payload.sale_price,
        default_purchase_cost=payload.purchase_cost,
        created_via="quick_bill",
        created_by=uuid.UUID(user_id),
    )
    db.add(product)
    await db.flush()

    attributes = {}
    if payload.colour:
        attributes["colour"] = payload.colour.strip()
    if payload.size:
        attributes["size"] = payload.size.strip()
    # Colour and size are what make one variant different from another, so they
    # belong in the variant name too.
    suffix = " / ".join(v for v in (payload.colour, payload.size) if v)
    variant = ProductVariant(
        product_id=product.id,
        variant_code=f"{sku}-1",
        variant_name=f"{product.name}{f' — {suffix}' if suffix else ''}"[:200],
        uom_id=uom.id,
        attributes=attributes,
        standard_cost=payload.purchase_cost,
        last_sale_price=payload.sale_price,
        created_by=uuid.UUID(user_id),
    )
    db.add(variant)
    await db.flush()
    await db.refresh(variant, ["product", "uom"])

    await write_audit(
        db, action="product.quick_created", entity_type="product", entity_id=product.id,
        new={"sku": sku, "name": product.name, "track_stock": product.track_stock},
    )
    return variant


class QuickProductRequest(QuickProductIn):
    warehouse_id: uuid.UUID | None = None


@router.post("/quick-product", status_code=201)
async def quick_product(
    payload: QuickProductRequest,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a product without leaving the invoice."""
    variant = await create_quick_product(db, payload, user_id=user.id)
    if payload.track_stock and payload.opening_quantity:
        from app.services.costing import receive_stock

        warehouse = (
            await db.get(Warehouse, payload.warehouse_id)
            if payload.warehouse_id
            else await get_default_warehouse(db)
        )
        await receive_stock(
            db,
            warehouse_id=warehouse.id,
            product_variant_id=variant.id,
            quantity=payload.opening_quantity,
            unit_cost=payload.purchase_cost,
            user_id=user.id,
            movement_type="opening",
            reference_type="quick_product",
            reference_id=str(variant.id),
            notes="Opening stock entered while billing",
        )
    await db.commit()
    return ok(
        {
            "product_variant_id": str(variant.id),
            "product_id": str(variant.product_id),
            "sku": variant.product.sku,
            "label": f"{variant.product.name} — {variant.variant_name}",
            "uom_code": variant.uom.code,
            "tax_rate": str(variant.product.tax_rate),
            "track_stock": variant.product.track_stock,
            "suggested_price": str(variant.last_sale_price or Decimal("0")),
        }
    )


# --------------------------------------------------------------------------
# direct invoices
# --------------------------------------------------------------------------

async def _build_items(
    db: AsyncSession, invoice: Invoice, lines: list[LineIn], *, user_id: str
) -> list:
    """Turn payload lines into invoice items, creating products as needed."""
    amounts = []
    items = []
    for index, line in enumerate(lines):
        if line.new_product is not None:
            variant = await create_quick_product(db, line.new_product, user_id=user_id)
        else:
            variant = (
                await db.execute(
                    select(ProductVariant)
                    .options(selectinload(ProductVariant.product))
                    .where(ProductVariant.id == line.product_variant_id)
                )
            ).scalar_one_or_none()
            if variant is None:
                raise ValidationFailedError(f"Line {index + 1}: product not found.")
            if not variant.is_active or not variant.product.is_active:
                raise ValidationFailedError(
                    f"Line {index + 1}: '{variant.variant_name}' is retired and cannot be sold."
                )
        product = variant.product
        tax_rate = line.tax_rate if line.tax_rate is not None else product.tax_rate
        calc = calculate_line(line.quantity, line.unit_price, line.discount_percent, tax_rate)
        amounts.append(calc)

        item = InvoiceItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_variant_id=variant.id,
            description_snapshot=(
                line.description.strip()
                if line.description
                else f"{product.name} — {variant.variant_name}"
            ),
            specification_snapshot=variant.attributes or {},
            quantity=line.quantity,
            uom_code=variant.uom.code,
            unit_price=money(line.unit_price),
            discount_percent=line.discount_percent,
            tax_rate=tax_rate,
            line_net=calc.net,
            line_tax=calc.tax,
            line_total=calc.total,
            sort_order=index,
            # A tracked product sold here moves stock; a Quick Bill one never does.
            line_source="stock" if product.track_stock else "quick_bill",
        )
        if line.unit_cost is not None:
            # An explicit cost typed on the line wins over any catalogue cost,
            # and finalize will not overwrite it.
            item.unit_cost = line.unit_cost
            item.cost_source = "manual"
        db.add(item)
        items.append(item)
    await db.flush()
    return amounts


async def _apply_header(
    db: AsyncSession, invoice: Invoice, payload: InvoiceDraftIn, *, user_id: str
) -> None:
    if payload.walk_in:
        walk_in = await get_walk_in_organization(db)
        invoice.organization_id = walk_in.id
        invoice.is_walk_in = True
        invoice.walk_in_name = (payload.walk_in_name or "").strip() or None
        terms = 0
    else:
        org = await db.get(Organization, payload.organization_id)
        if org is None:
            raise NotFoundError("Customer not found.")
        if org.is_system:
            raise ValidationFailedError(
                "That is a reserved record. Mark the sale as walk-in instead."
            )
        invoice.organization_id = org.id
        invoice.is_walk_in = False
        invoice.walk_in_name = None
        profile = await db.get(CustomerProfile, org.id)
        terms = profile.payment_terms_days if profile else 30

    invoice.payment_terms_days = (
        payload.payment_terms_days if payload.payment_terms_days is not None else terms
    )
    invoice.invoice_date = payload.invoice_date
    invoice.due_date = payload.due_date
    invoice.reference_number = payload.reference_number
    invoice.contact_person = payload.contact_person
    invoice.contact_phone = payload.contact_phone
    invoice.billing_address = payload.billing_address
    invoice.delivery_address = payload.delivery_address
    invoice.notes = payload.notes
    invoice.payment_terms_note = payload.payment_terms_note
    invoice.overall_discount_type = payload.overall_discount_type
    invoice.overall_discount_value = payload.overall_discount_value
    invoice.updated_by = uuid.UUID(user_id)

    warehouse = (
        await db.get(Warehouse, payload.warehouse_id) if payload.warehouse_id else None
    )
    if warehouse is None:
        # Only needed once a tracked line is present; resolved lazily so a pure
        # Quick Bill works with no warehouse configured at all.
        warehouse = await _optional_default_warehouse(db)
    invoice.warehouse_id = warehouse.id if warehouse else None


async def _optional_default_warehouse(db: AsyncSession) -> Warehouse | None:
    return (
        await db.execute(
            select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.created_at)
        )
    ).scalars().first()


async def _draft_out(db: AsyncSession, invoice: Invoice) -> dict:
    from app.api.v1.invoices import invoice_out

    return await invoice_out(db, invoice)


@router.post("/invoices", status_code=201)
async def create_direct_invoice(
    payload: InvoiceDraftIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save a direct invoice as a draft. Drafts never touch stock."""
    invoice = Invoice(
        organization_id=uuid.uuid4(),  # replaced by _apply_header below
        status="draft",
        is_direct=True,
        created_by=uuid.UUID(user.id),
    )
    await _apply_header(db, invoice, payload, user_id=user.id)
    db.add(invoice)
    await db.flush()

    amounts = await _build_items(db, invoice, payload.items, user_id=user.id)
    apply_totals(
        invoice,
        calculate_totals(
            amounts,
            overall_discount_type=payload.overall_discount_type,
            overall_discount_value=payload.overall_discount_value,
            delivery_charge=payload.delivery_charge,
        ),
    )
    await db.flush()
    await write_audit(
        db, action="invoice.draft_created", entity_type="invoice", entity_id=invoice.id,
        new={"grand_total": str(invoice.grand_total), "lines": len(payload.items),
             "walk_in": invoice.is_walk_in},
    )
    await db.commit()
    await db.refresh(invoice, ["items"])
    return ok(await _draft_out(db, invoice))


@router.put("/invoices/{invoice_id}")
async def update_direct_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceDraftIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace a draft's header and lines wholesale."""
    invoice = (
        await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.items))
            .where(Invoice.id == invoice_id)
            .with_for_update(of=Invoice)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found.")
    if invoice.status != "draft":
        raise ConflictError(
            "Only a draft invoice can be edited. Cancel it and raise a new one.",
            code="INVOICE_NOT_DRAFT",
        )
    if not invoice.is_direct:
        raise ConflictError(
            "This invoice came from a sales order. Edit the order instead.",
            code="INVOICE_FROM_ORDER",
        )

    for item in list(invoice.items):
        await db.delete(item)
    await db.flush()

    await _apply_header(db, invoice, payload, user_id=user.id)
    amounts = await _build_items(db, invoice, payload.items, user_id=user.id)
    apply_totals(
        invoice,
        calculate_totals(
            amounts,
            overall_discount_type=payload.overall_discount_type,
            overall_discount_value=payload.overall_discount_value,
            delivery_charge=payload.delivery_charge,
        ),
    )
    await db.flush()
    await db.commit()
    await db.refresh(invoice, ["items"])
    return ok(await _draft_out(db, invoice))


class FinalizeIn(BaseModel):
    """Optional payment taken at the counter as the bill is finalized."""

    amount_paid: Decimal | None = Field(default=None, ge=0)
    payment_method: str = Field(default="cash", max_length=20)
    payment_reference: str | None = Field(default=None, max_length=150)


async def _record_payment(
    db: AsyncSession, invoice: Invoice, payload: FinalizeIn, *, user_id: str
) -> Decimal:
    """Create a payment and allocate it to this invoice."""
    from app.models.payments import Payment
    from app.services.payments import allocate_payment

    amount = money(payload.amount_paid)
    if amount <= 0:
        return Decimal("0")
    if amount > invoice.grand_total:
        raise ValidationFailedError(
            "The amount paid is more than the invoice total.",
            field_errors={"amount_paid": ["Exceeds the invoice total"]},
        )
    payment = Payment(
        payment_number=await allocate_number(db, "PAY"),
        organization_id=invoice.organization_id,
        payment_date=invoice.invoice_date or date.today(),
        amount=amount,
        method=payload.payment_method,
        reference=payload.payment_reference,
        created_by=uuid.UUID(user_id),
    )
    db.add(payment)
    await db.flush()
    await allocate_payment(
        db, payment_id=payment.id, user_id=user_id,
        allocations=[{"invoice_id": invoice.id, "amount": amount}],
    )
    return amount


@router.post("/invoices/{invoice_id}/finalize")
async def finalize_invoice(
    invoice_id: uuid.UUID,
    payload: FinalizeIn,
    request: Request,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue the invoice, deduct tracked stock, and freeze every line's cost.

    Idempotent: the same Idempotency-Key replays the stored response, and
    ``stock_committed_at`` independently guarantees stock moves only once even
    if the key is lost.
    """
    key = require_idempotency_key(request)

    async def do_finalize() -> dict:
        invoice = (
            await db.execute(
                select(Invoice)
                .options(selectinload(Invoice.items))
                .where(Invoice.id == invoice_id)
                .with_for_update(of=Invoice)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Invoice not found.")
        if invoice.status == "cancelled":
            raise ConflictError("This invoice is cancelled.", code="INVOICE_CANCELLED")
        if invoice.status != "draft":
            raise ConflictError(
                "This invoice has already been finalized.", code="INVOICE_NOT_DRAFT"
            )
        if not invoice.items:
            raise ValidationFailedError("The invoice has no items.")

        paid = money(payload.amount_paid or 0)
        if invoice.is_walk_in and paid < invoice.grand_total:
            raise ValidationFailedError(
                "A walk-in sale must be paid in full. Choose a saved customer to "
                "leave a balance outstanding.",
                code="WALK_IN_REQUIRES_FULL_PAYMENT",
            )

        today = date.today()
        invoice.invoice_date = invoice.invoice_date or today
        if invoice.due_date is None:
            invoice.due_date = invoice.invoice_date + timedelta(
                days=invoice.payment_terms_days
            )
        if invoice.invoice_number is None:
            invoice.invoice_number = await allocate_number(db, "INV")

        # Stock and cost before the document is frozen: if stock is short the
        # invoice stays a draft with no number burned.
        stock_result = await commit_stock_and_cost(db, invoice, user_id=user.id)

        invoice.status = "issued"
        invoice.issued_at = datetime.now(UTC)
        invoice.updated_by = uuid.UUID(user.id)

        context = freeze_context(await build_pdf_context(db, invoice))
        # Render now so a broken template fails before the invoice is issued.
        render_html("invoice.html", context)
        invoice.pdf_context = context
        await db.flush()

        if payload.amount_paid:
            await _record_payment(db, invoice, payload, user_id=user.id)

        await write_audit(
            db, action="invoice.finalized", entity_type="invoice", entity_id=invoice.id,
            new={
                "number": invoice.invoice_number,
                "grand_total": str(invoice.grand_total),
                "stock_moved": stock_result["stock_moved"],
                "amount_paid": str(paid),
            },
        )
        await db.refresh(invoice, ["items"])
        body = await _draft_out(db, invoice)
        body["stock"] = stock_result
        return body

    body, _status, _replayed = await run_idempotent(
        db, user_id=user.id, action="invoice.finalize", key=key,
        payload={"invoice_id": str(invoice_id), "amount_paid": str(payload.amount_paid or 0)},
        fn=do_finalize,
    )
    await db.commit()
    return ok(body)


# --------------------------------------------------------------------------
# stepped picker: product first, then its options
# --------------------------------------------------------------------------

@router.get("/catalogue")
async def billing_catalogue(
    search: str | None = Query(None, max_length=200),
    warehouse_id: uuid.UUID | None = Query(None),
    only_tracked: bool = Query(False),
    limit: int = Query(12, ge=1, le=40),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Products with their variants, for picking one step at a time.

    The billing screen asks for the product first, then narrows by the
    category's own attributes in the order the category defines them — colour,
    then size, and so on. Returning the whole product in one response keeps
    each step instant instead of a round trip per choice.
    """
    stmt = (
        select(Product)
        .options(selectinload(Product.variants).selectinload(ProductVariant.uom))
        .where(Product.is_active.is_(True))
    )
    if only_tracked:
        stmt = stmt.where(Product.track_stock.is_(True))
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(needle), Product.sku.ilike(needle)))
    products = (
        (await db.execute(stmt.order_by(Product.name).limit(limit))).scalars().unique().all()
    )

    all_variant_ids = [v.id for p in products for v in p.variants if v.is_active]
    warehouse = None
    if any(p.track_stock for p in products):
        warehouse = (
            await db.get(Warehouse, warehouse_id)
            if warehouse_id
            else await _optional_default_warehouse(db)
        )
    balances = (
        await balances_for(db, warehouse.id, all_variant_ids) if warehouse else {}
    )

    rows = []
    for product in products:
        variants = [v for v in product.variants if v.is_active]
        if not variants:
            continue
        schema = (product.category.attribute_schema or {}).get("attributes", [])
        # Only ask about attributes the variants actually differ on; an
        # attribute every variant shares is not a choice.
        steps = []
        for attr in schema:
            key = attr.get("key")
            values = {
                str(v.attributes.get(key))
                for v in variants
                if v.attributes.get(key) not in (None, "")
            }
            if len(values) > 1:
                steps.append({
                    "key": key,
                    "label": attr.get("label") or key.replace("_", " ").title(),
                    "unit": attr.get("unit"),
                })

        rows.append({
            "product_id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "category": product.category.name if product.category else None,
            "track_stock": product.track_stock,
            "tax_rate": str(product.tax_rate),
            "steps": steps,
            "variants": [
                {
                    "product_variant_id": str(v.id),
                    "variant_name": v.variant_name,
                    "attributes": {k: str(val) for k, val in (v.attributes or {}).items()},
                    "uom_code": v.uom.code if v.uom else None,
                    "track_stock": product.track_stock,
                    "available": (
                        str(
                            (balances[v.id].on_hand - balances[v.id].reserved)
                            if v.id in balances
                            else Decimal("0")
                        )
                        if product.track_stock
                        else None
                    ),
                    "suggested_price": str(
                        v.last_sale_price or product.default_sale_price or Decimal("0")
                    ),
                    "has_cost": bool(
                        (v.id in balances and balances[v.id].avg_cost is not None)
                        or v.standard_cost is not None
                        or product.default_purchase_cost is not None
                    ),
                }
                for v in variants
            ],
        })
    return ok(rows)
