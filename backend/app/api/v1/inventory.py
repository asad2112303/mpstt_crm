"""M6: inventory endpoints — warehouses, balances, movements, admin adjustments."""
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError
from app.core.security import CurrentUser, require_admin, require_user
from app.models.catalogue import Product, ProductVariant
from app.models.inventory import StockMovement, Warehouse
from app.services.audit import write_audit
from app.services.inventory import admin_adjust_stock

router = APIRouter(prefix="/inventory", tags=["inventory"])


class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    is_active: bool = True


class AdjustmentIn(BaseModel):
    warehouse_id: uuid.UUID
    product_variant_id: uuid.UUID
    quantity: Decimal  # signed; validated non-zero in the service
    reason: str = Field(min_length=3)
    reference: str | None = Field(default=None, max_length=80)
    movement_type: str = Field(default="adjustment", pattern="^(adjustment|opening|receipt_in)$")


@router.get("/warehouses")
async def list_warehouses(
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (await db.execute(select(Warehouse).order_by(Warehouse.created_at))).scalars().all()
    return ok([
        {"id": str(w.id), "code": w.code, "name": w.name, "address": w.address,
         "is_active": w.is_active}
        for w in rows
    ])


@router.post("/warehouses", status_code=201)
async def create_warehouse(
    payload: WarehouseIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    warehouse = Warehouse(**payload.model_dump())
    db.add(warehouse)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A warehouse with this code already exists.",
                            code="DUPLICATE_CODE") from exc
    await db.commit()
    return ok({"id": str(warehouse.id), "code": warehouse.code, "name": warehouse.name,
               "address": warehouse.address, "is_active": warehouse.is_active})


@router.patch("/warehouses/{warehouse_id}")
async def update_warehouse(
    warehouse_id: uuid.UUID,
    payload: WarehouseIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    warehouse = await db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError("Warehouse not found.")
    for field, value in payload.model_dump().items():
        setattr(warehouse, field, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A warehouse with this code already exists.",
                            code="DUPLICATE_CODE") from exc
    await db.commit()
    return ok({"id": str(warehouse.id), "code": warehouse.code, "name": warehouse.name,
               "address": warehouse.address, "is_active": warehouse.is_active})


@router.get("/balances")
async def stock_balances(
    warehouse_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None, max_length=120),
    low_stock_below: Decimal | None = Query(None, gt=0),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # A retired variant that still holds stock stays visible — you need to see
    # it to clear it. Once it is empty it drops off the list for good.
    conditions = ["(v.variant_is_active OR v.on_hand <> 0 OR v.reserved <> 0)"]
    params: dict = {}
    if warehouse_id:
        conditions.append("v.warehouse_id = :wh")
        params["wh"] = str(warehouse_id)
    if search:
        conditions.append(
            "(v.product_name ILIKE :needle OR v.variant_name ILIKE :needle OR v.sku ILIKE :needle)"
        )
        params["needle"] = f"%{search}%"
    if low_stock_below is not None:
        conditions.append("v.available < :low")
        params["low"] = low_stock_below
    rows = (
        await db.execute(
            text(
                "SELECT * FROM crm.v_stock_available v "
                f"WHERE {' AND '.join(conditions)} "
                "ORDER BY v.product_name, v.variant_name LIMIT 500"
            ),
            params,
        )
    ).mappings().all()
    return ok([dict(r) | {
        "warehouse_id": str(r["warehouse_id"]),
        "product_variant_id": str(r["product_variant_id"]),
        "on_hand": str(r["on_hand"]), "reserved": str(r["reserved"]),
        "available": str(r["available"]),
    } for r in rows])


@router.get("/movements")
async def stock_movements(
    product_variant_id: uuid.UUID | None = Query(None),
    warehouse_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(StockMovement, ProductVariant.variant_name, Product.name)
        .join(ProductVariant, StockMovement.product_variant_id == ProductVariant.id)
        .join(Product, ProductVariant.product_id == Product.id)
    )
    if product_variant_id:
        stmt = stmt.where(StockMovement.product_variant_id == product_variant_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(StockMovement.movement_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ok(
        [
            {
                "id": str(m.id),
                "warehouse_id": str(m.warehouse_id),
                "product_variant_id": str(m.product_variant_id),
                "product": f"{product_name} — {variant_name}",
                "quantity": str(m.quantity),
                "movement_type": m.movement_type,
                "reference_type": m.reference_type,
                "reference_id": m.reference_id,
                "notes": m.notes,
                "movement_at": m.movement_at.isoformat(),
            }
            for m, variant_name, product_name in rows
        ],
        page=page, page_size=page_size, total=total,
    )


@router.post("/adjustments", status_code=201)
async def create_adjustment(
    payload: AdjustmentIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if await db.get(Warehouse, payload.warehouse_id) is None:
        raise NotFoundError("Warehouse not found.")
    if await db.get(ProductVariant, payload.product_variant_id) is None:
        raise NotFoundError("Variant not found.")
    balance = await admin_adjust_stock(
        db,
        warehouse_id=payload.warehouse_id,
        product_variant_id=payload.product_variant_id,
        quantity=payload.quantity,
        reason=payload.reason,
        reference=payload.reference,
        user_id=admin.id,
        movement_type=payload.movement_type,
    )
    await db.commit()
    return ok({
        "warehouse_id": str(balance.warehouse_id),
        "product_variant_id": str(balance.product_variant_id),
        "on_hand": str(balance.on_hand),
        "reserved": str(balance.reserved),
    })


class ReceiptIn(BaseModel):
    """Stock coming in, with the cost that drives the weighted average."""

    warehouse_id: uuid.UUID | None = None
    product_variant_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    # Optional: a receipt with no cost still adds quantity, it just leaves the
    # average where it was and shows up as incomplete cost coverage.
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    movement_type: str = Field(default="receipt_in", pattern="^(receipt_in|opening)$")


@router.post("/receipts", status_code=201)
async def create_receipt(
    payload: ReceiptIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Book stock in and roll the weighted average cost forward."""
    from app.services.costing import receive_stock
    from app.services.inventory import get_default_warehouse

    warehouse = (
        await db.get(Warehouse, payload.warehouse_id)
        if payload.warehouse_id
        else await get_default_warehouse(db)
    )
    if warehouse is None:
        raise NotFoundError("Warehouse not found.")
    variant = await db.get(ProductVariant, payload.product_variant_id)
    if variant is None:
        raise NotFoundError("Variant not found.")
    product = await db.get(Product, variant.product_id)
    if not product.track_stock:
        raise ConflictError(
            f"'{product.name}' is not stock-tracked. Enable tracking before receiving stock.",
            code="PRODUCT_NOT_TRACKED",
        )

    balance = await receive_stock(
        db,
        warehouse_id=warehouse.id,
        product_variant_id=variant.id,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        user_id=user.id,
        movement_type=payload.movement_type,
        reference_type="manual",
        reference_id=payload.reference,
        notes=payload.notes,
    )
    await write_audit(
        db, action="stock.received", entity_type="stock_balance",
        entity_id=f"{warehouse.id}:{variant.id}",
        new={"quantity": str(payload.quantity), "unit_cost": str(payload.unit_cost or "")},
    )
    await db.commit()
    return ok({
        "warehouse_id": str(balance.warehouse_id),
        "product_variant_id": str(balance.product_variant_id),
        "on_hand": str(balance.on_hand),
        "avg_cost": str(balance.avg_cost) if balance.avg_cost is not None else None,
    })


class EnableTrackingIn(BaseModel):
    """Promote a Quick Bill product to stock-tracked."""

    warehouse_id: uuid.UUID | None = None
    opening_quantity: Decimal = Field(ge=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reorder_level: Decimal | None = Field(default=None, ge=0)


@router.post("/products/{product_id}/enable-tracking")
async def enable_tracking(
    product_id: uuid.UUID,
    payload: EnableTrackingIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start tracking stock for a product that was created while billing.

    Opening stock is what the user says is on the shelf now. Quantities already
    sold on Quick Bill invoices are deliberately not inferred as stock received.
    """
    from app.services.costing import receive_stock
    from app.services.inventory import get_default_warehouse

    product = await db.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    if product.track_stock:
        raise ConflictError("This product is already stock-tracked.", code="ALREADY_TRACKED")

    product.track_stock = True
    if payload.unit_cost is not None:
        product.default_purchase_cost = payload.unit_cost
    product.updated_by = uuid.UUID(user.id)

    variants = (
        await db.execute(select(ProductVariant).where(ProductVariant.product_id == product.id))
    ).scalars().all()
    if payload.reorder_level is not None:
        for variant in variants:
            variant.reorder_level = payload.reorder_level

    opened = []
    if payload.opening_quantity > 0:
        warehouse = (
            await db.get(Warehouse, payload.warehouse_id)
            if payload.warehouse_id
            else await get_default_warehouse(db)
        )
        if len(variants) != 1:
            raise ConflictError(
                "This product has several variants. Enter opening stock per variant "
                "under Inventory instead.",
                code="MULTIPLE_VARIANTS",
            )
        await receive_stock(
            db,
            warehouse_id=warehouse.id,
            product_variant_id=variants[0].id,
            quantity=payload.opening_quantity,
            unit_cost=payload.unit_cost,
            user_id=user.id,
            movement_type="opening",
            reference_type="enable_tracking",
            reference_id=str(product.id),
            notes="Opening stock on enabling tracking",
        )
        opened.append(str(variants[0].id))

    await write_audit(
        db, action="product.tracking_enabled", entity_type="product", entity_id=product.id,
        new={"opening_quantity": str(payload.opening_quantity),
             "unit_cost": str(payload.unit_cost or "")},
    )
    await db.commit()
    return ok({"product_id": str(product.id), "track_stock": True, "opened_variants": opened})


@router.get("/low-stock")
async def low_stock(
    warehouse_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tracked variants at or below their reorder level."""
    rows = (
        await db.execute(
            text(
                """
                SELECT v.id AS variant_id, p.id AS product_id, p.name AS product_name,
                       v.variant_name, v.reorder_level, u.code AS uom_code,
                       COALESCE(b.on_hand, 0) AS on_hand,
                       COALESCE(b.reserved, 0) AS reserved,
                       b.avg_cost, w.code AS warehouse_code, w.id AS warehouse_id
                FROM crm.product_variants v
                JOIN crm.products p ON p.id = v.product_id
                JOIN crm.units_of_measure u ON u.id = v.uom_id
                LEFT JOIN crm.stock_balances b ON b.product_variant_id = v.id
                     AND (CAST(:wh AS uuid) IS NULL OR b.warehouse_id = CAST(:wh AS uuid))
                LEFT JOIN crm.warehouses w ON w.id = b.warehouse_id
                WHERE p.track_stock AND p.is_active AND v.is_active
                  AND v.reorder_level IS NOT NULL
                  AND COALESCE(b.on_hand, 0) - COALESCE(b.reserved, 0) <= v.reorder_level
                ORDER BY (COALESCE(b.on_hand, 0) - COALESCE(b.reserved, 0)) - v.reorder_level
                LIMIT :limit
                """
            ),
            {"wh": str(warehouse_id) if warehouse_id else None, "limit": limit},
        )
    ).mappings().all()
    return ok([
        {
            "product_variant_id": str(r["variant_id"]),
            "product_id": str(r["product_id"]),
            "label": f"{r['product_name']} — {r['variant_name']}",
            "uom_code": r["uom_code"],
            "on_hand": str(r["on_hand"]),
            "available": str(r["on_hand"] - r["reserved"]),
            "reorder_level": str(r["reorder_level"]),
            "warehouse_code": r["warehouse_code"],
        }
        for r in rows
    ])
