"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Package, PackageX, Plus } from "lucide-react";
import { api } from "@/lib/api";
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

/** Units the business actually sells in; seeded by migration 0016. */
const UNITS = ["PCS", "PKT", "ROLL", "BOX", "SET", "DOZ", "KG", "LTR"];

function InlineNewProduct({
  name,
  onCancel,
  onCreate,
}: {
  name: string;
  onCancel: () => void;
  onCreate: (payload: QuickProductPayload) => void;
}) {
  const [uom, setUom] = useState("PCS");
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [colour, setColour] = useState("");
  const [size, setSize] = useState("");
  const [track, setTrack] = useState(false);
  const [opening, setOpening] = useState("");

  return (
    <div className="space-y-3 rounded-lg border border-primary/40 bg-card p-3 shadow-md">
      <p className="text-sm font-medium">
        Add “{name}” as a new product
      </p>
      <p className="text-xs text-muted-foreground">
        Only the unit and price are needed. It is saved to the catalogue so you
        can pick it next time.
      </p>

      <div className="grid gap-2 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="np-uom" className="text-xs">Unit</Label>
          <select
            id="np-uom"
            value={uom}
            onChange={(e) => setUom(e.target.value)}
            className="h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
          >
            {UNITS.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="np-price" className="text-xs">Selling price</Label>
          <Input id="np-price" inputMode="decimal" value={price}
            onChange={(e) => setPrice(e.target.value)} placeholder="0.00" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="np-cost" className="text-xs">
            Purchase cost <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-cost" inputMode="decimal" value={cost}
            onChange={(e) => setCost(e.target.value)} placeholder="Internal only" />
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="np-colour" className="text-xs">
            Colour <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-colour" value={colour} onChange={(e) => setColour(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="np-size" className="text-xs">
            Size / capacity <span className="text-muted-foreground">(optional)</span>
          </Label>
          <Input id="np-size" value={size} onChange={(e) => setSize(e.target.value)} />
        </div>
      </div>

      <label className="flex items-start gap-2 rounded-md bg-muted/50 p-2 text-sm">
        <Checkbox checked={track} onCheckedChange={(v) => setTrack(v === true)} />
        <span>
          Track stock for this product
          <span className="block text-xs text-muted-foreground">
            Off by default. Selling is never counted as stock received — if you
            turn this on, enter what is actually on the shelf.
          </span>
        </span>
      </label>

      {track && (
        <div className="space-y-1">
          <Label htmlFor="np-opening" className="text-xs">Opening stock on hand</Label>
          <Input id="np-opening" inputMode="decimal" value={opening}
            onChange={(e) => setOpening(e.target.value)} placeholder="0" />
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
        <Button
          size="sm"
          onClick={() =>
            onCreate({
              name,
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

/** Turn a resolved catalogue variant into the shape the bill line expects. */
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

/**
 * Pick a product, then narrow it down one option at a time.
 *
 * Typing searches products rather than every variant, so "Waste Bag" is one
 * row instead of twelve. Choosing it asks for the category's own attributes in
 * order — colour, then size — and a step with only one possible answer is
 * skipped rather than asked.
 */
export function ProductCombobox({
  value,
  typedName,
  onlyTracked,
  warehouseId,
  onPick,
  onCreateNew,
  onTypedNameChange,
}: {
  value?: { label: string };
  typedName: string;
  onlyTracked: boolean;
  warehouseId?: string;
  onPick: (product: BillingProduct) => void;
  onCreateNew: (name: string, payload: QuickProductPayload) => void;
  onTypedNameChange: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [product, setProduct] = useState<CatalogueProduct | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const boxRef = useRef<HTMLDivElement>(null);

  const query = typedName.trim();
  const { data, isFetching } = useQuery({
    queryKey: ["billing-catalogue", { query, onlyTracked, warehouseId }],
    queryFn: async () =>
      (
        await api<CatalogueProduct[]>("/api/v1/billing/catalogue", {
          searchParams: {
            search: query || undefined,
            only_tracked: onlyTracked || undefined,
            warehouse_id: warehouseId,
          },
        })
      ).data,
    enabled: open && !adding && !product,
  });

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        close();
      }
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  function close() {
    setOpen(false);
    setAdding(false);
    setProduct(null);
    setChosen({});
  }

  /** Take a choice; if it lands on a single variant, that is the pick. */
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

  const results = data ?? [];
  const canCreate = query.length > 0 && !onlyTracked;
  const state = product ? narrow(product, chosen) : null;

  return (
    <div className="relative" ref={boxRef}>
      <Input
        value={value?.label ?? typedName}
        placeholder={onlyTracked ? "Search stock…" : "Type a product name…"}
        aria-label="Product"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          onTypedNameChange(e.target.value);
          setOpen(true);
          setProduct(null);
          setChosen({});
          setHighlight(0);
        }}
        onKeyDown={(e) => {
          if (!open || product) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (results[highlight]) choose(results[highlight], {});
            else if (canCreate) setAdding(true);
          } else if (e.key === "Escape") {
            close();
          }
        }}
      />

      {open && (
        <div className="absolute z-30 mt-1 w-[min(34rem,90vw)] rounded-lg border border-border bg-popover shadow-lg">
          {adding ? (
            <InlineNewProduct
              name={query}
              onCancel={() => setAdding(false)}
              onCreate={(payload) => {
                onCreateNew(query, payload);
                close();
              }}
            />
          ) : product && state ? (
            /* step 2+: narrow the chosen product down */
            <div className="p-3">
              <div className="flex items-center gap-2 border-b border-border pb-2">
                <button
                  type="button"
                  aria-label="Back to product search"
                  className="rounded-md p-1 hover:bg-muted"
                  onClick={() => {
                    setProduct(null);
                    setChosen({});
                  }}
                >
                  <ArrowLeft className="h-4 w-4" aria-hidden />
                </button>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{product.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {product.sku}
                    {product.category ? ` · ${product.category}` : ""}
                  </span>
                </span>
              </div>

              {/* what has been chosen so far, each one undoable */}
              {Object.keys(state.applied).length > 0 && (
                <div className="flex flex-wrap gap-1 pt-2">
                  {product.steps
                    .filter((s) => state.applied[s.key])
                    .map((s) => (
                      <button
                        key={s.key}
                        type="button"
                        className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs hover:border-primary"
                        onClick={() => {
                          const next = { ...chosen };
                          delete next[s.key];
                          setChosen(next);
                        }}
                        title={`Change ${s.label.toLowerCase()}`}
                      >
                        {s.label}: <strong>{state.applied[s.key]}</strong> ×
                      </button>
                    ))}
                </div>
              )}

              {state.step ? (
                <div className="pt-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Choose {state.step.label.toLowerCase()}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {state.options.map((option) => {
                      // Stock shown per option, so a colour that is empty is
                      // obvious before it is chosen.
                      const matching = state.candidates.filter(
                        (v) => v.attributes[state.step!.key] === option,
                      );
                      const stock = matching.reduce(
                        (sum, v) => sum + Number(v.available ?? 0),
                        0,
                      );
                      const out = product.track_stock && stock <= 0;
                      return (
                        <button
                          key={option}
                          type="button"
                          onClick={() =>
                            choose(product, { ...chosen, [state.step!.key]: option })
                          }
                          className={cn(
                            "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                            out
                              ? "border-border bg-muted/40 text-muted-foreground"
                              : "border-border bg-card hover:border-primary hover:bg-muted",
                          )}
                        >
                          <span className="block font-medium">
                            {option}
                            {state.step!.unit ? ` ${state.step!.unit}` : ""}
                          </span>
                          {product.track_stock && (
                            <span className="block text-xs text-muted-foreground">
                              {out ? "Out of stock" : `${stock} available`}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : (
                /* several variants share the same options — pick explicitly */
                <ul className="max-h-60 overflow-auto pt-2">
                  {state.candidates.map((v) => (
                    <li key={v.product_variant_id}>
                      <button
                        type="button"
                        className="w-full rounded-md px-2 py-2 text-left text-sm hover:bg-muted"
                        onClick={() => {
                          onPick(toBillingProduct(product, v));
                          close();
                        }}
                      >
                        <span className="block font-medium">{v.variant_name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {v.track_stock ? `${v.available} ${v.uom_code} available` : v.uom_code}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            /* step 1: find the product */
            <ul className="max-h-72 overflow-auto py-1" role="listbox">
              {isFetching && results.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted-foreground">Searching…</li>
              )}
              {results.map((p, i) => {
                const stock = p.variants.reduce(
                  (sum, v) => sum + Number(v.available ?? 0),
                  0,
                );
                return (
                  <li key={p.product_id} role="option" aria-selected={i === highlight}>
                    <button
                      type="button"
                      onMouseEnter={() => setHighlight(i)}
                      onClick={() => choose(p, {})}
                      className={cn(
                        "flex w-full items-start gap-2 px-3 py-2 text-left text-sm",
                        i === highlight && "bg-muted",
                      )}
                    >
                      {p.track_stock ? (
                        <Package className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                      ) : (
                        <PackageX
                          className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                          aria-hidden
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{p.name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {p.sku}
                          {p.category ? ` · ${p.category}` : ""}
                          {p.steps.length > 0
                            ? ` · choose ${p.steps.map((s) => s.label.toLowerCase()).join(", ")}`
                            : ""}
                          {p.track_stock ? ` · ${stock} in stock` : " · not stock-tracked"}
                        </span>
                      </span>
                      {p.steps.length > 0 && (
                        <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-xs text-secondary-foreground">
                          {p.variants.length} options
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
              {results.length === 0 && !isFetching && (
                <li className="px-3 py-2 text-sm text-muted-foreground">
                  {query ? "No matching product." : "Start typing to search."}
                </li>
              )}
              {canCreate && (
                <li className="border-t border-border">
                  <button
                    type="button"
                    onClick={() => setAdding(true)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium text-primary hover:bg-muted"
                  >
                    <Plus className="h-4 w-4" aria-hidden />
                    Add “{query}” as a new product
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
