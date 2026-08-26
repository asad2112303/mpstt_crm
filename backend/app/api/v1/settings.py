"""M11: company settings (singleton) and the audit viewer."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.envelope import ok
from app.core.security import CurrentUser, require_admin, require_user
from app.models.access import AuditLog, CompanySettings
from app.services.audit import write_audit

router = APIRouter(tags=["settings"])

DEFAULTS = {
    "company_name": "Medical Prism Supplies for Treatment and Technology",
}


class SettingsIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    website: str | None = Field(default=None, max_length=255)
    ntn: str | None = Field(default=None, max_length=50)
    strn: str | None = Field(default=None, max_length=50)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    bank_details: str | None = None
    default_currency: str = Field(default="PKR", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Karachi", max_length=50)
    default_payment_terms_days: int = Field(default=30, ge=0, le=365)
    quotation_terms: str | None = None
    document_footer: str | None = None
    logo_document_id: uuid.UUID | None = None


class SettingsOut(SettingsIn):
    model_config = ConfigDict(from_attributes=True)
    updated_at: datetime


async def get_company_settings(db: AsyncSession) -> CompanySettings:
    """Fetch (or lazily create) the singleton settings row."""
    settings = await db.get(CompanySettings, 1)
    if settings is None:
        settings = CompanySettings(id=1, **DEFAULTS)
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


@router.get("/settings")
async def read_settings(
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await get_company_settings(db)
    await db.commit()
    return ok(SettingsOut.model_validate(settings).model_dump(mode="json"))


@router.put("/admin/settings")
async def update_settings(
    payload: SettingsIn,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = await get_company_settings(db)
    old = {k: str(getattr(settings, k)) for k in payload.model_dump()}
    for field, value in payload.model_dump().items():
        setattr(settings, field, value)
    settings.updated_by = uuid.UUID(admin.id)
    await db.flush()
    await write_audit(db, action="settings.updated", entity_type="company_settings",
                      entity_id="1", old=old,
                      new={k: str(v) for k, v in payload.model_dump().items()})
    await db.refresh(settings)
    result = SettingsOut.model_validate(settings).model_dump(mode="json")
    await db.commit()
    return ok(result)


@router.get("/admin/audit")
async def audit_log(
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                stmt.order_by(AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        [
            {
                "id": r.id,
                "user_id": str(r.user_id) if r.user_id else None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "old_data": r.old_data,
                "new_data": r.new_data,
                "reason": r.reason,
                "request_id": r.request_id,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        page=page, page_size=page_size, total=total,
    )
