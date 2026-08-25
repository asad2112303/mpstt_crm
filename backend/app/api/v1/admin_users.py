"""Admin-only user management. Public signup does not exist."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.envelope import ok
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import CurrentUser, require_admin
from app.models.access import UserProfile
from app.schemas.access import InviteUserIn, UpdateUserIn, UserProfileOut
from app.services import supabase_admin
from app.services.audit import write_audit

router = APIRouter(prefix="/admin/users", tags=["admin"])


@router.get("")
async def list_users(
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        (await db.execute(select(UserProfile).order_by(UserProfile.created_at))).scalars().all()
    )
    return ok([UserProfileOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/invite", status_code=201)
async def invite_user(
    payload: InviteUserIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    existing = (
        await db.execute(select(UserProfile).where(func.lower(UserProfile.email) == payload.email.lower()))
    ).scalar_one_or_none()
    if existing:
        raise ConflictError("A profile with this email already exists.", code="DUPLICATE_EMAIL")

    auth_user_id = await supabase_admin.invite_user(settings, payload.email)
    profile = UserProfile(
        id=auth_user_id,
        full_name=payload.full_name,
        email=payload.email,
        role=payload.role,
    )
    db.add(profile)
    await db.flush()
    await write_audit(
        db,
        action="user.invited",
        entity_type="user_profile",
        entity_id=profile.id,
        new={"email": payload.email, "role": payload.role},
    )
    await db.commit()
    return ok(UserProfileOut.model_validate(profile).model_dump(mode="json"))


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    payload: UpdateUserIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = (
        await db.execute(select(UserProfile).where(UserProfile.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if profile is None:
        raise NotFoundError("User not found.")

    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailedError("Nothing to update.")

    if str(user_id) == admin.id and changes.get("is_active") is False:
        raise ConflictError("You cannot deactivate your own account.", code="SELF_DEACTIVATION")

    # Never allow removing the last active admin.
    demoting = (changes.get("role") == "user" or changes.get("is_active") is False) and (
        profile.role == "admin" and profile.is_active
    )
    if demoting:
        active_admins = (
            await db.execute(
                select(func.count())
                .select_from(UserProfile)
                .where(UserProfile.role == "admin", UserProfile.is_active.is_(True))
            )
        ).scalar_one()
        if active_admins <= 1:
            raise ConflictError("At least one active admin is required.", code="LAST_ADMIN")

    old = {"full_name": profile.full_name, "role": profile.role, "is_active": profile.is_active}
    for field, value in changes.items():
        setattr(profile, field, value)
    await db.flush()
    await write_audit(
        db,
        action="user.updated",
        entity_type="user_profile",
        entity_id=profile.id,
        old=old,
        new=changes,
    )
    await db.commit()
    return ok(UserProfileOut.model_validate(profile).model_dump(mode="json"))
