"use client";

import { use } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileDown } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import type { Organization } from "@/lib/types/crm";
import type { Invoice } from "@/lib/types/invoices";
import { InvoiceStatusBadge } from "../page";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function openPdf(invoiceId: string) {
  let headers: Record<string, string> = {};
  if (supabaseConfigured()) {
    const { data: { session } } = await createClient().auth.getSession();
    if (session) headers = { Authorization: `Bearer ${session.access_token}` };
  }
  const resp = await fetch(`${API_BASE}/api/v1/invoices/${invoiceId}/pdf`, { headers });
  if (!resp.ok) {
    toast.error("Could not load the PDF");
    return;
  }
  const blob = await resp.blob();
  window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

export default function InvoiceDetailPage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = use(params);
  const queryClient = useQueryClient();

  const { data: invoice, isLoading, error } = useQuery({
    queryKey: ["invoices", invoiceId],
    queryFn: async () => (await api<Invoice>(`/api/v1/invoices/${invoiceId}`)).data,
  });
  const { data: org } = useQuery({
    queryKey: ["customers", invoice?.organization_id],
    queryFn: async () =>
      (await api<Organization>(`/api/v1/customers/${invoice!.organization_id}`)).data,
    enabled: Boolean(invoice),
  });

  const act = useMutation({
    mutationFn: ({ action, body, idem }: { action: string; body?: unknown; idem?: boolean }) =>
      api(`/api/v1/invoices/${invoiceId}/${action}`, {
        method: "POST", body,
        idempotencyKey: idem ? newIdempotencyKey() : undefined,
      }),
    onSuccess: () => {
      toast.success("Done");
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Action failed"),
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !invoice)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Invoice not found.</p>
      </main>
    );

  return (
    <main className="space-y-6 p-6">
      <Link href="/invoices"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Invoices
      </Link>
      <PageHeader
        title={invoice.invoice_number ?? "Draft invoice"}
        description={org ? org.name : undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <InvoiceStatusBadge status={invoice.derived_status} />
            {invoice.pdf_document_id && (
              <Button variant="outline" size="sm" onClick={() => void openPdf(invoice.id)}>
                <FileDown className="mr-1 h-4 w-4" aria-hidden /> PDF
              </Button>
            )}
            {invoice.status === "draft" && (
              <Button size="sm" disabled={act.isPending}
                onClick={() => {
                  if (window.confirm(
                    "Issue this invoice? The number, totals, due date, and PDF become frozen.",
                  ))
                    act.mutate({ action: "issue", idem: true });
                }}>
                Issue invoice
              </Button>
            )}
            {invoice.status !== "cancelled" && Number(invoice.allocated) === 0 && (
              <Button size="sm" variant="destructive" disabled={act.isPending}
                onClick={() => {
                  const reason = window.prompt("Cancellation reason (required):");
                  if (reason) act.mutate({ action: "cancel", body: { reason } });
                }}>
                Cancel
              </Button>
            )}
          </div>
        }
      />

      {invoice.sales_order_id && (
        <Alert>
          <AlertDescription>
            Linked to order{" "}
            <Link className="text-primary underline" href={`/orders/${invoice.sales_order_id}`}>
              view order &amp; delivery status
            </Link>
            . An invoice records what is owed — delivery is evidenced separately by
            challan and POD.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Items (frozen at issue)</CardTitle></CardHeader>
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
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoice.items.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell>{i.sort_order + 1}</TableCell>
                    <TableCell className="text-sm">{i.description_snapshot}</TableCell>
                    <TableCell className="text-right">{i.quantity}</TableCell>
                    <TableCell>{i.uom_code}</TableCell>
                    <TableCell className="text-right">{i.unit_price}</TableCell>
                    <TableCell className="text-right font-medium">{i.line_total}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="mt-3 ml-auto w-full max-w-xs space-y-1 text-sm">
            <p className="flex justify-between"><span>Subtotal</span><span>{invoice.subtotal}</span></p>
            <p className="flex justify-between"><span>Discount</span><span>-{invoice.discount_total}</span></p>
            <p className="flex justify-between"><span>Tax</span><span>{invoice.tax_total}</span></p>
            <p className="flex justify-between border-t border-border pt-1 font-semibold text-primary">
              <span>Total (PKR)</span><span>{invoice.grand_total}</span>
            </p>
            <p className="flex justify-between text-muted-foreground">
              <span>Paid / allocated</span><span>{invoice.allocated}</span>
            </p>
            <p className="flex justify-between font-semibold">
              <span>Outstanding</span><span>{invoice.outstanding}</span>
            </p>
          </div>
          {invoice.due_date && (
            <p className="mt-2 text-sm text-muted-foreground">
              Due {invoice.due_date} · terms {invoice.payment_terms_days} days
            </p>
          )}
          {invoice.cancelled_reason && (
            <p className="mt-2 text-sm text-destructive">Cancelled: {invoice.cancelled_reason}</p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
