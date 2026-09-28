"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, Banknote, FilePlus, FileText, PackagePlus, Receipt, TrendingUp,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import {
  DATE_PRESETS, pkr, pkrExact,
  type BusinessBreakdown, type BusinessDashboard,
} from "@/lib/types/billing";
import { TrendChart } from "@/components/billing/trend-chart";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const ACTIONS = [
  { href: "/create-bill?mode=quick", label: "Create Quick Bill", icon: FilePlus, primary: true },
  { href: "/create-bill?mode=stock", label: "Invoice from Stock", icon: FileText },
  { href: "/inventory?tab=receive", label: "Add Stock", icon: PackagePlus },
  { href: "/payments", label: "Record Payment", icon: Banknote },
  { href: "/invoices", label: "View Invoices", icon: Receipt },
];

/** A money figure that opens the records behind it. */
function Tile({
  label, value, href, hint, tone = "default",
}: {
  label: string;
  value: string;
  href: string;
  hint?: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  return (
    <Link
      href={href}
      className="group rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/50 sm:p-4"
    >
      <span className="block text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          "mt-1 block text-lg font-semibold tabular-nums sm:text-xl",
          tone === "bad" && "text-destructive",
          tone === "good" && "text-primary",
        )}
      >
        {value}
      </span>
      {hint && <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>}
    </Link>
  );
}

