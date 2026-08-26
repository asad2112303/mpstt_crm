"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const REPORTS = [
  { key: "pipeline", label: "Pipeline", dated: false, finance: false },
  { key: "sales", label: "Sales", dated: true, finance: true },
  { key: "collections", label: "Collections", dated: true, finance: true },
  { key: "receivables", label: "Receivables", dated: false, finance: true },
  { key: "deliveries", label: "Delivery exceptions", dated: false, finance: false },
  { key: "inventory", label: "Inventory", dated: false, finance: false },
] as const;

type ReportKey = (typeof REPORTS)[number]["key"];

export default function ReportsPage() {
  const [report, setReport] = useState<ReportKey>("pipeline");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const meta = REPORTS.find((r) => r.key === report)!;

  const { data, isLoading, error } = useQuery({
    queryKey: ["reports", report, dateFrom, dateTo],
    queryFn: async () =>
      (
        await api<{ rows: Record<string, unknown>[]; filters: Record<string, string> }>(
          `/api/v1/reports/${report}`,
          {
            searchParams: {
              date_from: meta.dated ? dateFrom || undefined : undefined,
              date_to: meta.dated ? dateTo || undefined : undefined,
            },
          },
        )
      ).data,
  });

  async function exportCsv() {
    let headers: Record<string, string> = {};
    if (supabaseConfigured()) {
      const { data: { session } } = await createClient().auth.getSession();
      if (session) headers = { Authorization: `Bearer ${session.access_token}` };
    }
    const url = new URL(`${API_BASE}/api/v1/reports/${report}`);
    url.searchParams.set("format", "csv");
    if (meta.dated && dateFrom) url.searchParams.set("date_from", dateFrom);
    if (meta.dated && dateTo) url.searchParams.set("date_to", dateTo);
    const resp = await fetch(url.toString(), { headers });
    if (!resp.ok) { toast.error("Export failed"); return; }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${report}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
    if (meta.finance) toast.info("Finance export recorded in the audit log");
  }

  const rows = data?.rows ?? [];
  const columns = rows.length ? Object.keys(rows[0]) : [];

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Reports"
        description="Reconciled to source records. Cancelled/reversed are excluded. Finance exports are audited."
        actions={
          <Button variant="outline" onClick={() => void exportCsv()} disabled={!rows.length}>
            <Download className="mr-1 h-4 w-4" aria-hidden /> Export CSV
          </Button>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Report">
          {REPORTS.map((r) => (
            <button key={r.key}
              onClick={() => setReport(r.key)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium",
                report === r.key
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}>
              {r.label}
            </button>
          ))}
        </div>
        {meta.dated && (
          <>
            <div className="space-y-1">
              <Label htmlFor="rp-from" className="text-xs">From</Label>
              <Input id="rp-from" type="date" className="h-8 w-36" value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="rp-to" className="text-xs">To</Label>
              <Input id="rp-to" type="date" className="h-8 w-36" value={dateTo}
                onChange={(e) => setDateTo(e.target.value)} />
            </div>
          </>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          {error instanceof ApiError && error.status === 403
            ? "You do not have permission to view this report."
            : "Report failed to load."}
        </p>
      ) : !rows.length ? (
        <p className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          No rows for this report and range.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((c) => (
                  <TableHead key={c} className="capitalize">{c.replaceAll("_", " ")}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, i) => (
                <TableRow key={i}>
                  {columns.map((c) => (
                    <TableCell key={c} className="text-sm">
                      {String(row[c] ?? "—")}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  );
}
