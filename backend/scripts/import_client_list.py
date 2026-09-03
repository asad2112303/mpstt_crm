#!/usr/bin/env python3
"""Import the Clean & Green "Client List" (27 accounts) via the staged pipeline.

Source: Client List.pdf provided by MPSTT. Contract value, year, status and
service type are preserved in each organization's notes; ongoing accounts stay
active customers and closed contracts are marked account_status='closed'.

Usage (from backend/, uses DATABASE_URL from .env):
    PYTHONPATH=$PWD uv run python scripts/import_client_list.py
"""
import asyncio
import csv
import io
import os
import sys

os.environ.setdefault("APP_ENV", "development")

ADMIN_ID = os.environ.get("MIGRATION_USER_ID", "7cab17f1-7861-4129-a102-820a9f1e7763")

# (name, org_type, city, value, years, status, services)
CLIENTS = [
    ("Australian High Commission", "government", "Islamabad", "2,795,346", "2026", "OnGoing", "Cleaning & Gardening Services"),
    ("Federal Government Housing Authority Islamabad", "government", "Islamabad", "45,576,564", "2026", "OnGoing", "Horticulture & Gardening"),
    ("Evacuee Trust Complex", "government", "Islamabad", "27,288,000", "2026", "OnGoing", "Janitorial Services"),
    ("NADRA Balochistan", "government", "Quetta", "25,692,000", "2026", "OnGoing", "Janitorial Services"),
    ("NADRA Gawdar", "government", "Gwadar", "20,856,000", "2026", "OnGoing", "Janitorial Services"),
    ("Motives", "other", "", "29,064,000", "2026", "OnGoing", "Janitorial Services"),
    ("National Insurance Company", "government", "Islamabad", "12,828,000", "2026", "OnGoing", "Janitorial Services"),
    ("Pakistan Engineering Council", "government", "Islamabad", "15,841,296", "2026", "OnGoing", "Janitorial Services"),
    ("EXIM Bank of Pakistan", "government", "Islamabad", "10,200,000", "2026", "OnGoing", "Outsourcing manpower"),
    ("Embassy Of Spain", "government", "Islamabad", "5,909,040", "2026", "OnGoing", "Janitorial Services"),
    ("Jhpiego Corporation", "ngo", "Islamabad", "6,996,000", "2026", "OnGoing", "Janitorial Services"),
    ("Universal Services Fund", "government", "Islamabad", "2,489,568", "2026", "OnGoing", "Janitorial Services"),
    ("Philippine Embassy", "government", "Islamabad", "3,341,988", "2026", "OnGoing", "Janitorial Services"),
    ("Federal Public Service Commission", "government", "Islamabad", "8,278,608", "2026", "OnGoing", "Janitorial Services"),
    ("Ministry of Foreign Affairs Lahore", "government", "Lahore", "4,696,692", "2026", "OnGoing", "Janitorial Services"),
    ("PTA Quetta", "government", "Quetta", "1,423,332", "2026", "OnGoing", "Janitorial Services"),
    ("National Commission on the Rights of Child (NCRC)", "government", "Islamabad", "1,898,172", "2026", "OnGoing", "Janitorial Services"),
    ("United States Education Foundation Pakistan", "ngo", "Islamabad", "2,119,356", "2026", "OnGoing", "Janitorial Services"),
    ("NHA Multan", "government", "Multan", "5,400,000", "2021", "Closed", "Janitorial Services"),
    ("NHA Gilgit", "government", "Gilgit", "1,935,000", "2021", "Closed", "Janitorial Services"),
    ("SNGPL Abbottabad", "government", "Abbottabad", "4,140,000", "2020", "Closed", "Janitorial Services"),
    ("Hayatabad Medical Complex Peshawar", "hospital", "Peshawar", "", "", "Closed", "Janitorial Services"),
    ("AGPR Balochistan", "government", "Quetta", "1,164,000", "2021", "Closed", "Janitorial Services"),
    ("NADRA RHO Quetta", "government", "Quetta", "14,112,000", "2021-2024", "Closed", "Janitorial Services"),
    ("Wateen Telecom", "other", "", "16,092,000", "2022", "Closed", "Janitorial Services"),
    ("Cabinet Division", "government", "Islamabad", "24,966,000", "2023-2025", "Closed", "Janitorial Services"),
    ("National TB Control", "government", "Islamabad", "3,358,572", "2022", "Closed", "Janitorial Services"),
]
CLOSED_NAMES = [c[0] for c in CLIENTS if c[5] == "Closed"]


def build_csv() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["name", "org_type", "city", "source", "customer_since", "notes"])
    for name, org_type, city, value, years, status, services in CLIENTS:
        first_year = years.split("-")[0] if years else "2020"
        parts = []
        if value:
            parts.append(f"Contract value PKR {value}")
        if years:
            parts.append(f"Year {years}")
        parts.append(f"Status: {status}")
        parts.append(f"Services: {services}")
        writer.writerow([name, org_type, city, "Client List.pdf",
                         f"{first_year}-01-01", " | ".join(parts)])
    return buffer.getvalue().encode()


async def main() -> int:
    from sqlalchemy import text

    from app.core.db import dispose_engine, get_session_factory
    from app.services.imports import approve_import, stage_import

    async with get_session_factory()() as s:
        existing = (
            await s.execute(text(
                "SELECT count(*) FROM crm.organizations WHERE source = 'Client List.pdf'"
            ))
        ).scalar_one()
        if existing:
            print(f"ABORT: {existing} organizations already imported from Client List.pdf")
            return 1

        batch = await stage_import(s, filename="Client List.pdf.csv",
                                   content=build_csv(), uploaded_by=ADMIN_ID)
        await s.commit()
        print(f"staged: source={batch.source_count} ready={batch.ready_count} "
              f"errors={batch.error_count} duplicates={batch.duplicate_count}")

        # Names in this list are distinct organizations; trigram look-alikes are
        # confirmed for import rather than skipped.
        batch = await approve_import(s, batch_id=batch.id, user_id=ADMIN_ID,
                                     include_duplicates=True)
        await s.commit()
        print(f"approved: imported={batch.imported_count} rejected={batch.rejected_count}")

        result = await s.execute(
            text("""
                UPDATE crm.customer_profiles cp SET account_status='closed'
                FROM crm.organizations o
                WHERE o.id = cp.organization_id
                  AND o.source = 'Client List.pdf'
                  AND o.name = ANY(:names)
            """),
            {"names": CLOSED_NAMES},
        )
        await s.commit()
        print(f"closed accounts marked: {result.rowcount}")

    await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
