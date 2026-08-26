"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Truck, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { formatKarachi } from "@/lib/types/crm";
import type { Order } from "@/lib/types/orders";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export interface DeliveryRow {
  id: string;
  challan_number: string;
  sales_order_id: string;
  organization_id: string;
  status: "draft" | "dispatched" | "delivered" | "cancelled";
  scheduled_date: string | null;
  dispatched_at: string | null;
  delivered_at: string | null;
  delivery_person: string | null;
  vehicle: string | null;
  items: {
    id: string; sales_order_item_id: string; description_snapshot: string;
    uom_code: string; dispatched_quantity: string; delivered_quantity: string;
    rejected_quantity: string; rejection_remarks: string | null;
  }[];
  pod: {
    receiver_name: string; receiver_designation: string | null; received_at: string;
    signed_challan_document_id: string | null; signature_document_id: string | null;
  } | null;
}

interface RemainingRow {
  sales_order_item_id: string;
  description: string;
  uom_code: string;
  ordered: string;
  delivered: string;
  pending: string;
  remaining: string;
}

export function DeliveryStatusBadge({ status }: { status: DeliveryRow["status"] }) {
  const styles = {
    draft: "bg-muted text-muted-foreground",
    dispatched: "bg-warning/20 text-warning-foreground",
    delivered: "bg-primary text-primary-foreground",
    cancelled: "bg-destructive/15 text-destructive",
  } as const;
  return (
    <Badge className={cn("border-transparent capitalize", styles[status])}>{status}</Badge>
  );
}

function NewChallanDialog() {
  const [open, setOpen] = useState(false);
  const [orderSearch, setOrderSearch] = useState("");
  const [order, setOrder] = useState<Order | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [person, setPerson] = useState("");
  const [vehicle, setVehicle] = useState("");

  const { data: orders } = useQuery({
    queryKey: ["orders", { search: orderSearch, deliverable: true }],
    queryFn: async () =>
      (await api<Order[]>("/api/v1/orders", {
        searchParams: { search: orderSearch || undefined, page_size: 10 },
      })).data.filter((o) =>
        ["confirmed", "preparing", "ready", "partially_delivered"].includes(o.status)),
    enabled: open && !order,
  });
  const { data: remaining } = useQuery({
    queryKey: ["deliveries", "remaining", order?.id],
    queryFn: async () =>
      (await api<RemainingRow[]>(`/api/v1/deliveries/order/${order!.id}/remaining`)).data,
    enabled: Boolean(order),
  });

  const create = useMutation({
    mutationFn: () =>
      api<DeliveryRow>("/api/v1/deliveries", {
        method: "POST",
        body: {
          sales_order_id: order!.id,
          delivery_person: person || null,
          vehicle: vehicle || null,
          items: Object.entries(quantities)
            .filter(([, q]) => Number(q) > 0)
            .map(([itemId, q]) => ({ sales_order_item_id: itemId, quantity: q })),
        },
      }),
    onSuccess: (resp) => {
      toast.success(`Challan ${resp.data.challan_number} created`);
      setOpen(false);
      window.location.href = `/deliveries/${resp.data.id}`;
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const anyQty = Object.values(quantities).some((q) => Number(q) > 0);

  return (
    <Dialog open={open} onOpenChange={(o) => {
      setOpen(o);
      if (!o) { setOrder(null); setQuantities({}); }
    }}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> New challan
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {order ? `Challan from ${order.order_number}` : "New challan — choose order"}
          </DialogTitle>
        </DialogHeader>

        {!order ? (
          <>
            <Input autoFocus placeholder="Search deliverable orders…" value={orderSearch}
              onChange={(e) => setOrderSearch(e.target.value)} aria-label="Search orders" />
            <ul className="max-h-64 space-y-1 overflow-auto">
              {(orders ?? []).map((o) => (
                <li key={o.id}>
                  <button
                    className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                    onClick={() => setOrder(o)}>
                    <span className="font-medium">{o.order_number}</span>{" "}
                    <span className="text-xs capitalize text-muted-foreground">
                      {o.status.replace("_", " ")} · PKR {o.grand_total}
                    </span>
                  </button>
                </li>
              ))}
              {!orders?.length && (
                <li className="px-3 py-4 text-sm text-muted-foreground">
                  No deliverable orders (confirmed / preparing / ready / partially delivered).
                </li>
              )}
            </ul>
          </>
        ) : (
          <div className="space-y-4">
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Ordered</TableHead>
                    <TableHead className="text-right">Delivered</TableHead>
                    <TableHead className="text-right">Remaining</TableHead>
                    <TableHead className="w-28">This challan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(remaining ?? []).map((r) => (
                    <TableRow key={r.sales_order_item_id}>
                      <TableCell className="text-sm">{r.description}</TableCell>
                      <TableCell className="text-right">{r.ordered}</TableCell>
                      <TableCell className="text-right">{r.delivered}</TableCell>
                      <TableCell className="text-right font-medium">{r.remaining}</TableCell>
                      <TableCell>
                        <Input type="number" min="0" max={r.remaining} step="any"
                          aria-label={`Quantity for ${r.description}`}
                          value={quantities[r.sales_order_item_id] ?? ""}
                          disabled={Number(r.remaining) <= 0}
                          onChange={(e) =>
                            setQuantities((prev) => ({
                              ...prev, [r.sales_order_item_id]: e.target.value,
                            }))} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="dc-person">Delivery person</Label>
                <Input id="dc-person" value={person} onChange={(e) => setPerson(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dc-vehicle">Vehicle</Label>
                <Input id="dc-vehicle" value={vehicle} onChange={(e) => setVehicle(e.target.value)} />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOrder(null)}>Back</Button>
              <Button disabled={!anyQty || create.isPending} onClick={() => create.mutate()}>
                {create.isPending ? "Creating…" : "Create challan"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const FILTERS = ["", "draft", "dispatched", "delivered", "cancelled"];

export default function DeliveriesPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["deliveries", { status, search, page }],
    queryFn: async () =>
      await api<DeliveryRow[]>("/api/v1/deliveries", {
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
        title="Deliveries"
        description="Challans, partial fulfilment, and POD evidence."
        actions={<NewChallanDialog />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search challan or organization…" className="w-72" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search deliveries" />
        <div className="flex gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((s) => (
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
          Failed to load deliveries: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Truck className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No deliveries match.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Challan</TableHead>
                  <TableHead>Lines</TableHead>
                  <TableHead>Delivered at</TableHead>
                  <TableHead>POD</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link href={`/deliveries/${d.id}`}
                        className="font-medium text-primary hover:underline">
                        {d.challan_number}
                      </Link>
                    </TableCell>
                    <TableCell>{d.items.length}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatKarachi(d.delivered_at)}
                    </TableCell>
                    <TableCell>
                      {d.status === "delivered" ? (
                        d.pod ? (
                          <Badge variant="outline">✓ {d.pod.receiver_name}</Badge>
                        ) : (
                          <Badge variant="destructive">Missing POD</Badge>
                        )
                      ) : "—"}
                    </TableCell>
                    <TableCell><DeliveryStatusBadge status={d.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} deliveries</span>
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
