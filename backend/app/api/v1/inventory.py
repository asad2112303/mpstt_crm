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
    conditions = ["1=1"]
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
