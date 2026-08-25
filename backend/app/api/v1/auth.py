"""Auth endpoints."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.envelope import ok
from app.core.security import CurrentUser, require_user
from app.models.access import UserProfile
from app.schemas.access import MeOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def me(
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(
        update(UserProfile)
        .where(UserProfile.id == user.id)
        .values(last_login_at=datetime.now(UTC))
    )
    await db.commit()
    return ok(
        MeOut(
            id=user.id, full_name=user.full_name, email=user.email, role=user.role, aal=user.aal
        ).model_dump(mode="json")
    )
