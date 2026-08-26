"""Prospect domain rules: stage guards, duplicate detection, activity effects."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.models.organization import (
    MANUAL_STAGES,
    Organization,
    ProspectProfile,
)

# Stages that count as "later than" for automatic forward movement.
STAGE_ORDER = {
    "targeted": 0,
    "visited": 1,
    "requirement_collected": 2,
    "sample_provided": 3,
    "quotation_sent": 4,
    "negotiation": 5,
    "won": 9,
}
TERMINALISH = {"lost", "deferred"}


def validate_manual_stage_change(profile: ProspectProfile, new_stage: str, payload: dict) -> None:
    """Guards for PATCHing the stage by hand. 'won' is never manual."""
    if new_stage == "won":
        raise ConflictError(
            "'Won' cannot be set manually. It is produced by first-order conversion.",
            code="WON_IS_NOT_MANUAL",
        )
    if new_stage not in MANUAL_STAGES:
        raise ValidationFailedError(f"Unknown stage {new_stage!r}.")
    if profile.stage == "won":
        raise ConflictError("A converted organization's prospect history is read-only.")
    if new_stage == "lost" and not (payload.get("lost_reason") or profile.lost_reason):
        raise ValidationFailedError(
            "A reason is required to mark a prospect as lost.",
            field_errors={"lost_reason": ["Required"]},
        )
    if new_stage == "deferred" and not (payload.get("deferred_reason") or profile.deferred_reason):
        raise ValidationFailedError(
            "A reason is required to defer a prospect.",
            field_errors={"deferred_reason": ["Required"]},
        )


def advance_stage(profile: ProspectProfile, at_least: str) -> None:
    """Move the stage forward automatically (never backwards, never out of lost/deferred/won)."""
    if profile.stage in TERMINALISH or profile.stage == "won":
        return
    if STAGE_ORDER.get(at_least, -1) > STAGE_ORDER.get(profile.stage, -1):
        profile.stage = at_least


def touch_activity(profile: ProspectProfile, at: datetime | None = None) -> None:
    profile.last_activity_at = at or datetime.now(UTC)
    if profile.first_contact_date is None:
        profile.first_contact_date = (at or datetime.now(UTC)).date()


async def find_duplicates(
    session: AsyncSession,
    *,
    name: str,
    phone_normalized: str | None,
    exclude_id: uuid.UUID | None = None,
) -> list[dict]:
    """Similar-name (trigram) or same-phone matches. Warn — never auto-merge."""
    conditions = [func.similarity(Organization.name, name) > 0.45]
    if phone_normalized:
        conditions.append(Organization.phone_normalized == phone_normalized)
    stmt = (
        select(Organization, func.similarity(Organization.name, name).label("score"))
        .where(or_(*conditions))
        .order_by(func.similarity(Organization.name, name).desc())
        .limit(5)
    )
    if exclude_id:
        stmt = stmt.where(Organization.id != exclude_id)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "organization_id": str(org.id),
            "org_code": org.org_code,
            "name": org.name,
            "city": org.city,
            "lifecycle_status": org.lifecycle_status,
            "name_similarity": float(score or 0),
            "same_phone": bool(phone_normalized and org.phone_normalized == phone_normalized),
        }
        for org, score in rows
    ]
