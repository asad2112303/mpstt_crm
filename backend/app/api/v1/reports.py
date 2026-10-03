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


# ---------------------------------------------------------------------------
# Business dashboard (billing, profit, inventory value)
# ---------------------------------------------------------------------------

PRESETS = ("today", "week", "month", "year", "custom")

# Per-line net sales and cost, with any header-level discount allocated across
# the lines pro-rata by line value. Without that allocation an invoice-wide
# discount would never reach the profit figure and margin would read high.
#
# Only issued invoices count: drafts and cancellations are not sales. Net sales
# excludes tax (tax collected is not revenue) and excludes delivery charges,
# which are reported separately so they cannot flatter gross margin.
LINE_BASE = """
    WITH scoped AS (
        SELECT
            i.id                AS invoice_id,
            i.invoice_date,
            i.organization_id,
            i.is_direct,
            i.grand_total,
            i.delivery_charge,
            ii.id               AS item_id,
            ii.product_id,
            ii.line_source,
            ii.quantity,
            ii.unit_cost,
            ii.line_net,
            i.overall_discount_amount,
            SUM(ii.line_net) OVER (PARTITION BY i.id) AS invoice_line_net
        FROM crm.invoices i
        JOIN crm.invoice_items ii ON ii.invoice_id = i.id
        WHERE i.status = 'issued'
          AND i.invoice_date BETWEEN :date_from AND :date_to
    ),
    lines AS (
        SELECT
            *,
            line_net - COALESCE(
                overall_discount_amount * line_net / NULLIF(invoice_line_net, 0), 0
            ) AS net_sales,
            CASE WHEN unit_cost IS NOT NULL THEN unit_cost * quantity END AS cogs
        FROM scoped
    )
"""


