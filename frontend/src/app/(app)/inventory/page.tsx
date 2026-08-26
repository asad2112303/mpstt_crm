"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageOpen, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { formatKarachi } from "@/lib/types/crm";
import type { MovementRow, StockRow, WarehouseRow } from "@/lib/types/orders";
import type { SearchHit } from "@/lib/types/catalogue";
import { PageHeader } from "@/components/page-header";
import { useAuth } from "@/lib/auth-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

function AdjustmentDialog({ warehouses }: { warehouses: WarehouseRow[] }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [warehouseId, setWarehouseId] = useState("");
  const [picked, setPicked] = useState<SearchHit | null>(null);
  const [itemQ, setItemQ] = useState("");
  const [quantity, setQuantity] = useState("");
  const [movementType, setMovementType] = useState("adjustment");
  const [reason, setReason] = useState("");

  const { data: hits } = useQuery({
    queryKey: ["catalogue", "search", itemQ],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q: itemQ } })).data,
    enabled: itemQ.length >= 2,
  });

  const adjust = useMutation({
    mutationFn: () =>
      api("/api/v1/inventory/adjustments", {
        method: "POST",
        body: {
          warehouse_id: warehouseId,
          product_variant_id: picked!.variant_id,
          quantity, reason, movement_type: movementType,
        },
      }),
    onSuccess: () => {
      toast.success("Stock adjusted");
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
      setOpen(false);
      setPicked(null); setQuantity(""); setReason("");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Adjustment failed"),
  });

  const valid = warehouseId && picked && Number(quantity) !== 0 && reason.length >= 3;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> Adjustment
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Stock adjustment (Admin)</DialogTitle></DialogHeader>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); adjust.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="adj-wh">Warehouse</Label>
            <Select value={warehouseId} onValueChange={(v) => setWarehouseId(v ?? "")}>
              <SelectTrigger id="adj-wh"><SelectValue placeholder="Select…" /></SelectTrigger>
              <SelectContent>
                {warehouses.filter((w) => w.is_active).map((w) => (
                  <SelectItem key={w.id} value={w.id}>{w.code} — {w.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Product / variant</Label>
            {picked ? (
              <div className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                <span>{picked.label}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => setPicked(null)}>
                  Change
                </Button>
              </div>
            ) : (
              <div className="relative">
                <Input placeholder="Search…" value={itemQ}
                  onChange={(e) => setItemQ(e.target.value)} aria-label="Search catalogue" />
                {itemQ.length >= 2 && hits && (
                  <ul className="absolute z-30 mt-1 max-h-40 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
                    {hits.map((h) => (
                      <li key={`${h.product_id}-${h.variant_id}`}>
                        <button type="button"
                          className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                          onClick={() => { setPicked(h); setItemQ(""); }}>
                          {h.label}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="adj-qty">Quantity (+ in / − out)</Label>
              <Input id="adj-qty" type="number" step="any" value={quantity}
                onChange={(e) => setQuantity(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="adj-type">Type</Label>
              <Select value={movementType} onValueChange={(v) => setMovementType(v ?? "adjustment")}>
                <SelectTrigger id="adj-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="adjustment">Adjustment</SelectItem>
                  <SelectItem value="opening">Opening stock</SelectItem>
                  <SelectItem value="receipt_in">Receipt in</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adj-reason">Reason (required, audited)</Label>
            <Textarea id="adj-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!valid || adjust.isPending}>
              {adjust.isPending ? "Applying…" : "Apply adjustment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BalancesTab({ warehouses }: { warehouses: WarehouseRow[] }) {
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["inventory", "balances", { search, lowOnly }],
    queryFn: async () =>
      (await api<StockRow[]>("/api/v1/inventory/balances", {
        searchParams: {
          search: search || undefined,
          low_stock_below: lowOnly ? 50 : undefined,
        },
      })).data,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input placeholder="Search product, variant, SKU…" className="w-72" value={search}
          onChange={(e) => setSearch(e.target.value)} aria-label="Search stock" />
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={lowOnly} onCheckedChange={(v) => setLowOnly(v === true)} />
          Low stock only (&lt; 50 available)
        </label>
      </div>
      {isLoading ? (
        <Skeleton className="h-56 w-full" />
      ) : !data?.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-10 text-center">
          <PackageOpen className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            No stock rows. {warehouses.length === 0 && "Create a warehouse first, then add opening stock."}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Warehouse</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead>Product / variant</TableHead>
                <TableHead>UOM</TableHead>
                <TableHead className="text-right">On hand</TableHead>
                <TableHead className="text-right">Reserved</TableHead>
                <TableHead className="text-right">Available</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => {
                const low = Number(r.available) < 50;
                return (
                  <TableRow key={`${r.warehouse_id}-${r.product_variant_id}`}>
                    <TableCell className="font-mono text-xs">{r.warehouse_code}</TableCell>
                    <TableCell className="font-mono text-xs">{r.sku}</TableCell>
                    <TableCell className="text-sm">
                      {r.product_name} — {r.variant_name}
                    </TableCell>
                    <TableCell>{r.uom_code}</TableCell>
                    <TableCell className="text-right">{r.on_hand}</TableCell>
                    <TableCell className="text-right">{r.reserved}</TableCell>
                    <TableCell className="text-right font-medium">
                      {r.available}{" "}
                      {low && (
                        <Badge className="ml-1 border-transparent bg-warning/20 text-warning-foreground">
                          Low
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function MovementsTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["inventory", "movements"],
    queryFn: async () =>
      (await api<MovementRow[]>("/api/v1/inventory/movements", {
        searchParams: { page_size: 100 },
      })).data,
  });
  if (isLoading) return <Skeleton className="h-56 w-full" />;
  if (!data?.length) return <p className="text-sm text-muted-foreground">No movements.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Product</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Reference</TableHead>
            <TableHead>Notes</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((m) => (
            <TableRow key={m.id}>
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                {formatKarachi(m.movement_at)}
              </TableCell>
              <TableCell className="text-sm">{m.product}</TableCell>
              <TableCell className={`text-right font-medium ${Number(m.quantity) < 0 ? "text-destructive" : "text-primary"}`}>
                {Number(m.quantity) > 0 ? "+" : ""}{m.quantity}
              </TableCell>
              <TableCell><Badge variant="secondary">{m.movement_type}</Badge></TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {m.reference_id ?? "—"}
              </TableCell>
              <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                {m.notes ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function WarehousesTab({ warehouses }: { warehouses: WarehouseRow[] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", name: "", address: "" });
  const patchWh = useMutation({
    mutationFn: ({ wh, changes }: { wh: WarehouseRow; changes: Partial<WarehouseRow> }) =>
      api(`/api/v1/inventory/warehouses/${wh.id}`, {
        method: "PATCH",
        body: {
          code: wh.code,
          name: changes.name ?? wh.name,
          address: changes.address !== undefined ? changes.address : wh.address,
          is_active: changes.is_active ?? wh.is_active,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inventory"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const create = useMutation({
    mutationFn: () =>
      api("/api/v1/inventory/warehouses", {
        method: "POST",
        body: { ...form, address: form.address || null },
      }),
    onSuccess: () => {
      toast.success("Warehouse created");
      queryClient.invalidateQueries({ queryKey: ["inventory"] });
      setForm({ code: "", name: "", address: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  return (
    <div className="space-y-4">
      <form className="flex max-w-2xl flex-wrap items-end gap-2"
        onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <div className="space-y-1.5">
          <Label htmlFor="wh-code">Code</Label>
          <Input id="wh-code" className="w-28" value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wh-name">Name</Label>
          <Input id="wh-name" className="w-56" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wh-addr">Address</Label>
          <Input id="wh-addr" className="w-64" value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </div>
        <Button type="submit" disabled={!form.code || !form.name || create.isPending}>
          Add warehouse
        </Button>
      </form>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead><TableHead>Name</TableHead>
              <TableHead>Address</TableHead><TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {warehouses.map((w) => (
              <TableRow key={w.id}>
                <TableCell className="font-mono text-xs">{w.code}</TableCell>
                <TableCell className="font-medium">{w.name}</TableCell>
                <TableCell className="text-muted-foreground">{w.address ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={w.is_active ? "outline" : "destructive"}>
                    {w.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button variant="ghost" size="sm"
                    onClick={() => {
                      const newName = window.prompt("Warehouse name:", w.name);
                      if (newName) patchWh.mutate({ wh: w, changes: { name: newName } });
                    }}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="sm"
                    onClick={() => patchWh.mutate({ wh: w, changes: { is_active: !w.is_active } })}>
                    {w.is_active ? "Deactivate" : "Activate"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const { me } = useAuth();
  const { data: warehouses } = useQuery({
    queryKey: ["inventory", "warehouses"],
    queryFn: async () => (await api<WarehouseRow[]>("/api/v1/inventory/warehouses")).data,
  });

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Inventory"
        description="Available = on hand − reserved. Adjustments are Admin-only and audited."
        actions={me?.role === "admin" ? <AdjustmentDialog warehouses={warehouses ?? []} /> : undefined}
      />
      <Tabs defaultValue="balances">
        <TabsList>
          <TabsTrigger value="balances">Balances</TabsTrigger>
          <TabsTrigger value="movements">Movements</TabsTrigger>
          {me?.role === "admin" && <TabsTrigger value="warehouses">Warehouses</TabsTrigger>}
        </TabsList>
        <TabsContent value="balances" className="pt-4">
          <BalancesTab warehouses={warehouses ?? []} />
        </TabsContent>
        <TabsContent value="movements" className="pt-4"><MovementsTab /></TabsContent>
        {me?.role === "admin" && (
          <TabsContent value="warehouses" className="pt-4">
            <WarehousesTab warehouses={warehouses ?? []} />
          </TabsContent>
        )}
      </Tabs>
    </main>
  );
}
