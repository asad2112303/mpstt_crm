"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Category, Product, Uom, Variant } from "@/lib/types/catalogue";
import { AttributeForm, type AttributeValues } from "@/components/attribute-form";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

function VariantDialog({
  product, category, uoms, variant, open, onOpenChange,
}: {
  product: Product;
  category: Category | undefined;
  uoms: Uom[];
  variant: Variant | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState(variant?.variant_code ?? "");
  const [name, setName] = useState(variant?.variant_name ?? "");
  const [uomId, setUomId] = useState(variant?.uom_id ?? product.base_uom_id);
  const [attrs, setAttrs] = useState<AttributeValues>(variant?.attributes ?? {});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});

  const save = useMutation({
    mutationFn: () =>
      variant
        ? api(`/api/v1/catalogue/variants/${variant.id}`, {
            method: "PATCH",
            body: { variant_name: name, uom_id: uomId, attributes: attrs },
          })
        : api(`/api/v1/catalogue/products/${product.id}/variants`, {
            method: "POST",
            body: { variant_code: code, variant_name: name, uom_id: uomId, attributes: attrs },
          }),
    onSuccess: () => {
      toast.success(variant ? "Variant updated" : "Variant created");
      queryClient.invalidateQueries({ queryKey: ["catalogue", "product", product.id] });
      onOpenChange(false);
    },
    onError: (e) => {
      if (e instanceof ApiError) {
        setFieldErrors(e.fieldErrors);
        toast.error(e.message);
      } else toast.error("Save failed");
    },
  });

  const defs = category?.attribute_schema.attributes ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{variant ? `Edit ${variant.variant_code}` : "New variant"}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            {!variant && (
              <div className="space-y-1.5">
                <Label htmlFor="v-code">Variant code</Label>
                <Input id="v-code" required value={code} onChange={(e) => setCode(e.target.value)} />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="v-name">Variant name</Label>
              <Input id="v-name" required value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="v-uom">UOM</Label>
              <select
                id="v-uom"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={uomId}
                onChange={(e) => setUomId(e.target.value)}
              >
                {uoms.map((u) => (
                  <option key={u.id} value={u.id}>{u.code} — {u.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Specifications</p>
            <AttributeForm defs={defs} values={attrs} onChange={setAttrs} fieldErrors={fieldErrors} />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={save.isPending || !name || (!variant && !code)}>
              {save.isPending ? "Saving…" : "Save variant"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditProductDialog({ product }: { product: Product }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: product.name,
    description: product.description ?? "",
    tax_rate: product.tax_rate,
    is_active: product.is_active,
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/api/v1/catalogue/products/${product.id}`, {
        method: "PATCH",
        body: {
          name: form.name,
          description: form.description || null,
          tax_rate: form.tax_rate,
          is_active: form.is_active,
        },
      }),
    onSuccess: () => {
      toast.success("Product updated");
      queryClient.invalidateQueries({ queryKey: ["catalogue"] });
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed"),
  });

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>Edit product</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Edit {product.sku}</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="ep-name">Name *</Label>
              <Input id="ep-name" required minLength={2} value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ep-desc">Description</Label>
              <Input id="ep-desc" value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 items-end gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="ep-tax">Tax rate %</Label>
                <Input id="ep-tax" type="number" min="0" max="100" step="0.01"
                  value={form.tax_rate}
                  onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} />
              </div>
              <label className="flex items-center gap-2 pb-2 text-sm">
                <input type="checkbox" checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                Active
              </label>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!form.name || save.isPending}>
                {save.isPending ? "Saving…" : "Save changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default function ProductDetailPage({
  params,
}: {
  params: Promise<{ productId: string }>;
}) {
  const { productId } = use(params);
  const queryClient = useQueryClient();
  const [dialogVariant, setDialogVariant] = useState<Variant | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: product, isLoading, error } = useQuery({
    queryKey: ["catalogue", "product", productId],
    queryFn: async () => (await api<Product>(`/api/v1/catalogue/products/${productId}`)).data,
  });
  const { data: categories } = useQuery({
    queryKey: ["catalogue", "categories"],
    queryFn: async () => (await api<Category[]>("/api/v1/catalogue/categories")).data,
  });
  const { data: uoms } = useQuery({
    queryKey: ["catalogue", "uoms"],
    queryFn: async () => (await api<Uom[]>("/api/v1/catalogue/uoms")).data,
  });

  const toggleActive = useMutation({
    mutationFn: (v: Variant) =>
      api(`/api/v1/catalogue/variants/${v.id}`, {
        method: "PATCH",
        body: { is_active: !v.is_active },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalogue", "product", productId] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed"),
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-72 w-full" /></main>;
  if (error || !product)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">
          Product not found or failed to load.
        </p>
      </main>
    );

  const category = categories?.find((c) => c.id === product.category_id);

  return (
    <main className="space-y-6 p-6">
      <Link href="/catalogue" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Catalogue
      </Link>
      <PageHeader
        title={product.name}
        description={`SKU ${product.sku} · ${category?.name ?? ""} · Tax ${product.tax_rate}%`}
        actions={
          <div className="flex items-center gap-2">
            <EditProductDialog product={product} />
            <Button onClick={() => { setDialogVariant(null); setDialogOpen(true); }}>
              <Plus className="mr-1 h-4 w-4" aria-hidden /> New variant
            </Button>
          </div>
        }
      />

      {!product.variants.length ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          No variants yet. A product needs at least one sellable variant.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Variant</TableHead>
                <TableHead>Specifications</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {product.variants.map((v) => (
                <TableRow key={v.id}>
                  <TableCell className="font-mono text-xs">{v.variant_code}</TableCell>
                  <TableCell className="font-medium">{v.variant_name}</TableCell>
                  <TableCell className="max-w-md text-xs text-muted-foreground">
                    {Object.entries(v.attributes)
                      .map(([k, val]) => `${k}: ${String(val)}`)
                      .join(" · ") || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={v.is_active ? "outline" : "destructive"}>
                      {v.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button variant="outline" size="sm"
                      onClick={() => { setDialogVariant(v); setDialogOpen(true); }}>
                      Edit
                    </Button>
                    <Button variant="ghost" size="sm" disabled={toggleActive.isPending}
                      onClick={() => toggleActive.mutate(v)}>
                      {v.is_active ? "Deactivate" : "Activate"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {dialogOpen && (
        <VariantDialog
          key={dialogVariant?.id ?? "new"}
          product={product}
          category={category}
          uoms={uoms ?? []}
          variant={dialogVariant}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
        />
      )}
    </main>
  );
}
