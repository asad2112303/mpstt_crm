"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Package, PackagePlus, PackageX, Search } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { pkrExact, type BillingProduct } from "@/lib/types/billing";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

type Tab = "tracked" | "untracked";

function ReceiveStockDialog({
  product, onClose,
}: {
  product: BillingProduct | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState("");
  const [cost, setCost] = useState("");

  const receive = useMutation({
    mutationFn: () =>
      api("/api/v1/inventory/receipts", {
        method: "POST",
        body: {
          product_variant_id: product!.product_variant_id,
          quantity,
          unit_cost: cost || null,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["products-view"] });
      toast.success("Stock received.");
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not receive stock."),
  });

  return (
    <Dialog open={product != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        {product && (
          <>
            <DialogHeader>
              <DialogTitle>Receive stock</DialogTitle>
              <DialogDescription>{product.label}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="rc-qty">Quantity received ({product.uom_code})</Label>
                <Input id="rc-qty" inputMode="decimal" value={quantity} autoFocus
                  onChange={(e) => setQuantity(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="rc-cost">Purchase cost per unit</Label>
                <Input id="rc-cost" inputMode="decimal" value={cost}
                  onChange={(e) => setCost(e.target.value)} placeholder="Optional" />
                <p className="text-xs text-muted-foreground">
                  Drives the weighted average used for profit. Leaving it blank
                  adds the quantity but leaves those sales without a cost.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button disabled={!quantity || receive.isPending}
                onClick={() => receive.mutate()}>
                {receive.isPending ? "Saving…" : "Receive"}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function EnableTrackingDialog({
  product, onClose,
}: {
  product: BillingProduct | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [opening, setOpening] = useState("");
  const [cost, setCost] = useState("");
  const [reorder, setReorder] = useState("");

  const enable = useMutation({
    mutationFn: () =>
      api(`/api/v1/inventory/products/${product!.product_id}/enable-tracking`, {
        method: "POST",
        body: {
          opening_quantity: opening || "0",
          unit_cost: cost || null,
          reorder_level: reorder || null,
        },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["products-view"] });
      toast.success("Stock tracking enabled.");
      onClose();
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not enable tracking."),
  });

  return (
    <Dialog open={product != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        {product && (
          <>
            <DialogHeader>
              <DialogTitle>Start tracking stock</DialogTitle>
              <DialogDescription>{product.label}</DialogDescription>
            </DialogHeader>
            <p className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
              Enter what is actually on the shelf now. Quantities already sold on
              Quick Bill invoices are not added back as stock received.
            </p>
            <div className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="et-open">Opening stock on hand</Label>
                <Input id="et-open" inputMode="decimal" value={opening} autoFocus
                  onChange={(e) => setOpening(e.target.value)} placeholder="0" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="et-cost">Purchase cost per unit</Label>
                <Input id="et-cost" inputMode="decimal" value={cost}
                  onChange={(e) => setCost(e.target.value)} placeholder="Optional" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="et-reorder">Low-stock alert at</Label>
                <Input id="et-reorder" inputMode="decimal" value={reorder}
                  onChange={(e) => setReorder(e.target.value)} placeholder="Optional" />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button disabled={enable.isPending} onClick={() => enable.mutate()}>
                {enable.isPending ? "Saving…" : "Enable tracking"}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function ProductsPage() {
  const [tab, setTab] = useState<Tab>("tracked");
  const [search, setSearch] = useState("");
  const [receiving, setReceiving] = useState<BillingProduct | null>(null);
  const [enabling, setEnabling] = useState<BillingProduct | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["products-view", { tab, search }],
    queryFn: async () =>
      (
        await api<BillingProduct[]>("/api/v1/billing/products", {
          searchParams: { tracked: tab, search: search || undefined, limit: 200 },
        })
      ).data,
  });

  const rows = data ?? [];
  const lowStock = rows.filter((r) => r.low_stock);

  return (
    <main className="space-y-5 p-6">
      <PageHeader
        title="Products & Inventory"
        description="One catalogue, two views: what you hold stock of, and what you only bill."
        actions={
          <Button render={<Link href="/create-bill?mode=quick" />}>
            <PackagePlus className="mr-1.5 h-4 w-4" aria-hidden />
            New bill
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Product view">
          {(
            [
              ["tracked", "Stock-tracked", Package],
              ["untracked", "Quick Bill products", PackageX],
            ] as [Tab, string, typeof Package][]
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
                tab === value
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input className="w-72 pl-8" placeholder="Search products…" value={search}
            aria-label="Search products" onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>

      {tab === "tracked" && lowStock.length > 0 && (
        <p className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          {lowStock.length} product{lowStock.length > 1 ? "s are" : " is"} at or below
          the reorder level.
        </p>
      )}

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load products:{" "}
          {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-12 text-center text-sm text-muted-foreground">
          {tab === "tracked"
            ? "No stock-tracked products yet."
            : "No Quick Bill products yet. They appear here as you create them while billing."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Unit</TableHead>
                {tab === "tracked" ? (
                  <>
                    <TableHead className="text-right">Available</TableHead>
                    <TableHead className="text-right">Avg cost</TableHead>
                    <TableHead className="text-right">Reorder at</TableHead>
                  </>
                ) : (
                  <>
                    <TableHead className="text-right">Last price</TableHead>
                    <TableHead className="text-right">Cost on file</TableHead>
                  </>
                )}
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.product_variant_id}>
                  <TableCell>
                    <p className="font-medium">{r.label}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.sku}
                      {r.category ? ` · ${r.category}` : ""}
                      {r.created_via === "quick_bill" && " · added while billing"}
                    </p>
                  </TableCell>
                  <TableCell className="text-sm">{r.uom_code}</TableCell>
                  {tab === "tracked" ? (
                    <>
                      <TableCell className="text-right tabular-nums">
                        {r.available}
                        {r.low_stock && (
                          <Badge variant="destructive" className="ml-2">Low</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {r.avg_cost ? (
                          pkrExact(r.avg_cost)
                        ) : (
                          <span className="text-xs text-muted-foreground">No cost</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {r.reorder_level ?? "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => setReceiving(r)}>
                          Receive
                        </Button>
                      </TableCell>
                    </>
                  ) : (
                    <>
                      <TableCell className="text-right tabular-nums">
                        {Number(r.suggested_price) > 0 ? pkrExact(r.suggested_price) : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {r.standard_cost || r.default_purchase_cost ? (
                          pkrExact(r.standard_cost ?? r.default_purchase_cost)
                        ) : (
                          <span className="text-xs text-warning-foreground">
                            Profit incomplete
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => setEnabling(r)}>
                          Track stock
                        </Button>
                      </TableCell>
                    </>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <ReceiveStockDialog product={receiving} onClose={() => setReceiving(null)} />
      <EnableTrackingDialog product={enabling} onClose={() => setEnabling(null)} />
    </main>
  );
}
