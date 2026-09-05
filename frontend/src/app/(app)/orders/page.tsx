"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ClipboardList, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Organization } from "@/lib/types/crm";
import type { Order, OrderStatus } from "@/lib/types/orders";
import type { SearchHit } from "@/lib/types/catalogue";
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

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const styles: Record<OrderStatus, string> = {
    draft: "bg-muted text-muted-foreground",
    confirmed: "bg-primary/15 text-primary",
    preparing: "bg-warning/20 text-warning-foreground",
    ready: "bg-chart-2/30 text-primary",
    partially_delivered: "bg-warning/20 text-warning-foreground",
    fully_delivered: "bg-primary/20 text-primary",
    completed: "bg-primary text-primary-foreground",
    cancelled: "bg-destructive/15 text-destructive",
  };
  return (
    <Badge className={cn("border-transparent capitalize", styles[status])}>
      {status.replace("_", " ")}
    </Badge>
  );
}

interface LineDraft {
  variantId: string;
  label: string;
  quantity: string;
  unit_price: string;
  discount_percent: string;
}

function NewOrderDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState<Organization | null>(null);
  const [q, setQ] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [poNumber, setPoNumber] = useState("");
  const [itemQ, setItemQ] = useState("");

  const { data: customers } = useQuery({
    queryKey: ["customers", { search: q }],
    queryFn: async () =>
      (await api<Organization[]>("/api/v1/customers", {
        searchParams: { search: q || undefined, page_size: 8 },
      })).data,
    enabled: open && !customer,
  });
  const { data: hits } = useQuery({
    queryKey: ["catalogue", "search", itemQ],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q: itemQ } })).data,
    enabled: itemQ.length >= 2,
  });

  const create = useMutation({
    mutationFn: () =>
      api<Order>("/api/v1/orders", {
        method: "POST",
        body: {
          organization_id: customer!.id,
          customer_po_number: poNumber || null,
          items: lines.map((l) => ({
            product_variant_id: l.variantId,
            quantity: l.quantity,
            unit_price: l.unit_price,
            discount_percent: l.discount_percent || "0",
          })),
        },
      }),
    onSuccess: (resp) => {
      toast.success(`Order ${resp.data.order_number} created (draft)`);
      setOpen(false);
      router.push(`/orders/${resp.data.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const valid = customer && lines.length > 0 &&
    lines.every((l) => Number(l.quantity) > 0 && Number(l.unit_price) >= 0);

  return (
    <Dialog open={open} onOpenChange={(o) => {
      setOpen(o);
      if (!o) { setCustomer(null); setLines([]); setPoNumber(""); }
    }}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> New order (customer PO)
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {customer ? `New order — ${customer.name}` : "New order — choose customer"}
          </DialogTitle>
        </DialogHeader>

        {!customer ? (
          <>
            <Input autoFocus placeholder="Search customers…" value={q}
              onChange={(e) => setQ(e.target.value)} aria-label="Search customers" />
            <ul className="max-h-64 space-y-1 overflow-auto">
              {(customers ?? []).map((c) => (
                <li key={c.id}>
                  <button
                    className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                    onClick={() => setCustomer(c)}>
                    <span className="font-medium">{c.name}</span>{" "}
                    <span className="text-xs text-muted-foreground">
                      {c.customer_profile?.customer_code}
                    </span>
                  </button>
                </li>
              ))}
              {!customers?.length && (
                <li className="px-3 py-4 text-sm text-muted-foreground">
                  No customers found. Prospects get their first order through conversion.
                </li>
              )}
            </ul>
          </>
        ) : (
          <div className="space-y-4">
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
                            variantId: h.variant_id!, label: h.label,
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
                      <TableRow key={`${l.variantId}-${i}`}>
                        <TableCell className="w-full min-w-32 whitespace-normal text-sm">{l.label}</TableCell>
                        <TableCell>
                          <Input type="number" min="0.001" step="any" value={l.quantity}
                            className="w-20"
                            aria-label="Quantity"
                            onChange={(e) => setLines((p) =>
                              p.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" min="0" step="0.01" value={l.unit_price}
                            className="w-24"
                            aria-label="Unit price"
                            onChange={(e) => setLines((p) =>
                              p.map((x, j) => j === i ? { ...x, unit_price: e.target.value } : x))} />
                        </TableCell>
                        <TableCell>
                          <Input type="number" min="0" max="100" step="0.01" value={l.discount_percent}
                            className="w-20"
                            aria-label="Discount"
                            onChange={(e) => setLines((p) =>
                              p.map((x, j) => j === i ? { ...x, discount_percent: e.target.value } : x))} />
                        </TableCell>
                        <TableCell>
                          <Button variant="ghost" size="icon-sm" aria-label="Remove"
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

            <div className="space-y-1.5">
              <Label htmlFor="no-po">Customer PO number</Label>
              <Input id="no-po" className="max-w-xs" value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)} />
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setCustomer(null)}>Back</Button>
              <Button disabled={!valid || create.isPending} onClick={() => create.mutate()}>
                {create.isPending ? "Creating…" : "Create draft order"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const STATUS_FILTERS = ["", "draft", "confirmed", "preparing", "ready",
  "partially_delivered", "fully_delivered", "completed", "cancelled"];

export default function OrdersPage() {
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["orders", { status, search, page }],
    queryFn: async () =>
      await api<Order[]>("/api/v1/orders", {
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
        title="Sales orders"
        description="Confirmation reserves stock; delivery drives fulfilment statuses."
        actions={<NewOrderDialog />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search order no, PO no, organization…" className="w-72" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search orders" />
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
              {s === "" ? "All" : s.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load orders: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <ClipboardList className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No orders match.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Order</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Customer PO</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="text-right">Total (PKR)</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell>
                      <Link href={`/orders/${o.id}`}
                        className="font-medium text-primary hover:underline">
                        {o.order_number}
                      </Link>
                    </TableCell>
                    <TableCell>{o.order_date}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {o.customer_po_number ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {o.source_quotation_id ? "Quotation" : "Direct PO"}
                    </TableCell>
                    <TableCell className="text-right font-medium">{o.grand_total}</TableCell>
                    <TableCell><OrderStatusBadge status={o.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} orders</span>
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
