"""Idempotency for high-impact POST actions.

Contract:
- The client sends an ``Idempotency-Key`` header (required on these routes).
- First request: the key row is inserted, the business function runs in the
  same transaction, and the response is stored with the key.
- Retry with the same key + same payload: the stored response is returned
  without re-executing the business function.
- Same key + different payload: 409 IDEMPOTENCY_CONFLICT.
- Concurrent duplicate: the second transaction blocks on the unique index
  until the first commits, then sees the stored row and replays the response.
"""
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IdempotencyConflictError, ValidationFailedError
from app.models.access import IdempotencyKey

KEY_TTL = timedelta(hours=48)


def require_idempotency_key(request: Request) -> str:
    key = request.headers.get("idempotency-key", "").strip()
    if not key:
        raise ValidationFailedError(
            "The Idempotency-Key header is required for this action.",
            code="IDEMPOTENCY_KEY_REQUIRED",
        )
    if len(key) > 200:
        raise ValidationFailedError("Idempotency-Key is too long (max 200 characters).")
    return key


def hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def run_idempotent(
    session: AsyncSession,
    *,
    user_id: str,
    action: str,
    key: str,
    payload: Any,
    fn: Callable[[], Awaitable[dict]],
    status_code: int = 200,
) -> tuple[dict, int, bool]:
    """Execute ``fn`` once per (user, action, key).

    Returns (response_body, status_code, replayed).
    ``fn`` runs inside the caller's transaction; the caller commits.
    """
    request_hash = hash_payload(payload)

    insert_stmt = (
        pg_insert(IdempotencyKey)
        .values(
            user_id=uuid.UUID(user_id),
            action=action,
            idempotency_key=key,
            request_hash=request_hash,
            expires_at=datetime.now(UTC) + KEY_TTL,
        )
        .on_conflict_do_nothing(constraint="uq_idem_user_action_key")
        .returning(IdempotencyKey.id)
    )
    try:
        inserted_id = (await session.execute(insert_stmt)).scalar_one_or_none()
    except IntegrityError as exc:  # pragma: no cover - safety net
        raise IdempotencyConflictError("Duplicate request in progress. Retry shortly.") from exc

    if inserted_id is None:
        existing = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.user_id == uuid.UUID(user_id),
                    IdempotencyKey.action == action,
                    IdempotencyKey.idempotency_key == key,
                )
            )
        ).scalar_one()
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "This idempotency key was already used with a different payload.",
                code="IDEMPOTENCY_CONFLICT",
            )
        if existing.response_status is None:
            raise IdempotencyConflictError(
                "The original request is still being processed. Retry shortly.",
                code="IDEMPOTENCY_IN_PROGRESS",
            )
        return existing.response_body or {}, existing.response_status, True

    body = await fn()
    await session.execute(
        IdempotencyKey.__table__.update()
        .where(IdempotencyKey.id == inserted_id)
        .values(response_status=status_code, response_body=json.loads(json.dumps(body, default=str)))
    )
    return body, status_code, False
