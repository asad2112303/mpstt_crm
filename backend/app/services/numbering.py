"""Concurrency-safe human document numbers (QT-2026-0001 style).

Allocation locks the sequence row FOR UPDATE inside the caller's transaction,
so the number commits (or rolls back) together with the document it belongs
to. Never derived from MAX(number)+1.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import NumberSequence

PREFIXES = {
    "ORG": "ORG",
    "CUST": "CUST",
    "QT": "QT",
    "ORD": "ORD",
    "INV": "INV",
    "DC": "DC",
    "PAY": "PAY",
    "RCP": "RCP",
}

KARACHI = ZoneInfo("Asia/Karachi")


def business_year() -> int:
    return datetime.now(KARACHI).year


async def allocate_number(session: AsyncSession, document_type: str, *, year: int | None = None) -> str:
    if document_type not in PREFIXES:
        raise ValueError(f"Unknown document type {document_type!r}")
    year = year or business_year()

    # Ensure the row exists (no-op when it already does), then lock it.
    await session.execute(
        pg_insert(NumberSequence)
        .values(document_type=document_type, year=year, prefix=PREFIXES[document_type])
        .on_conflict_do_nothing(index_elements=["document_type", "year"])
    )
    seq = (
        await session.execute(
            select(NumberSequence)
            .where(NumberSequence.document_type == document_type, NumberSequence.year == year)
            .with_for_update()
        )
    ).scalar_one()

    number = f"{seq.prefix}-{year}-{str(seq.next_value).zfill(seq.padding)}"
    seq.next_value += 1
    await session.flush()
    return number
