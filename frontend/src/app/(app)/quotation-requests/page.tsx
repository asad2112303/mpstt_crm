"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Mail, Phone } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { formatKarachi } from "@/lib/types/crm";
import {
  QUOTATION_REQUEST_STATUSES,
  QUOTATION_REQUEST_STATUS_LABELS,
  type QuotationRequest,
  type QuotationRequestStatus,
  type QuotationRequestSummary,
} from "@/lib/types/website";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

const STATUS_STYLES: Record<QuotationRequestStatus, string> = {
  new: "bg-primary text-primary-foreground",
  contacted: "bg-primary/15 text-primary",
  quotation_preparing: "bg-warning/20 text-warning-foreground",
  quotation_sent: "bg-chart-2/30 text-primary",
  won: "bg-primary text-primary-foreground",
  lost: "bg-destructive/15 text-destructive",
  closed: "bg-muted text-muted-foreground",
};

export function RequestStatusBadge({ status }: { status: QuotationRequestStatus }) {
  return (
    <Badge className={cn("border-transparent", STATUS_STYLES[status] ?? "")}>
      {QUOTATION_REQUEST_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

/** "All" and "Open" are server-side filters too — "open" means not won/lost/closed. */
type FilterValue = "" | "open" | QuotationRequestStatus;

const FILTERS: { value: FilterValue; label: string }[] = [
  { value: "", label: "All" },
  { value: "open", label: "Open" },
  ...QUOTATION_REQUEST_STATUSES.map((s) => ({
    value: s as FilterValue,
    label: QUOTATION_REQUEST_STATUS_LABELS[s],
  })),
];

function DetailField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm break-words">{children}</dd>
    </div>
  );
}

/** Mounted fresh per request (keyed by id), so the form seeds straight from props. */
function RequestDetail({
  request,
  onClose,
}: {
  request: QuotationRequest;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<QuotationRequestStatus>(request.status);
  const [notes, setNotes] = useState(request.internal_notes ?? "");

  const save = useMutation({
    mutationFn: () =>
      api<QuotationRequest>(`/api/v1/quotation-requests/${request.id}`, {
        method: "PATCH",
        body: { status, internal_notes: notes.trim() || null },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["quotation-requests"] });
      toast.success("Request updated.");
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not update the request."),
  });

  const dirty =
    status !== request.status || notes.trim() !== (request.internal_notes ?? "");

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {request.reference}
          <span className="ml-2 align-middle">
            <RequestStatusBadge status={request.status} />
          </span>
        </DialogTitle>
        <DialogDescription>
          Received {formatKarachi(request.created_at)} from the website form.
        </DialogDescription>
      </DialogHeader>

      <dl className="grid gap-4 sm:grid-cols-2">
        <DetailField label="Name">{request.full_name}</DetailField>
        <DetailField label="Organization">
          {request.organization}
          {request.organization_type ? ` · ${request.organization_type}` : ""}
        </DetailField>
        <DetailField label="Phone">
          <a className="text-primary hover:underline" href={`tel:${request.phone}`}>
            {request.phone}
          </a>
        </DetailField>
        <DetailField label="Email">
          {request.email ? (
            <a className="text-primary hover:underline" href={`mailto:${request.email}`}>
              {request.email}
            </a>
          ) : (
            "—"
          )}
        </DetailField>
      </dl>

      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Requirement
        </p>
        <p className="mt-1 whitespace-pre-wrap rounded-lg border border-border bg-muted/40 p-3 text-sm">
          {request.requirement}
        </p>
      </div>

      <dl className="grid gap-4 sm:grid-cols-2">
        <DetailField label="Product of interest">
          {request.product_name ?? "—"}
          {request.product_slug && (
            <span className="block text-xs text-muted-foreground">
              {request.category_slug ? `${request.category_slug} / ` : ""}
              {request.product_slug}
            </span>
          )}
        </DetailField>
        <DetailField label="Intent">{request.intent ?? "—"}</DetailField>
        <DetailField label="Source page">
          <span className="text-xs text-muted-foreground">{request.source_page ?? "—"}</span>
        </DetailField>
        <DetailField label="Consent">
          {request.consent ? `Given ${formatKarachi(request.consent_at)}` : "Not given"}
        </DetailField>
        <DetailField label="First contacted">{formatKarachi(request.contacted_at)}</DetailField>
        <DetailField label="Last updated">{formatKarachi(request.updated_at)}</DetailField>
      </dl>

      <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-[200px_1fr]">
        <div className="space-y-1.5">
          <Label htmlFor="request-status">Status</Label>
          <Select
            value={status}
            onValueChange={(v) => v && setStatus(v as QuotationRequestStatus)}
          >
            <SelectTrigger id="request-status" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {QUOTATION_REQUEST_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {QUOTATION_REQUEST_STATUS_LABELS[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="request-notes">Internal notes</Label>
          <Textarea
            id="request-notes"
            value={notes}
            placeholder="Visible to the CRM team only — never shown on the website."
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </>
  );
}

function RequestDialog({
  request,
  onClose,
}: {
  request: QuotationRequest | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={request != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {request && <RequestDetail key={request.id} request={request} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

export default function QuotationRequestsPage() {
  const [filter, setFilter] = useState<FilterValue>("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<QuotationRequest | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["quotation-requests", { filter, search, page }],
    queryFn: async () =>
      await api<QuotationRequest[]>("/api/v1/quotation-requests", {
        searchParams: {
          status: filter || undefined,
          search: search || undefined,
          page,
          page_size: PAGE_SIZE,
        },
      }),
    // New enquiries arrive without anyone reloading the page.
    refetchInterval: 60_000,
  });

  const { data: summary } = useQuery({
    queryKey: ["quotation-requests", "summary"],
    queryFn: async () =>
      (await api<QuotationRequestSummary>("/api/v1/quotation-requests/summary")).data,
    refetchInterval: 60_000,
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function countFor(value: FilterValue): number | undefined {
    if (!summary) return undefined;
    if (value === "") return summary.total;
    if (value === "open") return summary.open_count;
    return summary.by_status[value];
  }

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Quotation requests"
        description="Enquiries submitted on the website land here — work them from new to won."
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search reference, name, organization, phone…"
          className="w-80"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          aria-label="Search quotation requests"
        />
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => {
            const count = countFor(f.value);
            return (
              <button
                key={f.value || "all"}
                onClick={() => {
                  setFilter(f.value);
                  setPage(1);
                }}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium",
                  filter === f.value
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card hover:bg-muted",
                )}
              >
                {f.label}
                {count !== undefined && (
                  <span className="ml-1.5 opacity-70">{count}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load quotation requests:{" "}
          {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Inbox className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            {search || filter
              ? "No requests match this filter."
              : "No website enquiries yet. New submissions appear here automatically."}
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Reference</TableHead>
                  <TableHead>Received</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead>Interested in</TableHead>
                  <TableHead>Requirement</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <button
                        className="font-medium text-primary hover:underline"
                        onClick={() => setSelected(r)}
                      >
                        {r.reference}
                      </button>
                    </TableCell>
                    <TableCell className="text-sm whitespace-nowrap">
                      {formatKarachi(r.created_at)}
                    </TableCell>
                    <TableCell>
                      <p className="text-sm font-medium">{r.organization}</p>
                      <p className="text-xs text-muted-foreground">
                        {r.full_name}
                        {r.organization_type ? ` · ${r.organization_type}` : ""}
                      </p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <Phone className="h-3 w-3" aria-hidden />
                          {r.phone}
                        </span>
                        {r.email && (
                          <span className="inline-flex items-center gap-1">
                            <Mail className="h-3 w-3" aria-hidden />
                            {r.email}
                          </span>
                        )}
                      </p>
                    </TableCell>
                    <TableCell className="text-sm">{r.product_name ?? "—"}</TableCell>
                    <TableCell className="max-w-72 truncate text-sm text-muted-foreground">
                      {r.requirement}
                    </TableCell>
                    <TableCell>
                      <RequestStatusBadge status={r.status} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} requests</span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span>
                Page {page} of {pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      <RequestDialog request={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
