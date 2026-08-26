"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileText, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Organization } from "@/lib/types/crm";
import type { Quote } from "@/lib/types/quotes";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export function QuoteStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-muted text-muted-foreground",
    sent: "bg-primary/15 text-primary",
    accepted: "bg-primary text-primary-foreground",
    rejected: "bg-destructive/15 text-destructive",
    expired: "bg-warning/20 text-warning-foreground",
    superseded: "bg-muted text-muted-foreground line-through",
    converted: "bg-chart-2/30 text-primary",
    cancelled: "bg-destructive/15 text-destructive",
  };
  return (
    <Badge className={cn("border-transparent capitalize", styles[status] ?? "")}>
      {status}
    </Badge>
  );
}

function NewQuoteDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");

  const { data: prospects } = useQuery({
    queryKey: ["prospects", { search: q }],
    queryFn: async () =>
      (await api<Organization[]>("/api/v1/prospects", {
        searchParams: { search: q || undefined, page_size: 8 },
      })).data,
    enabled: open,
  });
  const { data: customers } = useQuery({
    queryKey: ["customers", { search: q }],
    queryFn: async () =>
      (await api<Organization[]>("/api/v1/customers", {
        searchParams: { search: q || undefined, page_size: 8 },
      })).data,
    enabled: open,
  });

  const create = useMutation({
    mutationFn: (organizationId: string) =>
      api<Quote>("/api/v1/quotations", {
        method: "POST",
        body: { organization_id: organizationId },
      }),
    onSuccess: (resp) => {
      setOpen(false);
      router.push(`/quotations/${resp.data.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const options = [...(prospects ?? []), ...(customers ?? [])];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> New quotation
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>New quotation — choose organization</DialogTitle></DialogHeader>
        <Input autoFocus placeholder="Search prospects and customers…" value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Search organizations" />
        <ul className="max-h-72 space-y-1 overflow-auto">
          {options.map((o) => (
            <li key={o.id}>
              <button
                className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                disabled={create.isPending}
                onClick={() => create.mutate(o.id)}
              >
                <span className="font-medium">{o.name}</span>{" "}
                <span className="text-xs text-muted-foreground">
                  {o.org_code} · {o.lifecycle_status}{o.city ? ` · ${o.city}` : ""}
                </span>
              </button>
            </li>
          ))}
          {options.length === 0 && (
            <li className="px-3 py-4 text-sm text-muted-foreground">No organizations found.</li>
          )}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

const STATUS_FILTERS = ["", "draft", "sent", "accepted", "rejected", "converted", "superseded"];

export default function QuotationsPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["quotations", { status, search, page }],
    queryFn: async () =>
      await api<Quote[]>("/api/v1/quotations", {
        searchParams: {
          status: status || undefined, search: search || undefined,
          page, page_size: 25,
        },
      }),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Quotations"
        description="Sent quotations are immutable snapshots — revisions carry changes."
        actions={<NewQuoteDialog />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search number or organization…" className="w-72" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search quotations" />
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {STATUS_FILTERS.map((s) => (
            <button key={s || "all"}
              onClick={() => { setStatus(s); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium capitalize",
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
          Failed to load quotations: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <FileText className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No quotations match.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Number</TableHead>
                  <TableHead>Rev</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Valid until</TableHead>
                  <TableHead className="text-right">Total (PKR)</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((quote) => (
                  <TableRow key={quote.id}>
                    <TableCell>
                      <Link href={`/quotations/${quote.id}`}
                        className="font-medium text-primary hover:underline">
                        {quote.quotation_number}
                      </Link>
                    </TableCell>
                    <TableCell>{quote.revision_no}</TableCell>
                    <TableCell>{quote.quote_date}</TableCell>
                    <TableCell>{quote.valid_until ?? "—"}</TableCell>
                    <TableCell className="text-right font-medium">{quote.grand_total}</TableCell>
                    <TableCell><QuoteStatusBadge status={quote.effective_status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} quotations</span>
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
