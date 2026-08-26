# KPI definitions (M10)

All date boundaries are Asia/Karachi days. Cancelled and reversed records are
**never** counted. Every KPI names its source so reports reconcile.

## Operational dashboard

| KPI | Definition | Source | Drill-down |
|---|---|---|---|
| Follow-ups due today | Open tasks with due date = today | `crm.tasks` | /follow-ups |
| Follow-ups overdue | Open tasks with due < now | `crm.tasks` | /follow-ups |
| No next action | Active prospects with zero open tasks | `crm.v_prospect_action_queue` | /follow-ups?missing |
| Samples awaiting feedback | Samples in status `issued` | `crm.samples` | prospect Samples tab |
| Open quotations | Quotations in status `sent` (incl. derived expired) | `crm.quotations` | /quotations?status=sent |
| Orders to prepare | Orders in `confirmed` or `preparing` | `crm.sales_orders` | /orders |
| Open deliveries | Challans in `draft` or `dispatched` | `crm.deliveries` | /deliveries |
| Missing PODs | Completed deliveries without POD row | `crm.v_delivery_exceptions` | /deliveries |
| Payments awaiting allocation | Payments `recorded`/`partially_allocated` | `crm.payments` | /payments |

## Management dashboard (Admin)

| KPI | Definition | Source |
|---|---|---|
| Funnel | Active organizations per prospect stage | `crm.prospect_profiles` |
| Conversion rate | won / (won + active-stage prospects) ×100 | `crm.prospect_profiles` |
| Quotations sent (month) | Quotes sent this calendar month (incl. later accepted/converted) | `crm.quotations.sent_at` |
| Confirmed sales (month) | Σ grand_total of orders not draft/cancelled with order_date in month | `crm.sales_orders` |
| Collections (month) | Σ non-reversed payment amounts with payment_date in month | `crm.payments` |
| Outstanding | Σ outstanding of issued invoices | `crm.v_receivables_aging` |
| Overdue | Outstanding where days_overdue > 0 | `crm.v_receivables_aging` |
| Aging buckets | Outstanding grouped current / 0-30 / 31-60 / 61-90 / 90+ | `crm.v_receivables_aging` |
| Low stock | Variant/warehouse rows with available < 50 | `crm.v_stock_available` |
| Fully delivered orders | Orders `fully_delivered` or `completed` | `crm.sales_orders` |

## Reports

- `/reports/pipeline` — funnel with missing-next-action counts.
- `/reports/sales` — non-draft/cancelled orders in the date range (default last 30 days).
- `/reports/collections` — non-reversed payments in range.
- `/reports/receivables` — the aging view verbatim.
- `/reports/deliveries` — exception rows (delayed / missing POD / rejected qty).
- `/reports/inventory` — stock available ascending.

CSV export of finance reports (sales, collections, receivables) writes a
`report.exported` audit event with the filters used.

## Reconciliation rules

- Sales report Σ = confirmed-sales KPI for the same range.
- Collections report Σ = collections KPI for the same range.
- Receivables report Σ outstanding = outstanding KPI.
- Inventory report available = on_hand − reserved for every row.
