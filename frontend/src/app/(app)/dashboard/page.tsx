"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowRight, Banknote, BellRing, ClipboardList,
  FileText, FlaskConical, PackageOpen, Truck,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { STAGE_LABELS, type ProspectStage } from "@/lib/types/crm";
import { useAuth } from "@/lib/auth-context";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface Summary {
  as_of: string;
  operational: {
    followups_due_today: number;
    followups_overdue: number;
    prospects_missing_next_action: number;
    samples_awaiting_feedback: number;
    open_quotations: number;
    orders_to_prepare: number;
    deliveries_open: number;
    missing_pods: number;
    payments_awaiting_allocation: number;
  };
  management?: {
    funnel: Record<string, number>;
    conversion_rate_pct: number;
    quotations_sent_this_month: number;
    confirmed_sales_this_month: string;
    collections_this_month: string;
    outstanding_total: string;
    overdue_total: string;
    aging_buckets: Record<string, string>;
    low_stock_count: number;
    fully_delivered_orders: number;
  };
}

function ActionTile({
  label, value, href, icon: Icon, urgent = false,
}: {
  label: string; value: number; href: string;
  icon: React.ComponentType<{ className?: string }>; urgent?: boolean;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50"
    >
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
        urgent && value > 0 ? "bg-destructive/10 text-destructive" : "bg-secondary text-secondary-foreground"
      }`}>
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-2xl font-semibold leading-tight tabular-nums">
          {value}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{label}</span>
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
    </Link>
  );
}

function MoneyTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xl font-semibold tabular-nums">
        <span className="mr-1 text-xs font-normal text-muted-foreground">PKR</span>
        {Number(value).toLocaleString("en-PK", { minimumFractionDigits: 0 })}
      </p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

const FUNNEL_ORDER: ProspectStage[] = [
  "targeted", "visited", "requirement_collected", "sample_provided",
  "quotation_sent", "negotiation", "won",
];

function Funnel({ funnel }: { funnel: Record<string, number> }) {
  const max = Math.max(1, ...FUNNEL_ORDER.map((s) => funnel[s] ?? 0));
  return (
    <ol className="space-y-2" aria-label="Prospect funnel by stage">
      {FUNNEL_ORDER.map((stage) => {
        const value = funnel[stage] ?? 0;
        return (
          <li key={stage} className="grid grid-cols-[10rem_1fr_2.5rem] items-center gap-2 text-sm">
            <span className="truncate text-muted-foreground">{STAGE_LABELS[stage]}</span>
            <span className="h-4 overflow-hidden rounded-r-[4px] bg-muted" role="presentation">
              <span
                className="block h-full rounded-r-[4px] bg-primary"
                style={{ width: `${(value / max) * 100}%` }}
              />
            </span>
            <span className="text-right font-medium tabular-nums">{value}</span>
          </li>
        );
      })}
    </ol>
  );
}

const AGING_ORDER = ["current", "0-30", "31-60", "61-90", "90+"] as const;
const AGING_LABEL: Record<string, string> = {
  current: "Not yet due", "0-30": "0–30 days", "31-60": "31–60 days",
  "61-90": "61–90 days", "90+": "Over 90 days",
};

export default function DashboardPage() {
  const { me } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => (await api<Summary>("/api/v1/dashboard/summary")).data,
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <main className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </main>
    );
  }
  if (error || !data) {
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">
          Dashboard failed to load: {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      </main>
    );
  }

  const op = data.operational;
  const mgmt = data.management;

  return (
    <main className="space-y-8 p-6">
      <PageHeader
        title={`Welcome${me ? `, ${me.full_name.split(" ")[0]}` : ""}`}
        description={`Today's work — ${data.as_of} (Asia/Karachi)`}
      />

      <section aria-label="Action queues" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Needs attention
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <ActionTile label="Follow-ups overdue" value={op.followups_overdue}
            href="/follow-ups" icon={BellRing} urgent />
          <ActionTile label="Follow-ups due today" value={op.followups_due_today}
            href="/follow-ups" icon={BellRing} />
          <ActionTile label="Prospects with no next action" value={op.prospects_missing_next_action}
            href="/follow-ups" icon={AlertTriangle} urgent />
          <ActionTile label="Samples awaiting feedback" value={op.samples_awaiting_feedback}
            href="/prospects" icon={FlaskConical} />
          <ActionTile label="Open quotations" value={op.open_quotations}
            href="/quotations" icon={FileText} />
          <ActionTile label="Orders to prepare" value={op.orders_to_prepare}
            href="/orders" icon={ClipboardList} />
          <ActionTile label="Open deliveries" value={op.deliveries_open}
            href="/deliveries" icon={Truck} />
          <ActionTile label="Missing PODs" value={op.missing_pods}
            href="/deliveries" icon={AlertTriangle} urgent />
          <ActionTile label="Payments to allocate" value={op.payments_awaiting_allocation}
            href="/payments" icon={Banknote} />
        </div>
      </section>

      {mgmt && (
        <section aria-label="Management indicators" className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Management — this month
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MoneyTile label="Confirmed sales" value={mgmt.confirmed_sales_this_month} />
            <MoneyTile label="Collections" value={mgmt.collections_this_month} />
            <MoneyTile label="Outstanding (all)" value={mgmt.outstanding_total} />
            <MoneyTile label="Overdue (all)" value={mgmt.overdue_total} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Prospect funnel · conversion {mgmt.conversion_rate_pct}%
                </CardTitle>
              </CardHeader>
              <CardContent><Funnel funnel={mgmt.funnel} /></CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="text-base">Receivables aging</CardTitle></CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm" aria-label="Aging buckets">
                  {AGING_ORDER.map((bucket) => {
                    const amount = Number(mgmt.aging_buckets[bucket] ?? 0);
                    const severe = bucket === "61-90" || bucket === "90+";
                    return (
                      <li key={bucket} className="flex items-center justify-between border-b border-border pb-1 last:border-0">
                        <span className="flex items-center gap-2">
                          {severe && amount > 0 && (
                            <AlertTriangle className="h-3.5 w-3.5 text-destructive" aria-hidden />
                          )}
                          {AGING_LABEL[bucket]}
                        </span>
                        <span className={`font-medium tabular-nums ${severe && amount > 0 ? "text-destructive" : ""}`}>
                          PKR {amount.toLocaleString("en-PK")}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                  <Link className="text-primary underline" href="/receivables">
                    Open receivables
                  </Link>
                  <span className="flex items-center gap-1">
                    <PackageOpen className="h-3.5 w-3.5" aria-hidden />
                    {mgmt.low_stock_count} low-stock items ·{" "}
                    <Link className="text-primary underline" href="/inventory">inventory</Link>
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>
          <p className="text-xs text-muted-foreground">
            Definitions: docs/kpi-definitions.md. Cancelled and reversed records
            are never counted.
          </p>
        </section>
      )}
    </main>
  );
}
