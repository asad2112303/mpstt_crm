"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Plus, Receipt } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Invoice, InvoiceDerivedStatus } from "@/lib/types/invoices";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export function InvoiceStatusBadge({ status }: { status: InvoiceDerivedStatus }) {
  const styles: Record<InvoiceDerivedStatus, string> = {
    draft: "bg-muted text-muted-foreground",
    issued: "bg-primary/15 text-primary",
    partially_paid: "bg-warning/20 text-warning-foreground",
    paid: "bg-primary text-primary-foreground",
    overdue: "bg-destructive/15 text-destructive",
    cancelled: "bg-destructive/15 text-destructive line-through",
  };
  return (
    <Badge className={cn("border-transparent capitalize", styles[status])}>
      {status.replace("_", " ")}
    </Badge>
  );
}

const FILTERS = ["", "draft", "issued", "cancelled"];

export default function InvoicesPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["invoices", { status, search, page }],
    queryFn: async () =>
      await api<Invoice[]>("/api/v1/invoices", {
        searchParams: {
          status: status || undefined, search: search || undefined,
          page, page_size: 25,
        },
      }),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-4 p-4 sm:space-y-6 sm:p-6">
      <PageHeader
        title="Invoices"
        description="What is owed. Delivery and POD are recorded separately — an invoice never proves delivery."
        actions={
          <Button render={<Link href="/create-bill" />}>
            <Plus className="mr-1.5 h-4 w-4" aria-hidden /> Create bill
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search invoice number or organization…"
          className="w-full sm:w-72" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search invoices" />
        <div className="no-min-target flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
          {FILTERS.map((s) => (
            <button key={s || "all"}
              onClick={() => { setStatus(s); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium capitalize",
                status === s
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}>
              {s === "" ? "All" : s}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load invoices: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Receipt className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            No invoices. Create one from a confirmed order.
          </p>
        </div>
      ) : (
        <>
          {/* Phones get cards: a six-column table cannot be read at 320px
              without sideways scrolling, and the important figures are the
              amount and whether it is paid. */}
          <ul className="space-y-2 lg:hidden">
            {data.data.map((inv) => (
              <li key={inv.id}>
                <Link
                  href={`/invoices/${inv.id}`}
                  className="block rounded-lg border border-border bg-card p-3 active:bg-muted"
                >
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block font-medium text-primary">
                        {inv.invoice_number ?? "(draft)"}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {inv.invoice_date ?? "No date"}
                        {inv.due_date ? ` · due ${inv.due_date}` : ""}
                      </span>
                    </span>
                    <InvoiceStatusBadge status={inv.derived_status} />
                  </span>
                  <span className="mt-2 flex items-end justify-between gap-2">
                    <span className="text-lg font-semibold tabular-nums">
                      {inv.grand_total}
                    </span>
                    {Number(inv.outstanding) > 0 && (
                      <span className="text-xs text-muted-foreground">
                        {inv.outstanding} outstanding
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          <div className="hidden overflow-x-auto rounded-lg border border-border bg-card lg:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Due</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="text-right">Outstanding</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell>
                      <Link href={`/invoices/${inv.id}`}
                        className="font-medium text-primary hover:underline">
                        {inv.invoice_number ?? "(draft)"}
                      </Link>
                    </TableCell>
                    <TableCell>{inv.invoice_date ?? "—"}</TableCell>
                    <TableCell>{inv.due_date ?? "—"}</TableCell>
                    <TableCell className="text-right font-medium">{inv.grand_total}</TableCell>
                    <TableCell className="text-right">{inv.outstanding}</TableCell>
                    <TableCell><InvoiceStatusBadge status={inv.derived_status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
            <span>{total} invoices</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span>Page {page} of {pages}</span>
              <Button variant="outline" size="sm" disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
