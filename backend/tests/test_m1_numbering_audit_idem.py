"""M1: concurrency-safe numbering, append-only audit, idempotency semantics."""
import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.conftest import TEST_DATABASE_URL
from tests.helpers import seed_profile


async def test_concurrent_number_allocation_is_unique(db_session):
    """10 parallel transactions must yield 10 distinct sequential numbers."""
    from app.services.numbering import allocate_number

    engine = create_async_engine(TEST_DATABASE_URL, pool_size=12)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def allocate_one() -> str:
        async with factory() as session:
            async with session.begin():
                return await allocate_number(session, "QT", year=2099)

    numbers = await asyncio.gather(*[allocate_one() for _ in range(10)])
    await engine.dispose()

    assert len(set(numbers)) == 10
    suffixes = sorted(int(n.split("-")[-1]) for n in numbers)
    assert suffixes == list(range(suffixes[0], suffixes[0] + 10))
    assert all(n.startswith("QT-2099-") for n in numbers)


async def test_number_format_and_padding(db_session):
    from app.services.numbering import allocate_number

    async with db_session.begin():
        number = await allocate_number(db_session, "INV", year=2098)
    assert number == "INV-2098-0001"


async def test_audit_log_is_append_only(db_session):
    from app.services.audit import write_audit

    async with db_session.begin():
        await write_audit(
            db_session, action="test.append", entity_type="test", entity_id="x", new={"a": 1}
        )

    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin():
            await db_session.execute(
                text("UPDATE crm.audit_log SET action = 'tampered' WHERE action = 'test.append'")
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin():
            await db_session.execute(text("DELETE FROM crm.audit_log WHERE action = 'test.append'"))


async def test_idempotency_replay_and_conflict(db_session):
    from app.services.idempotency import run_idempotent

    user_id = await seed_profile(db_session)
    key = f"key-{uuid.uuid4()}"
    calls = {"n": 0}

    async def business() -> dict:
        calls["n"] += 1
        return {"result": "created", "call": calls["n"]}

    async with db_session.begin():
        body1, status1, replayed1 = await run_idempotent(
            db_session, user_id=user_id, action="test.create", key=key,
            payload={"amount": "10.00"}, fn=business, status_code=201,
        )
    assert (status1, replayed1, calls["n"]) == (201, False, 1)

    # Same key + same payload: replay without executing again.
    async with db_session.begin():
        body2, status2, replayed2 = await run_idempotent(
            db_session, user_id=user_id, action="test.create", key=key,
            payload={"amount": "10.00"}, fn=business, status_code=201,
        )
    assert (status2, replayed2, calls["n"]) == (201, True, 1)
    assert body2["result"] == "created"

    # Same key + different payload: 409.
    from app.core.errors import IdempotencyConflictError

    with pytest.raises(IdempotencyConflictError):
        async with db_session.begin():
            await run_idempotent(
                db_session, user_id=user_id, action="test.create", key=key,
                payload={"amount": "99.00"}, fn=business, status_code=201,
            )


async def test_idempotent_failure_rolls_back_key(db_session):
    """If the business function fails, the key row must not survive."""
    from app.services.idempotency import run_idempotent

    user_id = await seed_profile(db_session)
    key = f"key-{uuid.uuid4()}"

    async def failing() -> dict:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        async with db_session.begin():
            await run_idempotent(
                db_session, user_id=user_id, action="test.fail", key=key,
                payload={}, fn=failing,
            )

    # A retry after failure executes the business function again.
    async def succeeding() -> dict:
        return {"ok": True}

    async with db_session.begin():
        body, status, replayed = await run_idempotent(
            db_session, user_id=user_id, action="test.fail", key=key,
            payload={}, fn=succeeding,
        )
    assert (body["ok"], replayed) == (True, False)
