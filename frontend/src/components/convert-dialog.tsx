"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import type { SearchHit } from "@/lib/types/catalogue";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

interface LineDraft {
  hit: SearchHit;
  quantity: string;
  unit_price: string;
  discount_percent: string;
}

function VariantSearch({ onPick }: { onPick: (hit: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["catalogue", "search", q],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q } })).data,
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <Input value={q} placeholder="Add item: search product / variant…"
        aria-label="Search catalogue" onChange={(e) => setQ(e.target.value)} />
      {q.length >= 2 && data && (
        <ul className="absolute z-30 mt-1 max-h-48 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
          {data.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">No matches</li>
          )}
          {data.map((h) => (
            <li key={`${h.product_id}-${h.variant_id}`}>
              <button type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => { onPick(h); setQ(""); }}>
                {h.label} <span className="text-xs text-muted-foreground">({h.sku})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ConvertDialog({ orgId, orgName }: { orgId: string; orgName: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [poNumber, setPoNumber] = useState("");
  const [terms, setTerms] = useState("30");
  const [idemKey] = useState(newIdempotencyKey);

  const totals = useMemo(() => {
    let net = 0;
    for (const l of lines) {
      const gross = Number(l.quantity || 0) * Number(l.unit_price || 0);
      net += gross * (1 - Number(l.discount_percent || 0) / 100);
    }
    // Preview only; the server calculation (incl. tax) is authoritative.
    return { net };
  }, [lines]);

  const convert = useMutation({
    mutationFn: () =>
      api<{ organization: { id: string }; order: { order_number: string } }>(
        `/api/v1/prospects/${orgId}/convert-to-customer-order`,
        {
          method: "POST",
          idempotencyKey: idemKey,
          body: {
            items: lines.map((l) => ({
              product_variant_id: l.hit.variant_id,
              quantity: l.quantity,
              unit_price: l.unit_price,
              discount_percent: l.discount_percent || "0",
            })),
            customer_po_number: poNumber || null,
            payment_terms_days: Number(terms),
            is_direct_po: true,
          },
        },
      ),
    onSuccess: (resp) => {
      toast.success(
        `Converted to customer — first order ${resp.data.order.order_number} created`,
      );
      queryClient.invalidateQueries();
      setOpen(false);
      router.push(`/customers/${orgId}`);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Conversion failed"),
  });

  const valid = lines.length > 0 &&
    lines.every((l) => Number(l.quantity) > 0 && Number(l.unit_price) >= 0);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <ArrowRightCircle className="h-4 w-4" aria-hidden /> First order / convert
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>First order — convert {orgName} to customer</DialogTitle>
          <DialogDescription>
            One atomic step: the organization becomes a Customer, its prospect
            history is preserved and closed as Won, and the first order is created.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <VariantSearch
            onPick={(hit) =>
              setLines((prev) => [
                ...prev,
                { hit, quantity: "1", unit_price: "", discount_percent: "0" },
              ])
            }
          />

          {lines.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="w-24">Qty</TableHead>
                    <TableHead className="w-28">Rate (PKR)</TableHead>
                    <TableHead className="w-24">Disc %</TableHead>
                    <TableHead className="w-10" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {lines.map((l, i) => (
                    <TableRow key={`${l.hit.variant_id}-${i}`}>
                      <TableCell className="w-full min-w-32 whitespace-normal text-sm">{l.hit.label}</TableCell>
                      <TableCell>
                        <Input type="number" min="0.001" step="any" value={l.quantity}
                          className="w-20"
                          aria-label="Quantity"
                          onChange={(e) => setLines((prev) =>
                            prev.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" min="0" step="0.01" value={l.unit_price}
                          className="w-24"
                          aria-label="Unit price"
                          onChange={(e) => setLines((prev) =>
                            prev.map((x, j) => j === i ? { ...x, unit_price: e.target.value } : x))} />
                      </TableCell>
                      <TableCell>
                        <Input type="number" min="0" max="100" step="0.01" value={l.discount_percent}
                          className="w-20"
                          aria-label="Discount percent"
                          onChange={(e) => setLines((prev) =>
                            prev.map((x, j) => j === i ? { ...x, discount_percent: e.target.value } : x))} />
                      </TableCell>
                      <TableCell>
                        <Button type="button" variant="ghost" size="icon-sm"
                          aria-label="Remove line"
                          onClick={() => setLines((prev) => prev.filter((_, j) => j !== i))}>
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="cv-po">Customer PO number</Label>
              <Input id="cv-po" value={poNumber} onChange={(e) => setPoNumber(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cv-terms">Payment terms (days)</Label>
              <Input id="cv-terms" type="number" min="0" max="365" value={terms}
                onChange={(e) => setTerms(e.target.value)} />
            </div>
            <div className="flex items-end justify-end text-sm text-muted-foreground">
              Net preview: PKR {totals.net.toFixed(2)} + tax (server-calculated)
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button disabled={!valid || convert.isPending} onClick={() => convert.mutate()}>
            {convert.isPending ? "Converting…" : "Convert & create first order"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
