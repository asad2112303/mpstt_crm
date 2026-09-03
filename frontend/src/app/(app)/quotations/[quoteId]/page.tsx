"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileDown, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { API_BASE, api, ApiError, newIdempotencyKey } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import type { Organization } from "@/lib/types/crm";
import type { Quote } from "@/lib/types/quotes";
import type { SearchHit } from "@/lib/types/catalogue";
import { QuoteStatusBadge } from "../page";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";


async function openPdf(quoteId: string) {
  let headers: Record<string, string> = {};
  if (supabaseConfigured()) {
    const { data: { session } } = await createClient().auth.getSession();
    if (session) headers = { Authorization: `Bearer ${session.access_token}` };
  }
  const resp = await fetch(`${API_BASE}/api/v1/quotations/${quoteId}/pdf`, { headers });
  if (!resp.ok) {
    toast.error("Could not load the PDF");
    return;
  }
  const blob = await resp.blob();
  window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

function VariantSearch({ onPick }: { onPick: (hit: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["catalogue", "search", q],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q } })).data,
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <Input value={q} placeholder="Add item: search product / variant…"
        aria-label="Search catalogue" onChange={(e) => setQ(e.target.value)} />
      {q.length >= 2 && data && (
        <ul className="absolute z-30 mt-1 max-h-48 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
          {data.map((h) => (
            <li key={`${h.product_id}-${h.variant_id}`}>
              <button type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => { onPick(h); setQ(""); }}>
                {h.label} <span className="text-xs text-muted-foreground">({h.sku})</span>
              </button>
            </li>
          ))}
          {data.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">No matches</li>
          )}
        </ul>
      )}
    </div>
  );
}

interface LineDraft {
  product_variant_id: string;
  label: string;
  quantity: string;
  unit_price: string;
  discount_percent: string;
}