def _resolve_range(preset: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = today_karachi()
    if preset == "custom":
        if not date_from or not date_to:
            from app.core.errors import ValidationFailedError

            raise ValidationFailedError("A custom range needs both a start and an end date.")
        if date_from > date_to:
            from app.core.errors import ValidationFailedError

            raise ValidationFailedError("The start date is after the end date.")
        return date_from, date_to
    if preset == "today":
        return today, today
    if preset == "week":
        return today - timedelta(days=today.weekday()), today
    if preset == "year":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today  # month


@router.get("/dashboard/business")
async def business_dashboard(
    preset: str = Query("month", pattern="^(today|week|month|year|custom)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sales, profit, receivables and inventory for one date range.

    Every money figure here is derived from issued invoices only, so it can be
    reconciled against the invoice list. Lines whose cost is unknown are left
    out of profit and counted in ``sales_missing_cost`` instead — never costed
    at zero, which would report the sale price as pure profit.
    """
    start, end = _resolve_range(preset, date_from, date_to)
    params = {"date_from": start, "date_to": end}

    totals = (
        await db.execute(
            text(
                LINE_BASE
                + """
        SELECT
            COALESCE(SUM(net_sales), 0)                                   AS net_sales,
            COALESCE(SUM(cogs), 0)                                        AS cogs,
            COALESCE(SUM(net_sales) FILTER (WHERE cogs IS NOT NULL), 0)   AS sales_with_cost,
            COALESCE(SUM(net_sales) FILTER (WHERE cogs IS NULL), 0)       AS sales_missing_cost,
            COALESCE(SUM(net_sales) FILTER (WHERE line_source = 'stock'), 0)      AS sales_from_stock,
            COALESCE(SUM(net_sales) FILTER (WHERE line_source = 'quick_bill'), 0) AS sales_quick_bill,
            COUNT(DISTINCT invoice_id)                                    AS invoice_count
        FROM lines
        """
            ),
            params,
        )
    ).mappings().one()

    net_sales = totals["net_sales"] or 0
    cogs = totals["cogs"] or 0
    sales_with_cost = totals["sales_with_cost"] or 0
    # Profit is only meaningful over the sales we actually know the cost of.
    gross_profit = sales_with_cost - cogs
    gross_margin = (gross_profit / sales_with_cost * 100) if sales_with_cost else None
    coverage = (sales_with_cost / net_sales * 100) if net_sales else None

    headers = (
        await db.execute(
            text(
                """
        SELECT
            COALESCE(SUM(grand_total), 0) AS invoiced_total,
            COALESCE(SUM(delivery_charge), 0) AS delivery_charged,
            COUNT(*) AS invoice_count
        FROM crm.invoices
        WHERE status = 'issued' AND invoice_date BETWEEN :date_from AND :date_to
        """
            ),
            params,
        )
    ).mappings().one()

    collected = await _scalar(
        db,
        """
        SELECT COALESCE(SUM(amount), 0) FROM crm.payments
        WHERE status <> 'reversed' AND payment_date BETWEEN :date_from AND :date_to
        """,
        **params,
    )

    # Receivables are a position, not a flow: always as at today, never filtered
    # by the selected range.
    receivables = (
        await db.execute(
            text(
                """
        WITH open_invoices AS (
            SELECT i.id, i.grand_total, i.due_date,
                   COALESCE((
                       SELECT SUM(pa.allocated_amount)
                       FROM crm.payment_allocations pa
                       JOIN crm.payments p ON p.id = pa.payment_id
                       WHERE pa.invoice_id = i.id AND p.status <> 'reversed'
                   ), 0) AS allocated
            FROM crm.invoices i
            WHERE i.status = 'issued'
        )
        SELECT
            COALESCE(SUM(grand_total - allocated), 0) AS outstanding,
            COALESCE(SUM(grand_total - allocated)
                     FILTER (WHERE due_date < :today), 0) AS overdue,
            COUNT(*) FILTER (WHERE grand_total - allocated > 0) AS open_count
        FROM open_invoices
        WHERE grand_total - allocated > 0
        """
            ),
            {"today": today_karachi()},
        )
    ).mappings().one()

    inventory = (
        await db.execute(
            text(
                """
        SELECT
            COALESCE(SUM(b.on_hand * b.avg_cost) FILTER (WHERE b.avg_cost IS NOT NULL), 0)
                AS inventory_value,
            COUNT(*) FILTER (WHERE b.avg_cost IS NULL AND b.on_hand > 0) AS uncosted_lines
        FROM crm.stock_balances b
        JOIN crm.product_variants v ON v.id = b.product_variant_id
        JOIN crm.products p ON p.id = v.product_id
        WHERE p.track_stock AND p.is_active AND v.is_active
        """
            )
        )
    ).mappings().one()

    low_stock_count = await _scalar(
        db,
        """
        SELECT COUNT(*) FROM crm.product_variants v
        JOIN crm.products p ON p.id = v.product_id
        LEFT JOIN crm.stock_balances b ON b.product_variant_id = v.id
        WHERE p.track_stock AND p.is_active AND v.is_active
          AND v.reorder_level IS NOT NULL
          AND COALESCE(b.on_hand, 0) - COALESCE(b.reserved, 0) <= v.reorder_level
        """,
    )

    invoice_count = headers["invoice_count"] or 0
    return ok(
        {
            "range": {"preset": preset, "from": start.isoformat(), "to": end.isoformat()},
            "sales": {
                "net_sales": str(round(net_sales, 2)),
                "invoiced_total": str(round(headers["invoiced_total"], 2)),
                "delivery_charged": str(round(headers["delivery_charged"], 2)),
                "invoice_count": invoice_count,
                "average_invoice_value": (
                    str(round(headers["invoiced_total"] / invoice_count, 2))
                    if invoice_count
                    else "0"
                ),
                "from_stock": str(round(totals["sales_from_stock"], 2)),
                "quick_bill": str(round(totals["sales_quick_bill"], 2)),
            },
            "profit": {
                "cogs": str(round(cogs, 2)),
                "gross_profit": str(round(gross_profit, 2)),
                "gross_margin_percent": (
                    str(round(gross_margin, 1)) if gross_margin is not None else None
                ),
                "sales_with_cost": str(round(sales_with_cost, 2)),
                "sales_missing_cost": str(round(totals["sales_missing_cost"], 2)),
                "cost_coverage_percent": (
                    str(round(coverage, 1)) if coverage is not None else None
                ),
                "cost_complete": (totals["sales_missing_cost"] or 0) == 0,
            },
            "cash": {
                "collected": str(round(collected or 0, 2)),
                "outstanding": str(round(receivables["outstanding"], 2)),
                "overdue": str(round(receivables["overdue"], 2)),
                "open_invoices": receivables["open_count"],
            },
            "inventory": {
                "value": str(round(inventory["inventory_value"], 2)),
                "uncosted_lines": inventory["uncosted_lines"],
                "low_stock_count": low_stock_count or 0,
            },
        }
    )


@router.get("/dashboard/business/breakdown")
async def business_breakdown(
    preset: str = Query("month", pattern="^(today|week|month|year|custom)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    user: CurrentUser = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trend series, best sellers, top customers and recent invoices."""
    start, end = _resolve_range(preset, date_from, date_to)
    params = {"date_from": start, "date_to": end}
    span = (end - start).days
    # Daily points for short ranges, monthly once a year is in view.
    bucket = "day" if span <= 62 else "month"

    trend = (
        await db.execute(
            text(
                LINE_BASE
                + f"""
        SELECT date_trunc('{bucket}', invoice_date)::date AS bucket,
               COALESCE(SUM(net_sales), 0) AS net_sales,
               COALESCE(SUM(net_sales) FILTER (WHERE cogs IS NOT NULL), 0)
                   - COALESCE(SUM(cogs), 0) AS gross_profit
        FROM lines
        GROUP BY 1 ORDER BY 1
        """
            ),
            params,
        )
    ).mappings().all()

    products = (
        await db.execute(
            text(
                LINE_BASE
                + """
        SELECT p.id, p.name,
               COALESCE(SUM(l.net_sales), 0) AS net_sales,
               COALESCE(SUM(l.quantity), 0) AS quantity,
               COALESCE(SUM(l.net_sales) FILTER (WHERE l.cogs IS NOT NULL), 0)
                   - COALESCE(SUM(l.cogs), 0) AS gross_profit
        FROM lines l JOIN crm.products p ON p.id = l.product_id
        GROUP BY p.id, p.name ORDER BY net_sales DESC LIMIT :limit
        """
            ),
            {**params, "limit": limit},
        )
    ).mappings().all()

    categories = (
        await db.execute(
            text(
                LINE_BASE
                + """
        SELECT c.name,
               COALESCE(SUM(l.net_sales), 0) AS net_sales
        FROM lines l
        JOIN crm.products p ON p.id = l.product_id
        JOIN crm.product_categories c ON c.id = p.category_id
        GROUP BY c.name ORDER BY net_sales DESC LIMIT :limit
        """
            ),
            {**params, "limit": limit},
        )
    ).mappings().all()

    customers = (
        await db.execute(
            text(
                LINE_BASE
                + """
        SELECT o.id, o.name, o.is_system,
               COALESCE(SUM(l.net_sales), 0) AS net_sales,
               COUNT(DISTINCT l.invoice_id) AS invoice_count
        FROM lines l JOIN crm.organizations o ON o.id = l.organization_id
        GROUP BY o.id, o.name, o.is_system ORDER BY net_sales DESC LIMIT :limit
        """
            ),
            {**params, "limit": limit},
        )
    ).mappings().all()

    recent = (
        await db.execute(
            text(
                """
        SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, i.grand_total,
               i.is_direct, i.is_walk_in, i.walk_in_name, o.name AS customer_name,
               COALESCE((
                   SELECT SUM(pa.allocated_amount) FROM crm.payment_allocations pa
                   JOIN crm.payments p ON p.id = pa.payment_id
                   WHERE pa.invoice_id = i.id AND p.status <> 'reversed'
               ), 0) AS allocated
        FROM crm.invoices i
        JOIN crm.organizations o ON o.id = i.organization_id
        WHERE i.status = 'issued'
        ORDER BY i.issued_at DESC NULLS LAST, i.invoice_date DESC
        LIMIT :limit
        """
            ),
            {"limit": max(limit, 8)},
        )
    ).mappings().all()

    today = today_karachi()

    def payment_state(row) -> str:
        outstanding = row["grand_total"] - row["allocated"]
        if outstanding <= 0:
            return "paid"
        if row["allocated"] > 0:
            return "partially_paid"
        if row["due_date"] and row["due_date"] < today:
            return "overdue"
        return "unpaid"

    return ok(
        {
            "range": {"preset": preset, "from": start.isoformat(), "to": end.isoformat()},
            "bucket": bucket,
            "trend": [
                {
                    "bucket": r["bucket"].isoformat(),
                    "net_sales": str(round(r["net_sales"], 2)),
                    "gross_profit": str(round(r["gross_profit"], 2)),
                }
                for r in trend
            ],
            "top_products": [
                {
                    "product_id": str(r["id"]),
                    "name": r["name"],
                    "net_sales": str(round(r["net_sales"], 2)),
                    "quantity": str(r["quantity"]),
                    "gross_profit": str(round(r["gross_profit"], 2)),
                }
                for r in products
            ],
            "top_categories": [
                {"name": r["name"], "net_sales": str(round(r["net_sales"], 2))}
                for r in categories
            ],
            "top_customers": [
                {
                    "organization_id": str(r["id"]),
                    "name": "Walk-in sales" if r["is_system"] else r["name"],
                    "net_sales": str(round(r["net_sales"], 2)),
                    "invoice_count": r["invoice_count"],
                }
                for r in customers
            ],
            "recent_invoices": [
                {
                    "id": str(r["id"]),
                    "invoice_number": r["invoice_number"],
                    "invoice_date": r["invoice_date"].isoformat() if r["invoice_date"] else None,
                    "customer_name": (
                        r["walk_in_name"] or "Walk-in Customer"
                        if r["is_walk_in"]
                        else r["customer_name"]
                    ),
                    "grand_total": str(round(r["grand_total"], 2)),
                    "received": str(round(r["allocated"], 2)),
                    "outstanding": str(round(r["grand_total"] - r["allocated"], 2)),
                    "payment_status": payment_state(r),
                    "is_direct": r["is_direct"],
                }
                for r in recent
            ],
        }
    )
