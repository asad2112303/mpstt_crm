"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Package, PackageX, Plus, Search, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import {
  narrow,
  type BillingProduct, type CatalogueProduct, type CatalogueVariant,
  type QuickProductPayload,
} from "@/lib/types/billing";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** Selling units the business uses. Seeded by migration 0016. */
const UNITS = ["PCS", "PKT", "ROLL", "BOX", "SET", "DOZ", "KG", "LTR"];

/**
 * Swatch colours for the options people actually pick by eye.
 * The swatch is decoration: every option is also labelled and ticked when
 * selected, so colour is never the only way to tell them apart.
 */
const SWATCHES: Record<string, string> = {
  red: "#dc2626", yellow: "#eab308", black: "#171717", white: "#ffffff",
  blue: "#2563eb", green: "#16a34a", orange: "#ea580c", grey: "#6b7280",
  gray: "#6b7280", brown: "#92400e", pink: "#db2777", purple: "#7c3aed",
  transparent: "#e5e7eb", clear: "#e5e7eb",
};

function swatchFor(value: string): string | null {
  return SWATCHES[value.trim().toLowerCase()] ?? null;
}

function toBillingProduct(
  product: CatalogueProduct,
  variant: CatalogueVariant,
): BillingProduct {
  const options = product.steps
    .map((step) => variant.attributes[step.key])
    .filter(Boolean)
    .join(" · ");
  return {
    product_variant_id: variant.product_variant_id,
    product_id: product.product_id,
    sku: product.sku,
    variant_code: "",
    label: options ? `${product.name} — ${options}` : product.name,
    product_name: product.name,
    variant_name: variant.variant_name,
    category: product.category,
    attributes: variant.attributes,
    uom_code: variant.uom_code,
    tax_rate: product.tax_rate,
    track_stock: variant.track_stock,
    available: variant.available,
    on_hand: variant.available,
    suggested_price: variant.suggested_price,
    has_cost: variant.has_cost,
  };
}

// --------------------------------------------------------------------------

