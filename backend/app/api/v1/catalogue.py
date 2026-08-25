"""Catalogue endpoints: categories, brands, UOMs, products, variants, search.

Master-structure objects (categories, brands, UOMs) are Admin-only.
Products/variants can be managed by both roles per the V1 role matrix.
Nothing is hard-deleted: referenced records deactivate.
"""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import ListParams, list_params
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_admin, require_user
from app.models.catalogue import Brand, Product, ProductCategory, ProductVariant, UnitOfMeasure
from app.schemas.catalogue import (
    BrandIn,
    BrandOut,
    CategoryIn,
    CategoryOut,
    ProductIn,
    ProductListItem,
    ProductOut,
    ProductUpdate,
    SearchHit,
    UomIn,
    UomOut,
    VariantIn,
    VariantOut,
    VariantUpdate,
)
from app.services.attribute_schema import (
    CATEGORY_TEMPLATES,
    validate_attributes,
    validate_schema_definition,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

DEFAULT_UOMS = [
    {"code": "PCS", "name": "Pieces", "category": "count", "decimal_scale": 0},
    {"code": "PACK", "name": "Pack", "category": "count", "decimal_scale": 0},
    {"code": "CTN", "name": "Carton", "category": "count", "decimal_scale": 0},
    {"code": "ROLL", "name": "Roll", "category": "count", "decimal_scale": 0},
    {"code": "KG", "name": "Kilogram", "category": "weight", "decimal_scale": 3},
    {"code": "LTR", "name": "Litre", "category": "volume", "decimal_scale": 3},
]


# ---------- categories ----------

@router.get("/categories")
async def list_categories(
    include_inactive: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(ProductCategory).order_by(ProductCategory.name)
    if not include_inactive:
        stmt = stmt.where(ProductCategory.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return ok([CategoryOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/categories", status_code=201)
async def create_category(
    payload: CategoryIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    validate_schema_definition(payload.attribute_schema)
    category = ProductCategory(**payload.model_dump())
    db.add(category)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A category with this name already exists.", code="DUPLICATE_NAME") from exc
    await write_audit(db, action="category.created", entity_type="product_category",
                      entity_id=category.id, new=payload.model_dump())
    await db.commit()
    return ok(CategoryOut.model_validate(category).model_dump(mode="json"))


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    category = await db.get(ProductCategory, category_id)
    if category is None:
        raise NotFoundError("Category not found.")
    validate_schema_definition(payload.attribute_schema)
    old = {"name": category.name, "is_active": category.is_active}
    for field, value in payload.model_dump().items():
        setattr(category, field, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A category with this name already exists.", code="DUPLICATE_NAME") from exc
    await write_audit(db, action="category.updated", entity_type="product_category",
                      entity_id=category.id, old=old, new=payload.model_dump())
    await db.commit()
    return ok(CategoryOut.model_validate(category).model_dump(mode="json"))


@router.post("/categories/apply-templates")
async def apply_templates(
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Seed the editable starting templates (categories + default UOMs)."""
    existing_names = {
        n for (n,) in (await db.execute(select(ProductCategory.name))).all()
    }
    created = []
    for template in CATEGORY_TEMPLATES:
        if template["name"] not in existing_names:
            db.add(ProductCategory(**template))
            created.append(template["name"])

    existing_uoms = {c for (c,) in (await db.execute(select(UnitOfMeasure.code))).all()}
    for uom in DEFAULT_UOMS:
        if uom["code"] not in existing_uoms:
            db.add(UnitOfMeasure(**uom))
    await db.flush()
    if created:
        await write_audit(db, action="category.templates_applied", entity_type="product_category",
                          new={"created": created})
    await db.commit()
    return ok({"created_categories": created})


# ---------- brands ----------

@router.get("/brands")
async def list_brands(
    include_inactive: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Brand).order_by(Brand.name)
    if not include_inactive:
        stmt = stmt.where(Brand.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return ok([BrandOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/brands", status_code=201)
async def create_brand(
    payload: BrandIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    brand = Brand(**payload.model_dump())
    db.add(brand)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A brand with this name already exists.", code="DUPLICATE_NAME") from exc
    await db.commit()
    return ok(BrandOut.model_validate(brand).model_dump(mode="json"))


@router.patch("/brands/{brand_id}")
async def update_brand(
    brand_id: uuid.UUID,
    payload: BrandIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    brand = await db.get(Brand, brand_id)
    if brand is None:
        raise NotFoundError("Brand not found.")
    for field, value in payload.model_dump().items():
        setattr(brand, field, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A brand with this name already exists.", code="DUPLICATE_NAME") from exc
    await db.commit()
    return ok(BrandOut.model_validate(brand).model_dump(mode="json"))


# ---------- units of measure ----------

@router.get("/uoms")
async def list_uoms(
    include_inactive: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(UnitOfMeasure).order_by(UnitOfMeasure.code)
    if not include_inactive:
        stmt = stmt.where(UnitOfMeasure.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return ok([UomOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/uoms", status_code=201)
async def create_uom(
    payload: UomIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uom = UnitOfMeasure(**payload.model_dump())
    db.add(uom)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A UOM with this code already exists.", code="DUPLICATE_CODE") from exc
    await db.commit()
    return ok(UomOut.model_validate(uom).model_dump(mode="json"))


@router.patch("/uoms/{uom_id}")
async def update_uom(
    uom_id: uuid.UUID,
    payload: UomIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uom = await db.get(UnitOfMeasure, uom_id)
    if uom is None:
        raise NotFoundError("UOM not found.")
    for field, value in payload.model_dump().items():
        setattr(uom, field, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A UOM with this code already exists.", code="DUPLICATE_CODE") from exc
    await db.commit()
    return ok(UomOut.model_validate(uom).model_dump(mode="json"))


# ---------- products ----------

async def _get_product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = (
        await db.execute(
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.id == product_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("Product not found.")
    return product


@router.get("/products")
async def list_products(
    params: ListParams = Depends(list_params),
    category_id: uuid.UUID | None = Query(None),
    include_inactive: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    variant_count = (
        select(func.count(ProductVariant.id))
        .where(ProductVariant.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    stmt = (
        select(
            Product,
            ProductCategory.name.label("category_name"),
            Brand.name.label("brand_name"),
            UnitOfMeasure.code.label("base_uom_code"),
            variant_count.label("variant_count"),
        )
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(Brand, Product.brand_id == Brand.id)
        .join(UnitOfMeasure, Product.base_uom_id == UnitOfMeasure.id)
    )
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if params.search:
        needle = f"%{params.search.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(needle), Product.sku.ilike(needle)))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Product.name).offset(params.offset).limit(params.page_size)
        )
    ).all()
    items = [
        ProductListItem(
            id=p.id, sku=p.sku, name=p.name, is_active=p.is_active, tax_rate=p.tax_rate,
            category_name=category_name, brand_name=brand_name,
            base_uom_code=base_uom_code, variant_count=count,
        ).model_dump(mode="json")
        for p, category_name, brand_name, base_uom_code, count in rows
    ]
    return ok(items, page=params.page, page_size=params.page_size, total=total)


@router.post("/products", status_code=201)
async def create_product(
    payload: ProductIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    category = await db.get(ProductCategory, payload.category_id)
    if category is None or not category.is_active:
        raise ValidationFailedError("Category not found or inactive.",
                                    field_errors={"category_id": ["Invalid category"]})
    if await db.get(UnitOfMeasure, payload.base_uom_id) is None:
        raise ValidationFailedError("Base UOM not found.", field_errors={"base_uom_id": ["Invalid UOM"]})

    product = Product(**payload.model_dump(), created_by=uuid.UUID(user.id))
    db.add(product)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A product with this SKU already exists.", code="DUPLICATE_SKU") from exc
    await write_audit(db, action="product.created", entity_type="product",
                      entity_id=product.id, new={"sku": product.sku, "name": product.name})
    await db.commit()
    loaded = await _get_product(db, product.id)
    return ok(ProductOut.model_validate(loaded).model_dump(mode="json"))


@router.get("/products/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await _get_product(db, product_id)
    return ok(ProductOut.model_validate(product).model_dump(mode="json"))


@router.patch("/products/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await _get_product(db, product_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")
    old = {k: getattr(product, k) for k in changes}
    for field, value in changes.items():
        setattr(product, field, value)
    product.updated_by = uuid.UUID(user.id)
    await db.flush()
    await write_audit(db, action="product.updated", entity_type="product",
                      entity_id=product.id, old=old, new=changes)
    await db.commit()
    return ok(ProductOut.model_validate(product).model_dump(mode="json"))


# ---------- variants ----------

@router.post("/products/{product_id}/variants", status_code=201)
async def create_variant(
    product_id: uuid.UUID,
    payload: VariantIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await _get_product(db, product_id)
    validate_attributes(product.category.attribute_schema, payload.attributes)
    variant = ProductVariant(
        product_id=product.id,
        variant_code=payload.variant_code,
        variant_name=payload.variant_name,
        uom_id=payload.uom_id or product.base_uom_id,
        attributes=payload.attributes,
        is_active=payload.is_active,
        created_by=uuid.UUID(user.id),
    )
    db.add(variant)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "Variant code or name already exists for this product.", code="DUPLICATE_VARIANT"
        ) from exc
    await write_audit(db, action="variant.created", entity_type="product_variant",
                      entity_id=variant.id, new={"code": variant.variant_code})
    await db.commit()
    return ok(VariantOut.model_validate(variant).model_dump(mode="json"))


@router.patch("/variants/{variant_id}")
async def update_variant(
    variant_id: uuid.UUID,
    payload: VariantUpdate,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    variant = await db.get(ProductVariant, variant_id)
    if variant is None:
        raise NotFoundError("Variant not found.")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")
    if "attributes" in changes and changes["attributes"] is not None:
        validate_attributes(variant.product.category.attribute_schema, changes["attributes"])
    old = {k: getattr(variant, k) for k in changes}
    for field, value in changes.items():
        setattr(variant, field, value)
    variant.updated_by = uuid.UUID(user.id)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("Variant name already exists for this product.",
                            code="DUPLICATE_VARIANT") from exc
    await write_audit(db, action="variant.updated", entity_type="product_variant",
                      entity_id=variant.id, old=old, new=changes)
    await db.commit()
    return ok(VariantOut.model_validate(variant).model_dump(mode="json"))


# ---------- search / autocomplete ----------

@router.get("/search")
async def search_catalogue(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(15, ge=1, le=50),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    needle = f"%{q.strip()}%"
    stmt = (
        select(ProductVariant, Product, UnitOfMeasure.code)
        .join(Product, ProductVariant.product_id == Product.id)
        .join(UnitOfMeasure, ProductVariant.uom_id == UnitOfMeasure.id)
        .where(
            Product.is_active.is_(True),
            ProductVariant.is_active.is_(True),
            or_(
                Product.name.ilike(needle),
                Product.sku.ilike(needle),
                ProductVariant.variant_name.ilike(needle),
                ProductVariant.variant_code.ilike(needle),
            ),
        )
        .order_by(Product.name, ProductVariant.variant_name)
        .limit(limit)
    )
    hits = [
        SearchHit(
            product_id=product.id,
            variant_id=variant.id,
            label=f"{product.name} — {variant.variant_name}",
            sku=product.sku,
            variant_code=variant.variant_code,
            uom_code=uom_code,
        ).model_dump(mode="json")
        for variant, product, uom_code in (await db.execute(stmt)).all()
    ]
    return ok(hits)
