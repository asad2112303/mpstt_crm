#!/usr/bin/env python3
"""Clear transactional data so real trading can start from a clean slate.

Deletes quotations, orders, deliveries, invoices, payments and stock — the
records created while trialling the CRM — and resets the QT/ORD/INV/DC
counters so the first real document is numbered 0001.

Deliberately NOT touched: organizations, branches, contacts, prices,
requirement profiles, products, variants, users, and the audit log. The
customers behind the test orders are real imported records.

The deletion runs in ONE transaction: either all of it lands or none of it.
A JSON backup of every affected table is written first.

Usage:
    set -a && . ./.env && set +a
    DATABASE_URL="${DATABASE_URL/:5432/:6543}" uv run python scripts/reset_transactions.py --confirm
"""
import datetime
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ADMIN_ID = os.environ.get("MIGRATION_USER_ID", "7cab17f1-7861-4129-a102-820a9f1e7763")
BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"

# Children before parents, so no foreign key is left dangling.
DELETE_ORDER = [
    "payment_allocations",
    "receipts",
    "payments",
    "proof_of_delivery",
    "delivery_items",
    "deliveries",
    "invoice_items",
    "invoices",
    "quotation_items",
    "quotations",
    "stock_reservations",
    "sales_order_items",
    "sales_orders",
    "stock_movements",
    "stock_balances",
]

# ORG and CUST keep counting: the organizations they number are real and stay.
SEQUENCES_TO_RESET = ("QT", "ORD", "INV", "DC")


def main() -> int:
    if "--confirm" not in sys.argv:
        print("Refusing to run without --confirm (this deletes live records).")
        return 2

    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg", "postgresql")
    if not url:
        print("DATABASE_URL is not set.")
        return 2

    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"pre-reset-{stamp}.json"

    with psycopg.connect(url, row_factory=dict_row) as conn:
        dump = {
            "taken_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "tables": {
                table: conn.execute(f"select * from crm.{table}").fetchall()
                for table in DELETE_ORDER + ["number_sequences"]
            },
        }
        backup_path.write_text(json.dumps(dump, indent=1, default=str))
        total = sum(len(rows) for rows in dump["tables"].values())
        print(f"Backup: {backup_path} ({total} rows)")

    deleted: dict[str, int] = {}
    with psycopg.connect(url) as conn:
        with conn.transaction():
            for table in DELETE_ORDER:
                deleted[table] = conn.execute(f"delete from crm.{table}").rowcount
                print(f"  deleted {deleted[table]:>3}  {table}")

            reset = conn.execute(
                "update crm.number_sequences set next_value = 1 where prefix = any(%s)",
                (list(SEQUENCES_TO_RESET),),
            ).rowcount
            print(f"  reset {reset} number sequences to 1")

            conn.execute(
                """insert into crm.audit_log
                       (user_id, action, entity_type, entity_id, old_data, new_data, reason)
                   values (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    ADMIN_ID,
                    "system.transactional_reset",
                    "system",
                    "go-live",
                    json.dumps(deleted),
                    json.dumps({"sequences_reset": list(SEQUENCES_TO_RESET)}),
                    "Cleared trial transactions before entering real inventory and orders",
                ),
            )
    print(f"Committed. {sum(deleted.values())} rows deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
