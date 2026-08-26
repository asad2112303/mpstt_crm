"""Organization-level sub-resources shared by prospects and customers:
branches, contacts, and price history."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_user
from app.models.organization import (
    Organization,
    OrganizationBranch,
    OrganizationContact,
    OrganizationPrice,
)
from app.schemas.organization import BranchIn, BranchOut, ContactIn, ContactOut, PriceIn, PriceOut
from app.services.audit import write_audit
from app.services.phone import normalize_phone

router = APIRouter(prefix="/organizations", tags=["organizations"])


async def _ensure_org(db: AsyncSession, organization_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, organization_id)
    if org is None:
        raise NotFoundError("Organization not found.")
    return org


# ---------- branches ----------

@router.get("/{organization_id}/branches")
async def list_branches(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    rows = (
        (
            await db.execute(
                select(OrganizationBranch)
                .where(OrganizationBranch.organization_id == organization_id)
                .order_by(OrganizationBranch.is_primary.desc(), OrganizationBranch.branch_name)
            )
        )
        .scalars()
        .all()
    )
    return ok([BranchOut.model_validate(b).model_dump(mode="json") for b in rows])


@router.post("/{organization_id}/branches", status_code=201)
async def create_branch(
    organization_id: uuid.UUID,
    payload: BranchIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    branch = OrganizationBranch(organization_id=organization_id, **payload.model_dump())
    db.add(branch)
    await db.flush()
    await db.commit()
    return ok(BranchOut.model_validate(branch).model_dump(mode="json"))


@router.patch("/branches/{branch_id}")
async def update_branch(
    branch_id: uuid.UUID,
    payload: BranchIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    branch = await db.get(OrganizationBranch, branch_id)
    if branch is None:
        raise NotFoundError("Branch not found.")
    for field, value in payload.model_dump().items():
        setattr(branch, field, value)
    await db.flush()
    await db.commit()
    return ok(BranchOut.model_validate(branch).model_dump(mode="json"))


# ---------- contacts ----------

@router.get("/{organization_id}/contacts")
async def list_contacts(
    organization_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    rows = (
        (
            await db.execute(
                select(OrganizationContact)
                .where(OrganizationContact.organization_id == organization_id)
                .order_by(OrganizationContact.is_primary.desc(), OrganizationContact.full_name)
            )
        )
        .scalars()
        .all()
    )
    return ok([ContactOut.model_validate(c).model_dump(mode="json") for c in rows])


@router.post("/{organization_id}/contacts", status_code=201)
async def create_contact(
    organization_id: uuid.UUID,
    payload: ContactIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    contact = OrganizationContact(
        organization_id=organization_id,
        **payload.model_dump(),
        phone_primary_normalized=normalize_phone(payload.phone_primary),
    )
    db.add(contact)
    await db.flush()
    await db.commit()
    return ok(ContactOut.model_validate(contact).model_dump(mode="json"))


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contact = await db.get(OrganizationContact, contact_id)
    if contact is None:
        raise NotFoundError("Contact not found.")
    for field, value in payload.model_dump().items():
        setattr(contact, field, value)
    contact.phone_primary_normalized = normalize_phone(contact.phone_primary)
    await db.flush()
    await db.commit()
    return ok(ContactOut.model_validate(contact).model_dump(mode="json"))


# ---------- organization price history ----------

@router.get("/{organization_id}/prices")
async def list_prices(
    organization_id: uuid.UUID,
    product_id: uuid.UUID | None = Query(None),
    current_only: bool = Query(False),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    stmt = select(OrganizationPrice).where(OrganizationPrice.organization_id == organization_id)
    if product_id:
        stmt = stmt.where(OrganizationPrice.product_id == product_id)
    if current_only:
        today = date.today()
        stmt = stmt.where(
            OrganizationPrice.effective_from <= today,
            (OrganizationPrice.effective_to.is_(None)) | (OrganizationPrice.effective_to >= today),
        )
    rows = (
        (await db.execute(stmt.order_by(OrganizationPrice.effective_from.desc()))).scalars().all()
    )
    return ok([PriceOut.model_validate(p).model_dump(mode="json") for p in rows])


@router.post("/{organization_id}/prices", status_code=201)
async def create_price(
    organization_id: uuid.UUID,
    payload: PriceIn,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_org(db, organization_id)
    if payload.effective_to and payload.effective_to < payload.effective_from:
        raise ValidationFailedError(
            "effective_to cannot be before effective_from.",
            field_errors={"effective_to": ["Before effective_from"]},
        )

    # Effective periods for the same org/product/variant must not overlap.
    overlap_stmt = select(OrganizationPrice).where(
        OrganizationPrice.organization_id == organization_id,
        OrganizationPrice.product_id == payload.product_id,
        OrganizationPrice.effective_from <= (payload.effective_to or date.max),
        (OrganizationPrice.effective_to.is_(None))
        | (OrganizationPrice.effective_to >= payload.effective_from),
    )
    if payload.product_variant_id is None:
        overlap_stmt = overlap_stmt.where(OrganizationPrice.product_variant_id.is_(None))
    else:
        overlap_stmt = overlap_stmt.where(
            OrganizationPrice.product_variant_id == payload.product_variant_id
        )
    overlapping = (await db.execute(overlap_stmt.with_for_update())).scalars().all()
    if overlapping:
        raise ValidationFailedError(
            "An effective price already covers part of this period. Expire it first "
            "or choose non-overlapping dates. Price history is never overwritten.",
            field_errors={"effective_from": ["Overlapping price period"]},
        )

    price = OrganizationPrice(
        organization_id=organization_id,
        **payload.model_dump(),
        created_by=uuid.UUID(user.id),
    )
    db.add(price)
    await db.flush()
    await write_audit(db, action="price.created", entity_type="organization_price",
                      entity_id=price.id, new={"unit_price": str(payload.unit_price)})
    await db.commit()
    return ok(PriceOut.model_validate(price).model_dump(mode="json"))


@router.post("/prices/{price_id}/expire")
async def expire_price(
    price_id: uuid.UUID,
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    price = await db.get(OrganizationPrice, price_id)
    if price is None:
        raise NotFoundError("Price not found.")
    if price.effective_to and price.effective_to < date.today():
        return ok(PriceOut.model_validate(price).model_dump(mode="json"))
    price.effective_to = date.today()
    await db.flush()
    await write_audit(db, action="price.expired", entity_type="organization_price",
                      entity_id=price.id, new={"effective_to": str(price.effective_to)})
    await db.commit()
    return ok(PriceOut.model_validate(price).model_dump(mode="json"))
