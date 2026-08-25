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
      <DialogContent className="max-w-xl">
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
          <Button onClick={() => { setDialogVariant(null); setDialogOpen(true); }}>
            <Plus className="mr-1 h-4 w-4" aria-hidden /> New variant
          </Button>
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
