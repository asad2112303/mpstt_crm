"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import type { Organization } from "@/lib/types/crm";
import type { Order } from "@/lib/types/orders";
import type { SearchHit } from "@/lib/types/catalogue";
import { OrderStatusBadge } from "../page";
import { DocumentsPanel } from "@/components/documents-panel";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

function DraftOrderEditor({ order }: { order: Order }) {
  const queryClient = useQueryClient();
  const [lines, setLines] = useState(
    order.items.map((i) => ({
      product_variant_id: i.product_variant_id,
      label: i.description_snapshot,
      quantity: i.quantity,
      unit_price: i.unit_price,
      discount_percent: i.discount_percent,
    })),
  );
  const [poNumber, setPoNumber] = useState(order.customer_po_number ?? "");
  const [notes, setNotes] = useState(order.notes ?? "");
  const [itemQ, setItemQ] = useState("");

  const { data: hits } = useQuery({
    queryKey: ["catalogue", "search", itemQ],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q: itemQ } })).data,
    enabled: itemQ.length >= 2,
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/api/v1/orders/${order.id}`, {
        method: "PUT",
        body: {
          customer_po_number: poNumber || null,
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
      toast.success("Draft order saved — totals recalculated");
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Save failed"),
  });

  const valid = lines.length > 0 &&
    lines.every((l) => Number(l.quantity) > 0 && Number(l.unit_price) >= 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Edit draft order (frozen at confirmation)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="relative">
          <Input placeholder="Add item: search product / variant…" value={itemQ}
            onChange={(e) => setItemQ(e.target.value)} aria-label="Search catalogue" />
          {itemQ.length >= 2 && hits && (
            <ul className="absolute z-30 mt-1 max-h-44 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
              {hits.map((h) => (
                <li key={`${h.product_id}-${h.variant_id}`}>
                  <button type="button"
                    className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                    onClick={() => {
                      setLines((prev) => [...prev, {
                        product_variant_id: h.variant_id!, label: h.label,
                        quantity: "1", unit_price: "", discount_percent: "0",
                      }]);
                      setItemQ("");
                    }}>
                    {h.label} <span className="text-xs text-muted-foreground">({h.sku})</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

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

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="do-po">Customer PO number</Label>
            <Input id="do-po" value={poNumber} onChange={(e) => setPoNumber(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="do-notes">Notes</Label>
            <Input id="do-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
        <Button onClick={() => save.mutate()} disabled={!valid || save.isPending}>
          {save.isPending ? "Saving…" : "Save draft"}
        </Button>
      </CardContent>
    </Card>
  );
}

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

      {s === "draft" && <DraftOrderEditor key={order.items.map((i) => i.id).join(",")} order={order} />}

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