function DraftEditor({ quote }: { quote: Quote }) {
  const queryClient = useQueryClient();
  const [lines, setLines] = useState<LineDraft[]>(
    quote.items.map((i) => ({
      product_variant_id: i.product_variant_id,
      label: i.description_snapshot,
      quantity: i.quantity,
      unit_price: i.unit_price,
      discount_percent: i.discount_percent,
    })),
  );
  const [validUntil, setValidUntil] = useState(quote.valid_until ?? "");
  const [terms, setTerms] = useState(quote.terms ?? "");
  const [notes, setNotes] = useState(quote.notes ?? "");

  const save = useMutation({
    mutationFn: () =>
      api(`/api/v1/quotations/${quote.id}`, {
        method: "PUT",
        body: {
          valid_until: validUntil || null,
          terms: terms || null,
          notes: notes || null,
          items: lines.map((l) => ({
            product_variant_id: l.product_variant_id,
            quantity: l.quantity,
            unit_price: l.unit_price,
            discount_percent: l.discount_percent || "0",
          })),
        },
      }),
    onSuccess: () => {
      toast.success("Draft saved");
      queryClient.invalidateQueries({ queryKey: ["quotations"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Save failed"),
  });

  const valid = lines.length > 0 &&
    lines.every((l) => Number(l.quantity) > 0 && Number(l.unit_price) >= 0);

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Draft items &amp; terms</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <VariantSearch
          onPick={(hit) =>
            setLines((prev) => [
              ...prev,
              { product_variant_id: hit.variant_id!, label: hit.label,
                quantity: "1", unit_price: "", discount_percent: "0" },
            ])
          }
        />
        {lines.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead className="w-24">Qty</TableHead>
                  <TableHead className="w-28">Rate</TableHead>
                  <TableHead className="w-24">Disc %</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((l, i) => (
                  <TableRow key={`${l.product_variant_id}-${i}`}>
                    <TableCell className="text-sm">{l.label}</TableCell>
                    <TableCell>
                      <Input type="number" min="0.001" step="any" value={l.quantity}
                        aria-label="Quantity"
                        onChange={(e) => setLines((p) =>
                          p.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} />
                    </TableCell>
                    <TableCell>
                      <Input type="number" min="0" step="0.01" value={l.unit_price}
                        aria-label="Unit price"
                        onChange={(e) => setLines((p) =>
                          p.map((x, j) => j === i ? { ...x, unit_price: e.target.value } : x))} />
                    </TableCell>
                    <TableCell>
                      <Input type="number" min="0" max="100" step="0.01" value={l.discount_percent}
                        aria-label="Discount"
                        onChange={(e) => setLines((p) =>
                          p.map((x, j) => j === i ? { ...x, discount_percent: e.target.value } : x))} />
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon-sm" aria-label="Remove line"
                        onClick={() => setLines((p) => p.filter((_, j) => j !== i))}>
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="q-valid">Valid until</Label>
            <Input id="q-valid" type="date" value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="q-notes">Notes</Label>
            <Input id="q-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          <div className="space-y-1.5 sm:col-span-3">
            <Label htmlFor="q-terms">Terms (blank = company default)</Label>
            <Textarea id="q-terms" rows={3} value={terms}
              onChange={(e) => setTerms(e.target.value)} />
          </div>
        </div>
        <Button onClick={() => save.mutate()} disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : "Save draft"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function QuoteDetailPage({
  params,
}: {
  params: Promise<{ quoteId: string }>;
}) {
  const { quoteId } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: quote, isLoading, error } = useQuery({
    queryKey: ["quotations", quoteId],
    queryFn: async () => (await api<Quote>(`/api/v1/quotations/${quoteId}`)).data,
  });
  const { data: org } = useQuery({
    queryKey: ["org-any", quote?.organization_id],
    queryFn: async () =>
      (await api<Organization>(`/api/v1/prospects/${quote!.organization_id}`)).data,
    enabled: Boolean(quote),
  });
  const { data: revisions } = useQuery({
    queryKey: ["quotations", quoteId, "revisions"],
    queryFn: async () =>
      (await api<Quote[]>(`/api/v1/quotations/${quoteId}/revisions`)).data,
    enabled: Boolean(quote),
  });

  const act = useMutation({
    mutationFn: ({ action, body, idem }: { action: string; body?: unknown; idem?: boolean }) =>
      api<Quote | { order: { id: string; order_number: string } }>(
        `/api/v1/quotations/${quoteId}/${action}`,
        {
          method: "POST",
          body,
          idempotencyKey: idem ? newIdempotencyKey() : undefined,
        },
      ),
    onSuccess: (resp, vars) => {
      queryClient.invalidateQueries({ queryKey: ["quotations"] });
      if (vars.action === "revise") {
        const revision = resp.data as Quote;
        router.push(`/quotations/${revision.id}`);
        return;
      }
      if (vars.action === "convert-to-order") {
        const data = resp.data as { order: { order_number: string } };
        toast.success(`Order ${data.order.order_number} created`);
        queryClient.invalidateQueries();
        return;
      }
      toast.success("Done");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Action failed"),
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !quote)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Quotation not found.</p>
      </main>
    );

  const s = quote.effective_status;

  return (
    <main className="space-y-6 p-6">
      <Link href="/quotations"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Quotations
      </Link>
      <PageHeader
        title={`${quote.quotation_number}${quote.revision_no > 1 ? ` · Rev ${quote.revision_no}` : ""}`}
        description={org ? `${org.name} · ${org.city ?? ""}` : undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <QuoteStatusBadge status={s} />
            <Button variant="outline" size="sm" onClick={() => void openPdf(quote.id)}>
              <FileDown className="mr-1 h-4 w-4" aria-hidden />
              {quote.pdf_document_id ? "PDF" : "Preview PDF"}
            </Button>
            {s === "draft" && (
              <Button size="sm" disabled={act.isPending || quote.items.length === 0}
                onClick={() => {
                  if (window.confirm("Send this quotation? It becomes an immutable snapshot."))
                    act.mutate({ action: "send", idem: true });
                }}>
                <Send className="mr-1 h-4 w-4" aria-hidden /> Send
              </Button>
            )}
            {(s === "sent" || s === "expired") && (
              <>
                <Button size="sm" variant="outline" disabled={act.isPending}
                  onClick={() => act.mutate({ action: "revise" })}>
                  Revise
                </Button>
                {s === "sent" && (
                  <Button size="sm" disabled={act.isPending}
                    onClick={() => act.mutate({ action: "accept" })}>
                    Mark accepted
                  </Button>
                )}
                <Button size="sm" variant="destructive" disabled={act.isPending}
                  onClick={() => {
                    const reason = window.prompt("Rejection reason (required):");
                    if (reason) act.mutate({ action: "reject", body: { reason } });
                  }}>
                  Mark rejected
                </Button>
              </>
            )}
            {s === "accepted" && (
              <Button size="sm" disabled={act.isPending}
                onClick={() => {
                  if (window.confirm(
                    "Convert to order? A prospect becomes a Customer in the same step.",
                  ))
                    act.mutate({ action: "convert-to-order", idem: true });
                }}>
                Convert to order
              </Button>
            )}
          </div>
        }
      />

      {s === "draft" ? (
        <DraftEditor key={quote.items.map((i) => i.id).join(",")} quote={quote} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Frozen items {quote.sent_at && `· sent ${new Date(quote.sent_at).toLocaleDateString("en-PK")}`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>UOM</TableHead>
                    <TableHead className="text-right">Rate</TableHead>
                    <TableHead className="text-right">Disc %</TableHead>
                    <TableHead className="text-right">Tax %</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {quote.items.map((i) => (
                    <TableRow key={i.id}>
                      <TableCell>{i.sort_order + 1}</TableCell>
                      <TableCell className="text-sm">{i.description_snapshot}</TableCell>
                      <TableCell className="text-right">{i.quantity}</TableCell>
                      <TableCell>{i.uom_code}</TableCell>
                      <TableCell className="text-right">{i.unit_price}</TableCell>
                      <TableCell className="text-right">{i.discount_percent}</TableCell>
                      <TableCell className="text-right">{i.tax_rate}</TableCell>
                      <TableCell className="text-right font-medium">{i.line_total}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Totals (server-calculated)</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p className="flex justify-between"><span>Subtotal</span><span>{quote.subtotal}</span></p>
            <p className="flex justify-between"><span>Discount</span><span>-{quote.discount_total}</span></p>
            <p className="flex justify-between"><span>Tax</span><span>{quote.tax_total}</span></p>
            <p className="flex justify-between border-t border-border pt-1 font-semibold text-primary">
              <span>Grand total (PKR)</span><span>{quote.grand_total}</span>
            </p>
            {quote.rejected_reason && (
              <p className="pt-2 text-destructive">Rejected: {quote.rejected_reason}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Revision history</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {(revisions ?? []).map((r) => (
                <li key={r.id} className="flex items-center justify-between">
                  <Link href={`/quotations/${r.id}`}
                    className={r.id === quote.id ? "font-semibold" : "text-primary hover:underline"}>
                    Rev {r.revision_no} — {r.grand_total} PKR
                  </Link>
                  <QuoteStatusBadge status={r.effective_status} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
