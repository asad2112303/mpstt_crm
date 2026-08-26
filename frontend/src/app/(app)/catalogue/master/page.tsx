"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Brand, Category, Uom } from "@/lib/types/catalogue";
import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function CategoriesTab() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["catalogue", "categories", "all"],
    queryFn: async () =>
      (await api<Category[]>("/api/v1/catalogue/categories", {
        searchParams: { include_inactive: true },
      })).data,
  });

  const applyTemplates = useMutation({
    mutationFn: () => api("/api/v1/catalogue/categories/apply-templates", { method: "POST" }),
    onSuccess: (resp) => {
      const created = (resp.data as { created_categories: string[] }).created_categories;
      toast.success(created.length ? `Created: ${created.join(", ")}` : "Templates already applied");
      queryClient.invalidateQueries({ queryKey: ["catalogue"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const patchCat = useMutation({
    mutationFn: ({ cat, changes }: { cat: Category; changes: Partial<Category> }) =>
      api(`/api/v1/catalogue/categories/${cat.id}`, {
        method: "PATCH",
        body: {
          name: changes.name ?? cat.name,
          description: cat.description,
          attribute_schema: cat.attribute_schema,
          is_active: changes.is_active ?? cat.is_active,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalogue"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  return (
    <div className="space-y-4">
      <Button variant="outline" onClick={() => applyTemplates.mutate()} disabled={applyTemplates.isPending}>
        <Sparkles className="mr-1 h-4 w-4" aria-hidden />
        Apply starting templates
      </Button>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead>Specifications defined</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium">{c.name}</TableCell>
                <TableCell className="max-w-lg text-xs text-muted-foreground">
                  {c.attribute_schema.attributes.map((a) => a.label).join(", ") || "None"}
                </TableCell>
                <TableCell>
                  <Badge variant={c.is_active ? "outline" : "destructive"}>
                    {c.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button variant="ghost" size="sm"
                    onClick={() => {
                      const name = window.prompt("Category name:", c.name);
                      if (name) patchCat.mutate({ cat: c, changes: { name } });
                    }}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="sm"
                    onClick={() => patchCat.mutate({ cat: c, changes: { is_active: !c.is_active } })}>
                    {c.is_active ? "Deactivate" : "Activate"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        Specification templates are product master data, not a legal compliance
        determination. MPSTT Quality/Legal approves the exact waste-category and
        colour mapping used for each sellable item.
      </p>
    </div>
  );
}

function BrandsTab() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["catalogue", "brands", "all"],
    queryFn: async () =>
      (await api<Brand[]>("/api/v1/catalogue/brands", {
        searchParams: { include_inactive: true },
      })).data,
  });
  const patchBrand = useMutation({
    mutationFn: ({ brand, changes }: { brand: Brand; changes: Partial<Brand> }) =>
      api(`/api/v1/catalogue/brands/${brand.id}`, {
        method: "PATCH",
        body: {
          name: changes.name ?? brand.name,
          manufacturer: brand.manufacturer,
          country_of_origin: brand.country_of_origin,
          is_active: changes.is_active ?? brand.is_active,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalogue", "brands"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const create = useMutation({
    mutationFn: () => api("/api/v1/catalogue/brands", { method: "POST", body: { name } }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["catalogue", "brands"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  return (
    <div className="space-y-4">
      <form
        className="flex max-w-sm gap-2"
        onSubmit={(e) => { e.preventDefault(); if (name) create.mutate(); }}
      >
        <Input placeholder="New brand name" value={name} onChange={(e) => setName(e.target.value)}
          aria-label="New brand name" />
        <Button type="submit" disabled={!name || create.isPending}>Add</Button>
      </form>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Brand</TableHead><TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((b) => (
              <TableRow key={b.id}>
                <TableCell className="font-medium">{b.name}</TableCell>
                <TableCell>
                  <Badge variant={b.is_active ? "outline" : "destructive"}>
                    {b.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button variant="ghost" size="sm"
                    onClick={() => {
                      const newName = window.prompt("Brand name:", b.name);
                      if (newName) patchBrand.mutate({ brand: b, changes: { name: newName } });
                    }}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="sm"
                    onClick={() => patchBrand.mutate({ brand: b, changes: { is_active: !b.is_active } })}>
                    {b.is_active ? "Deactivate" : "Activate"}
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

function UomsTab() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", name: "" });
  const { data, isLoading } = useQuery({
    queryKey: ["catalogue", "uoms", "all"],
    queryFn: async () =>
      (await api<Uom[]>("/api/v1/catalogue/uoms", {
        searchParams: { include_inactive: true },
      })).data,
  });
  const patchUom = useMutation({
    mutationFn: ({ uom, changes }: { uom: Uom; changes: Partial<Uom> }) =>
      api(`/api/v1/catalogue/uoms/${uom.id}`, {
        method: "PATCH",
        body: {
          code: uom.code,
          name: changes.name ?? uom.name,
          category: uom.category,
          decimal_scale: uom.decimal_scale,
          is_active: changes.is_active ?? uom.is_active,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["catalogue", "uoms"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const create = useMutation({
    mutationFn: () => api("/api/v1/catalogue/uoms", { method: "POST", body: form }),
    onSuccess: () => {
      setForm({ code: "", name: "" });
      queryClient.invalidateQueries({ queryKey: ["catalogue", "uoms"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  return (
    <div className="space-y-4">
      <form
        className="flex max-w-md gap-2"
        onSubmit={(e) => { e.preventDefault(); if (form.code && form.name) create.mutate(); }}
      >
        <Input placeholder="Code (e.g. PCS)" className="w-32" value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
          aria-label="UOM code" />
        <Input placeholder="Name" value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="UOM name" />
        <Button type="submit" disabled={!form.code || !form.name || create.isPending}>Add</Button>
      </form>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead><TableHead>Name</TableHead>
              <TableHead>Decimals</TableHead><TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-mono text-xs">{u.code}</TableCell>
                <TableCell>{u.name}</TableCell>
                <TableCell>{u.decimal_scale}</TableCell>
                <TableCell>
                  <Badge variant={u.is_active ? "outline" : "destructive"}>
                    {u.is_active ? "Active" : "Inactive"}
                  </Badge>
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  <Button variant="ghost" size="sm"
                    onClick={() => {
                      const newName = window.prompt("Unit name:", u.name);
                      if (newName) patchUom.mutate({ uom: u, changes: { name: newName } });
                    }}>
                    Rename
                  </Button>
                  <Button variant="ghost" size="sm"
                    onClick={() => patchUom.mutate({ uom: u, changes: { is_active: !u.is_active } })}>
                    {u.is_active ? "Deactivate" : "Activate"}
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

export default function MasterDataPage() {
  return (
    <RequireAdmin>
      <main className="space-y-6 p-6">
        <PageHeader
          title="Master data"
          description="Categories with specification schemas, brands, and units of measure."
        />
        <Tabs defaultValue="categories">
          <TabsList>
            <TabsTrigger value="categories">Categories</TabsTrigger>
            <TabsTrigger value="brands">Brands</TabsTrigger>
            <TabsTrigger value="uoms">Units</TabsTrigger>
          </TabsList>
          <TabsContent value="categories" className="pt-4"><CategoriesTab /></TabsContent>
          <TabsContent value="brands" className="pt-4"><BrandsTab /></TabsContent>
          <TabsContent value="uoms" className="pt-4"><UomsTab /></TabsContent>
        </Tabs>
      </main>
    </RequireAdmin>
  );
}
