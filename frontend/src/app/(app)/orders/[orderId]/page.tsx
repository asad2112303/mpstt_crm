"use client";

import { use } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import type { Organization } from "@/lib/types/crm";
import type { Order } from "@/lib/types/orders";
import { OrderStatusBadge } from "../page";
import { DocumentsPanel } from "@/components/documents-panel";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export default function OrderDetailPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = use(params);
  const queryClient = useQueryClient();

  const { data: order, isLoading, error } = useQuery({
    queryKey: ["orders", orderId],
    queryFn: async () => (await api<Order>(`/api/v1/orders/${orderId}`)).data,
  });
  const { data: org } = useQuery({
    queryKey: ["customers", order?.organization_id],
    queryFn: async () =>
      (await api<Organization>(`/api/v1/customers/${order!.organization_id}`)).data,
    enabled: Boolean(order),
  });

  const createInvoice = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/api/v1/invoices/from-order", {
        method: "POST",
        body: { sales_order_id: orderId },
      }),
    onSuccess: (resp) => {
      toast.success("Draft invoice created");
      window.location.href = `/invoices/${resp.data.id}`;
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const act = useMutation({
    mutationFn: ({ action, body, idem }: { action: string; body?: unknown; idem?: boolean }) =>
      api(`/api/v1/orders/${orderId}/${action}`, {
        method: "POST",
        body: body ?? {},
        idempotencyKey: idem ? newIdempotencyKey() : undefined,
      }),
    onSuccess: () => {
      toast.success("Done");
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Action failed"),
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !order)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Order not found.</p>
      </main>
    );

  const s = order.status;

  return (
    <main className="space-y-6 p-6">
      <Link href="/orders"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Orders
      </Link>
      <PageHeader
        title={order.order_number}
        description={
          org
            ? `${org.name}${order.customer_po_number ? ` · PO ${order.customer_po_number}` : ""}`
            : undefined
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <OrderStatusBadge status={s} />
            {s === "draft" && (
              <Button size="sm" disabled={act.isPending}
                onClick={() => {
                  if (window.confirm("Confirm this order? Available stock will be reserved."))
                    act.mutate({ action: "confirm", idem: true });
                }}>
                Confirm & reserve stock
              </Button>
            )}
            {s === "confirmed" && (
              <Button size="sm" variant="outline" disabled={act.isPending}
                onClick={() => act.mutate({ action: "mark-preparing" })}>
                Mark preparing
              </Button>
            )}
            {(s === "confirmed" || s === "preparing") && (
              <Button size="sm" variant="outline" disabled={act.isPending}
                onClick={() => act.mutate({ action: "mark-ready" })}>
                Mark ready
              </Button>
            )}
            {!["draft", "cancelled"].includes(s) && (
              <Button size="sm" variant="outline" disabled={createInvoice.isPending}
                onClick={() => createInvoice.mutate()}>
                Create invoice
              </Button>
            )}
            {["draft", "confirmed", "preparing", "ready"].includes(s) && (
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

      <Card>
        <CardHeader><CardTitle className="text-base">Items (frozen snapshots)</CardTitle></CardHeader>
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
                {order.items.map((i) => (
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
          <div className="mt-3 ml-auto w-full max-w-xs space-y-1 text-sm">
            <p className="flex justify-between"><span>Subtotal</span><span>{order.subtotal}</span></p>
            <p className="flex justify-between"><span>Discount</span><span>-{order.discount_total}</span></p>
            <p className="flex justify-between"><span>Tax</span><span>{order.tax_total}</span></p>
            <p className="flex justify-between border-t border-border pt-1 font-semibold text-primary">
              <span>Grand total (PKR)</span><span>{order.grand_total}</span>
            </p>
          </div>
          {order.cancelled_reason && (
            <p className="mt-2 text-sm text-destructive">Cancelled: {order.cancelled_reason}</p>
          )}
        </CardContent>
      </Card>

      <div className="max-w-xl">
        <DocumentsPanel
          entityType="sales_order"
          entityId={order.id}
          documentType="customer_po"
          organizationId={order.organization_id}
          title="Customer PO & attachments"
        />
      </div>
    </main>
  );
}