function NewProductForm({
  name,
  onCancel,
  onCreate,
}: {
  name: string;
  onCancel: () => void;
  onCreate: (payload: QuickProductPayload) => void;
}) {
  const [productName, setProductName] = useState(name);
  const [uom, setUom] = useState("PCS");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [colour, setColour] = useState("");
  const [size, setSize] = useState("");
  const [track, setTrack] = useState(false);
  const [opening, setOpening] = useState("");

  const valid = productName.trim().length > 0;

  return (
    <div className="space-y-4 p-4">
      <p className="text-sm text-muted-foreground">
        Only the name, unit and price are needed. It is saved to the catalogue
        so you can pick it next time.
      </p>

      <div className="space-y-1.5">
        <Label htmlFor="np-name">Product name</Label>
        <Input id="np-name" value={productName} autoFocus
          onChange={(e) => setProductName(e.target.value)} />
      </div>

      <div className="space-y-1.5">
        <Label>Unit</Label>
        <div className="flex flex-wrap gap-2">
          {UNITS.map((u) => (
            <button
              key={u}
              type="button"
              onClick={() => setUom(u)}
              aria-pressed={uom === u}
              className={cn(
                "min-w-14 rounded-lg border px-3 py-2 text-sm font-medium",
                uom === u
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card",
              )}
            >
              {u}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="np-price">Selling price</Label>
          <Input id="np-price" inputMode="decimal" value={price} placeholder="0.00"
            onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-cost">
            Purchase cost <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-cost" inputMode="decimal" value={cost} placeholder="Internal only"
            onChange={(e) => setCost(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-colour">
            Colour <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-colour" value={colour} onChange={(e) => setColour(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="np-size">
            Size / capacity <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-size" value={size} onChange={(e) => setSize(e.target.value)} />
        </div>
      </div>

      <label className="flex items-start gap-3 rounded-lg bg-muted/50 p-3 text-sm">
        <Checkbox checked={track} onCheckedChange={(v) => setTrack(v === true)} />
        <span>
          Track stock for this product
          <span className="mt-0.5 block text-xs text-muted-foreground">
            Off by default. Selling is never counted as stock received — if you
            turn this on, enter what is actually on the shelf.
          </span>
        </span>
      </label>

      {track && (
        <div className="space-y-1.5">
          <Label htmlFor="np-open">Opening stock on hand</Label>
          <Input id="np-open" inputMode="decimal" value={opening} placeholder="0"
            onChange={(e) => setOpening(e.target.value)} />
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <Button variant="outline" className="flex-1" onClick={onCancel}>Cancel</Button>
        <Button
          className="flex-1"
          disabled={!valid}
          onClick={() =>
            onCreate({
              name: productName.trim(),
              uom_code: uom,
              sale_price: price || null,
              purchase_cost: cost || null,
              colour: colour || null,
              size: size || null,
              track_stock: track,
              opening_quantity: track && opening ? opening : null,
            })
          }
        >
          <Check className="mr-1 h-4 w-4" aria-hidden /> Add to bill
        </Button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------

/**
 * Product picker.
 *
 * On a phone it takes the whole screen: the search field focuses itself, the
 * results are finger-sized rows, and options are chips and swatches rather
 * than a dropdown inside a dropdown. On a wide screen the same panel is
 * anchored under the trigger.
 */
export function ProductPicker({
  value,
  onlyTracked,
  warehouseId,
  onPick,
  onCreateNew,
}: {
  value?: BillingProduct | { label: string } | null;
  onlyTracked: boolean;
  warehouseId?: string;
  onPick: (product: BillingProduct) => void;
  onCreateNew: (name: string, payload: QuickProductPayload) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [product, setProduct] = useState<CatalogueProduct | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const searchRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const { data, isFetching, error } = useQuery({
    queryKey: ["billing-catalogue", { query, onlyTracked, warehouseId }],
    queryFn: async () =>
      (
        await api<CatalogueProduct[]>("/api/v1/billing/catalogue", {
          searchParams: {
            search: query.trim() || undefined,
            only_tracked: onlyTracked || undefined,
            warehouse_id: warehouseId,
            limit: 40,
          },
        })
      ).data,
    enabled: open && !adding,
  });

  // Focus the search as the picker opens, so typing can start immediately.
  useEffect(() => {
    if (open && !adding && !product) {
      const t = setTimeout(() => searchRef.current?.focus(), 60);
      return () => clearTimeout(t);
    }
  }, [open, adding, product]);

  // Close on outside click (desktop) and on Escape.
  useEffect(() => {
    if (!open) return;
    function away(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) close();
    }
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  function close() {
    setOpen(false);
    setAdding(false);
    setProduct(null);
    setChosen({});
  }

  const results = useMemo(() => data ?? [], [data]);
  const categories = useMemo(
    () => Array.from(new Set(results.map((p) => p.category).filter(Boolean))) as string[],
    [results],
  );
  const shown = category ? results.filter((p) => p.category === category) : results;
  const state = product ? narrow(product, chosen) : null;

  function choose(p: CatalogueProduct, next: Record<string, string>) {
    const result = narrow(p, next);
    if (result.variant) {
      onPick(toBillingProduct(p, result.variant));
      close();
      return;
    }
    setProduct(p);
    setChosen(next);
  }

  const title = product ? product.name : adding ? "New product" : "Choose product";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg border border-input bg-transparent px-3 py-2.5 text-left text-base md:text-sm",
          "min-h-11 md:min-h-8 hover:border-ring focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        )}
      >
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className={cn("min-w-0 flex-1 truncate", !value && "text-muted-foreground")}>
          {value?.label ?? (onlyTracked ? "Search stock…" : "Type or choose a product")}
        </span>
      </button>

      {open && (
        <>
          {/* Full-screen on a phone; a backdrop-anchored panel from lg up. */}
          <div
            className="fixed inset-0 z-50 bg-black/30 lg:bg-transparent"
            aria-hidden
            onClick={close}
          />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={cn(
              "fixed inset-0 z-50 flex flex-col bg-popover",
              "lg:absolute lg:inset-auto lg:mt-1 lg:max-h-[28rem] lg:w-[34rem] lg:rounded-lg lg:border lg:border-border lg:shadow-lg",
            )}
            style={{ paddingTop: "var(--safe-top)", paddingBottom: "var(--safe-bottom)" }}
          >
            {/* header */}
            <div className="flex items-center gap-2 border-b border-border p-3 lg:p-2">
              {(product || adding) && (
                <button
                  type="button"
                  aria-label="Back"
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md hover:bg-muted"
                  onClick={() => {
                    if (adding) setAdding(false);
                    else {
                      setProduct(null);
                      setChosen({});
                    }
                  }}
                >
                  <ArrowLeft className="h-5 w-5" aria-hidden />
                </button>
              )}
              <p className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</p>
              <button
                type="button"
                aria-label="Close"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md hover:bg-muted"
                onClick={close}
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>

            {adding ? (
              <div className="min-h-0 flex-1 overflow-y-auto">
                <NewProductForm
                  name={query.trim()}
                  onCancel={() => setAdding(false)}
                  onCreate={(payload) => {
                    onCreateNew(payload.name, payload);
                    close();
                  }}
                />
              </div>
            ) : product && state ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <p className="text-xs text-muted-foreground">
                  {product.sku}
                  {product.category ? ` · ${product.category}` : ""}
                </p>

                {Object.keys(state.applied).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {product.steps
                      .filter((s) => state.applied[s.key])
                      .map((s) => (
                        <button
                          key={s.key}
                          type="button"
                          onClick={() => {
                            const next = { ...chosen };
                            delete next[s.key];
                            setChosen(next);
                          }}
                          className="rounded-full border border-border bg-muted px-3 py-1.5 text-xs"
                        >
                          {s.label}: <strong>{state.applied[s.key]}</strong> ✕
                        </button>
                      ))}
                  </div>
                )}

                {state.step ? (
                  <div className="mt-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Choose {state.step.label.toLowerCase()}
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {state.options.map((option) => {
                        const matching = state.candidates.filter(
                          (v) => v.attributes[state.step!.key] === option,
                        );
                        const stock = matching.reduce(
                          (sum, v) => sum + Number(v.available ?? 0), 0,
                        );
                        const out = product.track_stock && stock <= 0;
                        const swatch = swatchFor(option);
                        return (
                          <button
                            key={option}
                            type="button"
                            onClick={() =>
                              choose(product, { ...chosen, [state.step!.key]: option })
                            }
                            className={cn(
                              "flex min-h-16 items-center gap-2 rounded-lg border p-3 text-left",
                              out
                                ? "border-border bg-muted/40 text-muted-foreground"
                                : "border-border bg-card active:border-primary",
                            )}
                          >
                            {swatch && (
                              <span
                                aria-hidden
                                className="h-6 w-6 shrink-0 rounded-full border border-border"
                                style={{ background: swatch }}
                              />
                            )}
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium">
                                {option}
                                {state.step!.unit ? ` ${state.step!.unit}` : ""}
                              </span>
                              {product.track_stock && (
                                <span className="block text-xs text-muted-foreground">
                                  {out ? "Out of stock" : `${stock} available`}
                                </span>
                              )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <ul className="mt-4 space-y-2">
                    {state.candidates.map((v) => (
                      <li key={v.product_variant_id}>
                        <button
                          type="button"
                          className="w-full rounded-lg border border-border p-3 text-left"
                          onClick={() => {
                            onPick(toBillingProduct(product, v));
                            close();
                          }}
                        >
                          <span className="block text-sm font-medium">{v.variant_name}</span>
                          <span className="block text-xs text-muted-foreground">
                            {v.track_stock
                              ? `${v.available} ${v.uom_code} available`
                              : v.uom_code}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <>
                <div className="space-y-2 border-b border-border p-3">
                  <div className="relative">
                    <Search
                      className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                      aria-hidden
                    />
                    <Input
                      ref={searchRef}
                      value={query}
                      className="pl-9"
                      placeholder="Search name, category or code…"
                      aria-label="Search products"
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>
                  {categories.length > 1 && (
                    <div className="no-min-target flex gap-1.5 overflow-x-auto pb-1">
                      <button
                        type="button"
                        onClick={() => setCategory(null)}
                        className={cn(
                          "shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium",
                          category === null
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-border bg-card",
                        )}
                      >
                        All
                      </button>
                      {categories.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => setCategory(c)}
                          className={cn(
                            "shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium",
                            category === c
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border bg-card",
                          )}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <ul className="min-h-0 flex-1 overflow-y-auto">
                  {error && (
                    <li className="p-4 text-sm text-destructive">
                      <p className="font-medium">Could not load products.</p>
                      <p className="mt-0.5 text-xs">
                        {error instanceof ApiError
                          ? `${error.message}${error.status >= 500 ? " (server error)" : ""}`
                          : "The server could not be reached."}
                      </p>
                    </li>
                  )}
                  {isFetching && shown.length === 0 && !error && (
                    <li className="p-4 text-sm text-muted-foreground">Searching…</li>
                  )}
                  {shown.map((p) => {
                    const stock = p.variants.reduce(
                      (sum, v) => sum + Number(v.available ?? 0), 0,
                    );
                    return (
                      <li key={p.product_id} className="border-b border-border last:border-0">
                        <button
                          type="button"
                          onClick={() => choose(p, {})}
                          className="flex w-full items-start gap-3 p-3 text-left active:bg-muted"
                        >
                          {p.track_stock ? (
                            <Package className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
                          ) : (
                            <PackageX
                              className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground"
                              aria-hidden
                            />
                          )}
                          <span className="min-w-0 flex-1">
                            <span className="block text-sm font-medium">{p.name}</span>
                            <span className="block text-xs text-muted-foreground">
                              {p.sku}
                              {p.category ? ` · ${p.category}` : ""}
                            </span>
                            <span className="mt-0.5 block text-xs text-muted-foreground">
                              {p.steps.length > 0
                                ? `Choose ${p.steps.map((s) => s.label.toLowerCase()).join(", ")}`
                                : "Ready to add"}
                              {p.track_stock ? ` · ${stock} in stock` : " · not stock-tracked"}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                  {shown.length === 0 && !isFetching && !error && (
                    <li className="p-4 text-sm text-muted-foreground">
                      {query ? "No matching product." : "Start typing to search."}
                    </li>
                  )}
                </ul>

                {!onlyTracked && (
                  <div className="border-t border-border p-3">
                    <Button variant="outline" className="w-full" onClick={() => setAdding(true)}>
                      <Plus className="mr-1.5 h-4 w-4" aria-hidden />
                      {query.trim() ? `Add “${query.trim()}” as new` : "Add a new product"}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}
