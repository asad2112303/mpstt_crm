"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { Organization } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

interface AgingRow {
  invoice_id: string;
  invoice_number: string;
  organization_id: string;
  organization_name: string;
  invoice_date: string | null;
  due_date: string | null;
  grand_total: string;
  allocated: string;
  outstanding: string;
  derived_status: string;
  days_overdue: number;
  bucket: "current" | "0-30" | "31-60" | "61-90" | "90+";
}

interface StatementRow {
  date: string; kind: string; reference: string;
  debit: string; credit: string; balance: string;
}

const BUCKETS = ["", "current", "0-30", "31-60", "61-90", "90+"] as const;

function AgingTab() {
  const [bucket, setBucket] = useState("");
  const { data, isLoading, error } = useQuery({
    queryKey: ["receivables", { bucket }],
    queryFn: async () =>
      (await api<{ rows: AgingRow[]; totals: { outstanding_total: string; count: number } }>(
        "/api/v1/receivables",
        { searchParams: { bucket: bucket || undefined } },
      )).data,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Aging bucket">
          {BUCKETS.map((b) => (
            <button key={b || "all"}
              onClick={() => setBucket(b)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium",
                bucket === b
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}>
              {b === "" ? "All open" : b === "current" ? "Not yet due" : `${b} days`}
            </button>
          ))}
        </div>
        {data && (
          <span className="ml-auto text-sm font-medium">
            Outstanding: PKR {data.totals.outstanding_total} · {data.totals.count} invoices
          </span>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.rows.length ? (
        <p className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Nothing outstanding in this bucket.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Due</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Paid</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
                <TableHead>Overdue</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.invoice_id}>
                  <TableCell>
                    <Link href={`/invoices/${r.invoice_id}`}
                      className="font-medium text-primary hover:underline">
                      {r.invoice_number}
                    </Link>
                  </TableCell>
                  <TableCell className="text-sm">{r.organization_name}</TableCell>
                  <TableCell>{r.due_date ?? "—"}</TableCell>
                  <TableCell className="text-right">{r.grand_total}</TableCell>
                  <TableCell className="text-right">{r.allocated}</TableCell>
                  <TableCell className="text-right font-medium">{r.outstanding}</TableCell>
                  <TableCell>
                    {r.days_overdue > 0 ? (
                      <Badge variant="destructive">{r.days_overdue}d ({r.bucket})</Badge>
                    ) : (
                      <Badge variant="outline">Current</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function StatementTab() {
  const [orgQ, setOrgQ] = useState("");
  const [org, setOrg] = useState<Organization | null>(null);

  const { data: customers } = useQuery({
    queryKey: ["customers", { search: orgQ }],
    queryFn: async () =>
      (await api<Organization[]>("/api/v1/customers", {
        searchParams: { search: orgQ || undefined, page_size: 8 },
      })).data,
    enabled: !org && orgQ.length >= 1,
  });
  const { data: statement, isLoading } = useQuery({
    queryKey: ["statement", org?.id],
    queryFn: async () =>
      (await api<{ rows: StatementRow[]; closing_balance: string }>(
        `/api/v1/customers/${org!.id}/statement`,
      )).data,
    enabled: Boolean(org),
  });

  return (
    <div className="space-y-4">
      {!org ? (
        <div className="max-w-md space-y-2">
          <Input placeholder="Search customer for statement…" value={orgQ}
            onChange={(e) => setOrgQ(e.target.value)} aria-label="Search customers" />
          <ul className="space-y-1">
            {(customers ?? []).map((c) => (
              <li key={c.id}>
                <button className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => setOrg(c)}>
                  {c.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <div className="flex items-center justify-between">
            <p className="font-medium">{org.name}</p>
            <button className="text-sm text-primary underline" onClick={() => setOrg(null)}>
              Change customer
            </button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead className="text-right">Debit</TableHead>
                  <TableHead className="text-right">Credit</TableHead>
                  <TableHead className="text-right">Balance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(statement?.rows ?? []).map((r, i) => (
                  <TableRow key={`${r.reference}-${i}`}>
                    <TableCell>{r.date}</TableCell>
                    <TableCell className="capitalize">{r.kind}</TableCell>
                    <TableCell className="font-mono text-xs">{r.reference}</TableCell>
                    <TableCell className="text-right">{Number(r.debit) > 0 ? r.debit : ""}</TableCell>
                    <TableCell className="text-right">{Number(r.credit) > 0 ? r.credit : ""}</TableCell>
                    <TableCell className="text-right font-medium">{r.balance}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="text-right text-sm font-semibold">
            Closing balance: PKR {statement?.closing_balance}
          </p>
        </>
      )}
    </div>
  );
}

export default function ReceivablesPage() {
  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Receivables"
        description="Open invoices, aging buckets, and customer statements. Reversed payments are excluded."
      />
      <Tabs defaultValue="aging">
        <TabsList>
          <TabsTrigger value="aging">Aging</TabsTrigger>
          <TabsTrigger value="statement">Customer statement</TabsTrigger>
        </TabsList>
        <TabsContent value="aging" className="pt-4"><AgingTab /></TabsContent>
        <TabsContent value="statement" className="pt-4"><StatementTab /></TabsContent>
      </Tabs>
    </main>
  );
}
