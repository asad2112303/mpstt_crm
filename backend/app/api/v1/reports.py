"""M10: dashboard summary, reports, global search, CSV export.

Every KPI is defined in docs/kpi-definitions.md. Cancelled and reversed
records are never counted. All date boundaries use Asia/Karachi days.
"""
import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response as RawResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.envelope import ok
from app.core.security import CurrentUser, require_user
from app.services.audit import write_audit

router = APIRouter(tags=["reports"])

KARACHI = ZoneInfo("Asia/Karachi")


def today_karachi() -> date:
    return datetime.now(KARACHI).date()


async def _scalar(db: AsyncSession, sql: str, **params):
    return (await db.execute(text(sql), params)).scalar()


@router.get("/dashboard/summary")
async def dashboard_summary(
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    today = today_karachi()
    month_start = today.replace(day=1)

    operational = {
        "followups_due_today": await _scalar(
            db,
            "SELECT count(*) FROM crm.tasks WHERE status='open' "
            "AND (due_at AT TIME ZONE 'Asia/Karachi')::date = :today",
            today=today,
        ),
        "followups_overdue": await _scalar(
            db, "SELECT count(*) FROM crm.tasks WHERE status='open' AND due_at < now()"
        ),
        "prospects_missing_next_action": await _scalar(
            db, "SELECT count(*) FROM crm.v_prospect_action_queue WHERE missing_next_action"
        ),
        "samples_awaiting_feedback": await _scalar(
            db, "SELECT count(*) FROM crm.samples WHERE status='issued'"
        ),
        "open_quotations": await _scalar(
            db, "SELECT count(*) FROM crm.quotations WHERE status='sent'"
        ),
        "orders_to_prepare": await _scalar(
            db, "SELECT count(*) FROM crm.sales_orders WHERE status IN ('confirmed','preparing')"
        ),
        "deliveries_open": await _scalar(
            db, "SELECT count(*) FROM crm.deliveries WHERE status IN ('draft','dispatched')"
        ),
        "missing_pods": await _scalar(
            db, "SELECT count(*) FROM crm.v_delivery_exceptions WHERE missing_pod"
        ),
        "payments_awaiting_allocation": await _scalar(
            db,
            "SELECT count(*) FROM crm.payments "
            "WHERE status IN ('recorded','partially_allocated')",
        ),
    }

    funnel_rows = (
        await db.execute(text(
            "SELECT pp.stage, count(*) FROM crm.prospect_profiles pp "
            "JOIN crm.organizations o ON o.id = pp.organization_id "
            "WHERE o.is_active GROUP BY pp.stage"
        ))
    ).all()
    funnel = {stage: count for stage, count in funnel_rows}
    total_prospects = sum(v for k, v in funnel.items() if k not in ("won",))
    won = funnel.get("won", 0)

    management = {
        "funnel": funnel,
        "conversion_rate_pct": round(100 * won / (won + total_prospects), 1)
        if (won + total_prospects) else 0,
        "quotations_sent_this_month": await _scalar(
            db,
            "SELECT count(*) FROM crm.quotations WHERE status IN "
            "('sent','accepted','converted') AND (sent_at AT TIME ZONE 'Asia/Karachi')::date >= :ms",
            ms=month_start,
        ),
        "confirmed_sales_this_month": str(await _scalar(
            db,
            "SELECT COALESCE(sum(grand_total),0) FROM crm.sales_orders "
            "WHERE status NOT IN ('draft','cancelled') AND order_date >= :ms",
            ms=month_start,
        )),
        "collections_this_month": str(await _scalar(
            db,
            "SELECT COALESCE(sum(amount),0) FROM crm.payments "
            "WHERE status <> 'reversed' AND payment_date >= :ms",
            ms=month_start,
        )),
        "outstanding_total": str(await _scalar(
            db, "SELECT COALESCE(sum(outstanding),0) FROM crm.v_receivables_aging"
        )),
        "overdue_total": str(await _scalar(
            db,
            "SELECT COALESCE(sum(outstanding),0) FROM crm.v_receivables_aging "
            "WHERE days_overdue > 0",
        )),
        "aging_buckets": {
            bucket: str(amount)
            for bucket, amount in (
                await db.execute(text(
                    "SELECT bucket, sum(outstanding) FROM crm.v_receivables_aging GROUP BY bucket"
                ))
            ).all()
        },
        "low_stock_count": await _scalar(
            db, "SELECT count(*) FROM crm.v_stock_available WHERE available < 50"
        ),
        "fully_delivered_orders": await _scalar(
            db,
            "SELECT count(*) FROM crm.sales_orders "
            "WHERE status IN ('fully_delivered','completed')",
        ),
    }

    payload = {"operational": operational, "as_of": today.isoformat()}
    if user.is_admin:
        payload["management"] = management
    return ok(payload)


# ---------- reports ----------

REPORT_QUERIES = {
    "pipeline": (
        "SELECT pp.stage, count(*) AS prospects, "
        "count(*) FILTER (WHERE q.open_tasks = 0) AS missing_next_action "
        "FROM crm.prospect_profiles pp "
        "JOIN crm.organizations o ON o.id = pp.organization_id "
        "LEFT JOIN LATERAL (SELECT count(*) AS open_tasks FROM crm.tasks t "
        "  WHERE t.organization_id = o.id AND t.status = 'open') q ON true "
        "WHERE o.is_active GROUP BY pp.stage ORDER BY pp.stage",
        False,
    ),
    "sales": (
        "SELECT so.order_date, so.order_number, o.name AS customer, so.status, "
        "so.grand_total FROM crm.sales_orders so "
        "JOIN crm.organizations o ON o.id = so.organization_id "
        "WHERE so.status NOT IN ('draft','cancelled') "
        "AND so.order_date BETWEEN :date_from AND :date_to "
        "ORDER BY so.order_date DESC",
        True,
    ),
    "collections": (
        "SELECT p.payment_date, p.payment_number, o.name AS customer, p.method, "
        "p.amount, p.status FROM crm.payments p "
        "JOIN crm.organizations o ON o.id = p.organization_id "
        "WHERE p.status <> 'reversed' "
        "AND p.payment_date BETWEEN :date_from AND :date_to "
        "ORDER BY p.payment_date DESC",
        True,
    ),
    "receivables": (
        "SELECT invoice_number, organization_name AS customer, invoice_date, due_date, "
        "grand_total, allocated, outstanding, days_overdue, bucket "
        "FROM crm.v_receivables_aging ORDER BY days_overdue DESC",
        False,
    ),
    "deliveries": (
        "SELECT challan_number, organization_name AS customer, status, "
        "scheduled_date, delayed, missing_pod, rejected_total "
        "FROM crm.v_delivery_exceptions ORDER BY scheduled_date NULLS LAST",
        False,
    ),
    "inventory": (
        "SELECT warehouse_code, sku, product_name, variant_name, uom_code, "
        "on_hand, reserved, available FROM crm.v_stock_available "
        "ORDER BY available ASC",
        False,
    ),
}

FINANCE_REPORTS = {"sales", "collections", "receivables"}


@router.get("/reports/{report_name}")
async def run_report(
    report_name: str,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    format: str = Query("json", pattern="^(json|csv)$"),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if report_name not in REPORT_QUERIES:
        from app.core.errors import NotFoundError

        raise NotFoundError("Unknown report.")
    sql, needs_dates = REPORT_QUERIES[report_name]
    params = {}
    if needs_dates:
        params["date_from"] = date_from or (today_karachi() - timedelta(days=30))
        params["date_to"] = date_to or today_karachi()

    rows = [dict(r) for r in (await db.execute(text(sql), params)).mappings().all()]
    for row in rows:
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            elif not isinstance(value, (str, int, float, bool, type(None))):
                row[key] = str(value)

    if format == "csv":
        if report_name in FINANCE_REPORTS:
            await write_audit(db, action="report.exported", entity_type="report",
                              entity_id=report_name,
                              new={"format": "csv", "rows": len(rows),
                                   "date_from": str(params.get("date_from")),
                                   "date_to": str(params.get("date_to"))})
            await db.commit()
        buffer = io.StringIO()
        if rows:
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return RawResponse(
            content=buffer.getvalue(), media_type="text/csv",
            headers={"Content-Disposition":
                     f'attachment; filename="{report_name}-{today_karachi()}.csv"'},
        )
    return ok({"report": report_name, "rows": rows,
               "filters": {k: str(v) for k, v in params.items()}})


# ---------- global search ----------

@router.get("/search")
async def global_search(
    q: str = Query(min_length=2, max_length=120),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    needle = f"%{q.strip()}%"
    results: list[dict] = []

    orgs = (
        await db.execute(text(
            "SELECT id, org_code, name, lifecycle_status FROM crm.organizations "
            "WHERE name ILIKE :n OR org_code ILIKE :n ORDER BY name LIMIT 8"
        ), {"n": needle})
    ).all()
    for row in orgs:
        kind = "customer" if row.lifecycle_status == "customer" else "prospect"
        results.append({
            "kind": kind, "id": str(row.id),
            "label": f"{row.name} ({row.org_code})",
            "href": f"/{'customers' if kind == 'customer' else 'prospects'}/{row.id}",
        })

    for kind, table, number_col, href in (
        ("quotation", "crm.quotations", "quotation_number", "/quotations/{id}"),
        ("order", "crm.sales_orders", "order_number", "/orders/{id}"),
        ("invoice", "crm.invoices", "invoice_number", "/invoices/{id}"),
        ("delivery", "crm.deliveries", "challan_number", "/deliveries/{id}"),
        ("payment", "crm.payments", "payment_number", "/payments"),
    ):
        rows = (
            await db.execute(text(
                f"SELECT id, {number_col} AS number FROM {table} "
                f"WHERE {number_col} ILIKE :n LIMIT 5"
            ), {"n": needle})
        ).all()
        for row in rows:
            if row.number:
                results.append({
                    "kind": kind, "id": str(row.id), "label": row.number,
                    "href": href.replace("{id}", str(row.id)),
                })
    return ok(results[:30])
