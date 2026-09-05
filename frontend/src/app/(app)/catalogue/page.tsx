"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackagePlus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Category, ProductListItem, Uom, Brand } from "@/lib/types/catalogue";
import { PageHeader } from "@/components/page-header";
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

function NewProductDialog({ categories, brands, uoms }: {
  categories: Category[]; brands: Brand[]; uoms: Uom[];
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    sku: "", name: "", category_id: "", brand_id: "", base_uom_id: "",
    tax_rate: "0", description: "",
  });

  const create = useMutation({
    mutationFn: () =>
      api("/api/v1/catalogue/products", {
        method: "POST",
        body: {
          ...form,
          brand_id: form.brand_id || null,
          description: form.description || null,
        },
      }),
    onSuccess: () => {
      toast.success("Product created");
      queryClient.invalidateQueries({ queryKey: ["catalogue", "products"] });
      setOpen(false);
      setForm({ sku: "", name: "", category_id: "", brand_id: "", base_uom_id: "", tax_rate: "0", description: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to create product"),
  });

  const valid = form.sku && form.name.length >= 2 && form.category_id && form.base_uom_id;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <PackagePlus className="h-4 w-4" aria-hidden /> New product
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>New product</DialogTitle></DialogHeader>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="p-sku">SKU</Label>
            <Input id="p-sku" required value={form.sku}
              onChange={(e) => setForm({ ...form, sku: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-name">Name</Label>
            <Input id="p-name" required minLength={2} value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-cat">Category</Label>
            <Select value={form.category_id} onValueChange={(v) => setForm({ ...form, category_id: v ?? "" })}>
              <SelectTrigger id="p-cat"><SelectValue placeholder="Select…" /></SelectTrigger>
              <SelectContent>
                {categories.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-brand">Brand (optional)</Label>
            <Select value={form.brand_id} onValueChange={(v) => setForm({ ...form, brand_id: v ?? "" })}>
              <SelectTrigger id="p-brand"><SelectValue placeholder="None" /></SelectTrigger>
              <SelectContent>
                {brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-uom">Base UOM</Label>
            <Select value={form.base_uom_id} onValueChange={(v) => setForm({ ...form, base_uom_id: v ?? "" })}>
              <SelectTrigger id="p-uom"><SelectValue placeholder="Select…" /></SelectTrigger>
              <SelectContent>
                {uoms.map((u) => <SelectItem key={u.id} value={u.id}>{u.code} — {u.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-tax">Tax rate %</Label>
            <Input id="p-tax" type="number" min={0} max={100} step="0.01" value={form.tax_rate}
              onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="p-desc">Description</Label>
            <Input id="p-desc" value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <DialogFooter className="sm:col-span-2">
            <Button type="submit" disabled={!valid || create.isPending}>
              {create.isPending ? "Creating…" : "Create product"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function CataloguePage() {
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [page, setPage] = useState(1);

  const { data: categories } = useQuery({
    queryKey: ["catalogue", "categories"],
    queryFn: async () => (await api<Category[]>("/api/v1/catalogue/categories")).data,
  });
  const { data: brands } = useQuery({
    queryKey: ["catalogue", "brands"],
    queryFn: async () => (await api<Brand[]>("/api/v1/catalogue/brands")).data,
  });
  const { data: uoms } = useQuery({
    queryKey: ["catalogue", "uoms"],
    queryFn: async () => (await api<Uom[]>("/api/v1/catalogue/uoms")).data,
  });

  const { data: products, isLoading, error } = useQuery({
    queryKey: ["catalogue", "products", { search, categoryId, showInactive, page }],
    queryFn: async () =>
      await api<ProductListItem[]>("/api/v1/catalogue/products", {
        searchParams: {
          search: search || undefined,
          category_id: categoryId || undefined,
          include_inactive: showInactive,
          page,
          page_size: 25,
        },
      }),
  });

  const total = products?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Catalogue"
        description="Products, variants, and specifications."
        actions={
          <NewProductDialog
            categories={categories ?? []} brands={brands ?? []} uoms={uoms ?? []}
          />
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search name or SKU…"
          className="w-64"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search products"
        />
        <Select value={categoryId} onValueChange={(v) => { setCategoryId(v ?? ""); setPage(1); }}>
          <SelectTrigger className="w-52" aria-label="Filter by category">
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent>
            {(categories ?? []).map((c) => (
              <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {categoryId && (
          <Button variant="ghost" size="sm" onClick={() => setCategoryId("")}>Clear</Button>
        )}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={showInactive} onCheckedChange={(v) => setShowInactive(v === true)} />
          Show inactive
        </label>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load products: {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : !products?.data.length ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          No products found. Create the first product or apply the starting templates
          under <Link className="text-primary underline" href="/catalogue/master">Master data</Link>.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>SKU</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Brand</TableHead>
                  <TableHead>UOM</TableHead>
                  <TableHead className="text-right">Tax %</TableHead>
                  <TableHead className="text-right">Variants</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {products.data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.sku}</TableCell>
                    <TableCell>
                      <Link href={`/catalogue/${p.id}`} className="font-medium text-primary hover:underline">
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell>{p.category_name}</TableCell>
                    <TableCell className="text-muted-foreground">{p.brand_name ?? "—"}</TableCell>
                    <TableCell>{p.base_uom_code}</TableCell>
                    <TableCell className="text-right">{p.tax_rate}</TableCell>
                    <TableCell className="text-right">{p.variant_count}</TableCell>
                    <TableCell>
                      <Badge variant={p.is_active ? "outline" : "destructive"}>
                        {p.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} products</span>
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
