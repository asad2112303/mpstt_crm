"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Package, PackageX, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { BillingProduct, QuickProductPayload } from "@/lib/types/billing";
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
  const boxRef = useRef<HTMLDivElement>(null);

  const query = typedName.trim();
  const { data, isFetching } = useQuery({
    queryKey: ["billing-products", { query, onlyTracked, warehouseId }],
    queryFn: async () =>
      (
        await api<BillingProduct[]>("/api/v1/billing/products", {
          searchParams: {
            search: query || undefined,
            only_tracked: onlyTracked || undefined,
            warehouse_id: warehouseId,
          },
        })
      ).data,
    enabled: open && !adding,
  });

  useEffect(() => {
    function onClickAway(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
        setAdding(false);
      }
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  const results = data ?? [];
  const canCreate = query.length > 0 && !onlyTracked;

  return (
    <div className="relative" ref={boxRef}>
      <Input
        value={value?.label ?? typedName}
        placeholder={onlyTracked ? "Search stock…" : "Type or search a product…"}
        aria-label="Product"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          onTypedNameChange(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (results[highlight]) {
              onPick(results[highlight]);
              setOpen(false);
            } else if (canCreate) {
              setAdding(true);
            }
          } else if (e.key === "Escape") {
            setOpen(false);
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
                setAdding(false);
                setOpen(false);
              }}
            />
          ) : (
            <ul className="max-h-72 overflow-auto py-1" role="listbox">
              {isFetching && results.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted-foreground">Searching…</li>
              )}
              {results.map((p, i) => {
                const out = p.track_stock && Number(p.available ?? 0) <= 0;
                return (
                  <li key={p.product_variant_id} role="option" aria-selected={i === highlight}>
                    <button
                      type="button"
                      onMouseEnter={() => setHighlight(i)}
                      onClick={() => {
                        onPick(p);
                        setOpen(false);
                      }}
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
                        <span className="block truncate font-medium">{p.label}</span>
                        <span className="block text-xs text-muted-foreground">
                          {p.sku}
                          {p.category ? ` · ${p.category}` : ""}
                          {p.track_stock
                            ? ` · ${p.available} ${p.uom_code} available`
                            : " · not stock-tracked"}
                          {!p.has_cost && " · no cost on file"}
                        </span>
                      </span>
                      {out && (
                        <span className="shrink-0 rounded-full bg-destructive/15 px-2 py-0.5 text-xs text-destructive">
                          Out of stock
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