function RankList({
  title, rows, href,
}: {
  title: string;
  rows: { key: string; name: string; value: string; sub?: string }[];
  href?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => Number(r.value)));
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">Nothing in this period.</p>
      ) : (
        <ol className="mt-3 space-y-2">
          {rows.map((r) => (
            <li key={r.key} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 truncate">{r.name}</span>
                <span className="shrink-0 tabular-nums">{pkr(r.value)}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(Number(r.value) / max) * 100}%` }}
                />
              </div>
              {r.sub && <p className="text-xs text-muted-foreground">{r.sub}</p>}
            </li>
          ))}
        </ol>
      )}
      {href && rows.length > 0 && (
        <Link href={href} className="mt-3 inline-block text-xs text-primary hover:underline">
          See all
        </Link>
      )}
    </div>
  );
}

const PAYMENT_TONE: Record<string, string> = {
  paid: "bg-primary/15 text-primary",
  partially_paid: "bg-warning/20 text-warning-foreground",
  overdue: "bg-destructive/15 text-destructive",
  unpaid: "bg-muted text-muted-foreground",
};

export function BusinessOverview() {
  const [preset, setPreset] = useState("month");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const params = {
    preset,
    date_from: preset === "custom" ? from || undefined : undefined,
    date_to: preset === "custom" ? to || undefined : undefined,
  };
  const ready = preset !== "custom" || (!!from && !!to);

  const summary = useQuery({
    queryKey: ["business-dashboard", params],
    queryFn: async () =>
      (await api<BusinessDashboard>("/api/v1/dashboard/business", { searchParams: params })).data,
    enabled: ready,
  });
  const breakdown = useQuery({
    queryKey: ["business-breakdown", params],
    queryFn: async () =>
      (await api<BusinessBreakdown>("/api/v1/dashboard/business/breakdown", {
        searchParams: params,
      })).data,
    enabled: ready,
  });

  const d = summary.data;
  const b = breakdown.data;
  const range = preset === "custom" ? `${from}…${to}` : preset;

  return (
    <section aria-label="Business overview" className="space-y-4">
      {/* actions first: the point is to start a bill in one click */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {ACTIONS.map((a) => (
          <Link
            key={a.href}
            href={a.href}
            className={cn(
              "flex items-center gap-2 rounded-lg border p-3 text-sm font-medium transition-colors",
              // Billing is the job; on a phone it gets the full width and the
              // filled treatment so it cannot be missed.
              a.primary
                ? "col-span-2 justify-center border-primary bg-primary py-4 text-base text-primary-foreground sm:col-span-1 sm:py-3 sm:text-sm lg:col-span-1"
                : "border-border bg-card",
            )}
          >
            <a.icon className={cn("h-4 w-4 shrink-0", a.primary && "h-5 w-5 sm:h-4 sm:w-4")} aria-hidden />
            {a.label}
          </Link>
        ))}
      </div>

      {/* one filter row above the figures */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="no-min-target flex flex-wrap gap-1.5" role="group" aria-label="Date range">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPreset(p.value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium",
                preset === p.value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        {preset === "custom" && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="bd-from" className="text-xs">From</Label>
              <Input id="bd-from" type="date" className="h-8 w-40" value={from}
                onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="bd-to" className="text-xs">To</Label>
              <Input id="bd-to" type="date" className="h-8 w-40" value={to}
                onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
        )}
      </div>

      {summary.error ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load business figures:{" "}
          {summary.error instanceof ApiError ? summary.error.message : "unknown error"}
        </p>
      ) : !d ? (
        <Skeleton className="h-32 w-full" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
            <Tile label="Net sales (ex tax)" value={pkr(d.sales.net_sales)}
              href={`/invoices?range=${range}`}
              hint={`${d.sales.invoice_count} invoices · avg ${pkr(d.sales.average_invoice_value)}`} />
            <Tile label="Payments collected" value={pkr(d.cash.collected)}
              href="/payments" tone="good"
              hint="Cash in, not the same as invoiced" />
            <Tile label="Outstanding" value={pkr(d.cash.outstanding)}
              href="/receivables" hint={`${d.cash.open_invoices} open invoices`} />
            <Tile label="Overdue" value={pkr(d.cash.overdue)} href="/receivables"
              tone={Number(d.cash.overdue) > 0 ? "bad" : "default"}
              hint="Past the due date" />

            <Tile label="Gross profit" value={pkr(d.profit.gross_profit)}
              href={`/invoices?range=${range}`}
              tone={d.profit.cost_complete ? "good" : "default"}
              hint={
                d.profit.gross_margin_percent
                  ? `${d.profit.gross_margin_percent}% margin`
                  : "No costed sales yet"
              } />
            <Tile label="Cost of goods sold" value={pkr(d.profit.cogs)}
              href={`/invoices?range=${range}`}
              hint={`${d.profit.cost_coverage_percent ?? "0"}% of sales have cost data`} />
            <Tile label="Inventory value" value={pkr(d.inventory.value)}
              href="/inventory"
              hint={
                d.inventory.uncosted_lines > 0
                  ? `${d.inventory.uncosted_lines} lines have no cost`
                  : "At weighted average cost"
              } />
            <Tile label="Low stock" value={String(d.inventory.low_stock_count)}
              href="/inventory?tab=low-stock"
              tone={d.inventory.low_stock_count > 0 ? "bad" : "default"}
              hint="At or below reorder level" />
          </div>

          {!d.profit.cost_complete && Number(d.profit.sales_missing_cost) > 0 && (
            <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              <span>
                <strong>Profit incomplete.</strong> {pkr(d.profit.sales_missing_cost)} of
                sales have no purchase cost recorded, so they are left out of gross
                profit rather than counted as free margin. Only{" "}
                {d.profit.cost_coverage_percent ?? "0"}% of sales value is fully costed.
              </span>
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-lg border border-border bg-card p-4 lg:col-span-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Sales and gross profit</h3>
                <TrendingUp className="h-4 w-4 text-muted-foreground" aria-hidden />
              </div>
              <div className="mt-3">
                {b ? (
                  <TrendChart points={b.trend} bucket={b.bucket} />
                ) : (
                  <Skeleton className="h-56 w-full" />
                )}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Where sales came from</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Both billing modes feed the same figures.
              </p>
              <dl className="mt-3 space-y-3">
                {[
                  ["From stock", d.sales.from_stock],
                  ["Quick Bill", d.sales.quick_bill],
                  ["Delivery charged", d.sales.delivery_charged],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-baseline justify-between text-sm">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="tabular-nums">{pkrExact(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <RankList
              title="Best-selling products"
              href="/catalogue"
              rows={(b?.top_products ?? []).map((p) => ({
                key: p.product_id, name: p.name, value: p.net_sales,
                sub: `${p.quantity} sold · ${pkr(p.gross_profit)} profit`,
              }))}
            />
            <RankList
              title="Top categories"
              rows={(b?.top_categories ?? []).map((c) => ({
                key: c.name, name: c.name, value: c.net_sales,
              }))}
            />
            <RankList
              title="Top customers"
              href="/customers"
              rows={(b?.top_customers ?? []).map((c) => ({
                key: c.organization_id, name: c.name, value: c.net_sales,
                sub: `${c.invoice_count} invoice${c.invoice_count === 1 ? "" : "s"}`,
              }))}
            />
          </div>

          <div className="rounded-lg border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border p-4">
              <h3 className="text-sm font-semibold">Recent invoices</h3>
              <Link href="/invoices" className="text-xs text-primary hover:underline">
                View all
              </Link>
            </div>
            <ul className="divide-y divide-border">
              {(b?.recent_invoices ?? []).map((inv) => (
                <li key={inv.id}>
                  <Link
                    href={`/invoices/${inv.id}`}
                    className="flex flex-wrap items-center gap-3 p-3 text-sm hover:bg-muted/50"
                  >
                    <span className="font-medium text-primary">{inv.invoice_number}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {inv.customer_name}
                    </span>
                    {inv.is_direct && <Badge variant="outline">Direct</Badge>}
                    <Badge className={cn("border-transparent", PAYMENT_TONE[inv.payment_status])}>
                      {inv.payment_status.replace("_", " ")}
                    </Badge>
                    <span className="tabular-nums">{pkrExact(inv.grand_total)}</span>
                  </Link>
                </li>
              ))}
              {(b?.recent_invoices ?? []).length === 0 && (
                <li className="p-4 text-sm text-muted-foreground">No issued invoices yet.</li>
              )}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
