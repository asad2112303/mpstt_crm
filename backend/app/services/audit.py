"""Append-only audit records, written in the same transaction as the mutation."""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import request_id_var, user_id_var
from app.models.access import AuditLog


def _jsonable(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, dict):
        return {k: _jsonable(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_jsonable(v) for v in data]
    if isinstance(data, (str, int, float, bool)):
        return data
    return str(data)


async def write_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    old: dict | None = None,
    new: dict | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=uuid.UUID(user_id_var.get()) if user_id_var.get() else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_data=_jsonable(old),
            new_data=_jsonable(new),
            reason=reason,
            request_id=request_id_var.get() or None,
        )
    )
    await session.flush()
