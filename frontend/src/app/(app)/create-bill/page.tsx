"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, Copy, FileText, Package, PackageX, Plus, Save, Trash2, Zap,
} from "lucide-react";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import {
  lineAmounts, pkr, pkrExact,
  type BillingCustomer, type BillingMode, type DraftLine, type Invoice,
} from "@/lib/types/billing";
import { CustomerCombobox } from "@/components/billing/customer-combobox";
import { ProductCombobox } from "@/components/billing/product-combobox";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

function blankLine(): DraftLine {
  return {
    key: crypto.randomUUID(),
    typedName: "",
    description: "",
    uom_code: "PCS",
    quantity: "1",
    unit_price: "",
    discount_percent: "0",
    tax_rate: "0",
    unit_cost: "",
  };
}

function CreateBill() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<BillingMode>(
    params.get("mode") === "stock" ? "stock" : "quick",
  );

  const [walkIn, setWalkIn] = useState(true);
  const [customer, setCustomer] = useState<BillingCustomer | null>(null);
  const [walkInName, setWalkInName] = useState("");
  const [contactPerson, setContactPerson] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [billingAddress, setBillingAddress] = useState("");
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [reference, setReference] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [notes, setNotes] = useState("");
  const [termsNote, setTermsNote] = useState("");

  const [discountType, setDiscountType] = useState<"" | "percent" | "amount">("");
  const [discountValue, setDiscountValue] = useState("");
  const [delivery, setDelivery] = useState("");

  const [lines, setLines] = useState<DraftLine[]>([blankLine()]);
  const [amountPaid, setAmountPaid] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");

  function patchLine(key: string, patch: Partial<DraftLine>) {
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  const totals = useMemo(() => {
    let gross = 0, lineDiscount = 0, tax = 0, linesTotal = 0;
    for (const line of lines) {
      if (!line.product && !line.newProduct) continue;
      const a = lineAmounts(line);
      gross += a.gross;
      lineDiscount += a.discount;
      tax += a.tax;
      linesTotal += a.total;
    }
    const value = Number(discountValue || 0);
    const overall =
      discountType === "percent" ? (linesTotal * value) / 100
      : discountType === "amount" ? value
      : 0;
    const capped = Math.min(overall, linesTotal);
    const grand = linesTotal - capped + Number(delivery || 0);
    return {
      gross, lineDiscount, tax, linesTotal,
      overall: capped,
      overflowed: overall > linesTotal,
      grand,
    };
  }, [lines, discountType, discountValue, delivery]);

  const readyLines = lines.filter((l) => l.product || l.newProduct);
  const shortages = readyLines.filter(
    (l) =>
      l.product?.track_stock &&
      Number(l.product.available ?? 0) < Number(l.quantity || 0),
  );
  const missingCost = readyLines.filter(
    (l) => !l.unit_cost && !(l.product?.has_cost ?? false) && !l.newProduct?.purchase_cost,
  );

  function buildPayload() {
    return {
      walk_in: walkIn,
      walk_in_name: walkIn ? walkInName || null : null,
      organization_id: walkIn ? null : customer?.id ?? null,
      invoice_date: invoiceDate || null,
      due_date: dueDate || null,
      reference_number: reference || null,
      contact_person: contactPerson || null,
      contact_phone: contactPhone || null,
      billing_address: billingAddress || null,
      delivery_address: deliveryAddress || null,
      notes: notes || null,
      payment_terms_note: termsNote || null,
      overall_discount_type: discountType || null,
      overall_discount_value: discountValue || "0",
      delivery_charge: delivery || "0",
      items: readyLines.map((l) => ({
        product_variant_id: l.product?.product_variant_id ?? null,
        new_product: l.product ? null : l.newProduct,
        quantity: l.quantity || "0",
        unit_price: l.unit_price || "0",
        discount_percent: l.discount_percent || "0",
        tax_rate: l.tax_rate || "0",
        description: l.description || null,
        unit_cost: l.unit_cost || null,
      })),
    };
  }

  function validate(): string | null {
    if (readyLines.length === 0) return "Add at least one product.";
    if (!walkIn && !customer) return "Choose a customer, or switch to walk-in.";
    if (readyLines.some((l) => Number(l.quantity || 0) <= 0))
      return "Every line needs a quantity above zero.";
    if (totals.overflowed) return "The discount is larger than the invoice total.";
    return null;
  }

  const saveDraft = useMutation({
    mutationFn: async () =>
      (await api<Invoice>("/api/v1/billing/invoices", {
        method: "POST", body: buildPayload(),
      })).data,
    onSuccess: (invoice) => {
      toast.success("Draft saved. Stock is untouched until you finalize.");
      router.push(`/invoices/${invoice.id}`);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not save the draft."),
  });

  const finalize = useMutation({
    mutationFn: async () => {
      const draft = (await api<Invoice>("/api/v1/billing/invoices", {
        method: "POST", body: buildPayload(),
      })).data;
      return (
        await api<Invoice>(`/api/v1/billing/invoices/${draft.id}/finalize`, {
          method: "POST",
          idempotencyKey: newIdempotencyKey(),
          body: {
            amount_paid: amountPaid || null,
            payment_method: paymentMethod,
          },
        })
      ).data;
    },
    onSuccess: (invoice) => {
      toast.success(`${invoice.invoice_number} finalized.`);
      router.push(`/invoices/${invoice.id}`);
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not finalize the bill."),
  });

  const busy = saveDraft.isPending || finalize.isPending;
  const problem = validate();

  function attempt(run: () => void) {
    const issue = validate();
    if (issue) {
      toast.error(issue);
      return;
    }
    run();
  }

  return (
    <main className="space-y-5 p-6 pb-32">
      <PageHeader
        title="Create bill"
        description="Pick products from stock, or just type what you are selling. Nothing moves until you finalize."
      />

      {/* mode */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Billing mode">
        {(
          [
            ["quick", "Quick Bill", Zap, "Type anything. Products are saved as you go."],
            ["stock", "Sell from Stock", Package, "Only stock-tracked products."],
          ] as [BillingMode, string, typeof Zap, string][]
        ).map(([value, label, Icon, hint]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={cn(
              "flex-1 rounded-lg border p-3 text-left transition-colors sm:flex-none sm:w-64",
              mode === value
                ? "border-primary bg-primary/5 ring-1 ring-primary"
                : "border-border bg-card hover:bg-muted",
            )}
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
          </button>
        ))}
      </div>

      {/* customer */}
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Bill to</h2>
          <div className="flex gap-1" role="group" aria-label="Customer type">
            {[
              [true, "Walk-in"],
              [false, "Saved customer"],
            ].map(([value, label]) => (
              <button
                key={String(value)}
                onClick={() => setWalkIn(value as boolean)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium",
                  walkIn === value
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-card hover:bg-muted",
                )}
              >
                {label as string}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="cust">{walkIn ? "Customer name (optional)" : "Customer"}</Label>
            {walkIn ? (
              <Input id="cust" value={walkInName} placeholder="Walk-in Customer"
                onChange={(e) => setWalkInName(e.target.value)} />
            ) : (
              <CustomerCombobox selected={customer} onSelect={setCustomer} />
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="contact">Contact person</Label>
            <Input id="contact" value={contactPerson}
              onChange={(e) => setContactPerson(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="phone">Phone</Label>
            <Input id="phone" value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ref">PO / reference</Label>
            <Input id="ref" value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="idate">Invoice date</Label>
            <Input id="idate" type="date" value={invoiceDate}
              onChange={(e) => setInvoiceDate(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ddate">Due date</Label>
            <Input id="ddate" type="date" value={dueDate}
              onChange={(e) => setDueDate(e.target.value)} />
          </div>
          <div className="space-y-1 sm:col-span-2 lg:col-span-1">
            <Label htmlFor="baddr">Billing address</Label>
            <Textarea id="baddr" className="min-h-9" value={billingAddress}
              onChange={(e) => setBillingAddress(e.target.value)} />
          </div>
          <div className="space-y-1 sm:col-span-2 lg:col-span-2">
            <Label htmlFor="daddr">Delivery address (optional)</Label>
            <Textarea id="daddr" className="min-h-9" value={deliveryAddress}
              onChange={(e) => setDeliveryAddress(e.target.value)} />
          </div>
        </div>
        {walkIn && (
          <p className="mt-2 text-xs text-muted-foreground">
            A walk-in sale must be paid in full. Choose a saved customer to leave
            a balance outstanding.
          </p>
        )}
      </section>

      {/* lines */}
      <section className="rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between border-b border-border p-3">
          <h2 className="text-sm font-semibold">Items</h2>
          <Button variant="outline" size="sm" onClick={() => setLines((l) => [...l, blankLine()])}>
            <Plus className="mr-1 h-4 w-4" aria-hidden /> Add line
          </Button>
        </div>

        <div className="divide-y divide-border">
          {lines.map((line, index) => {
            const a = lineAmounts(line);
            const source = line.product
              ? line.product.track_stock ? "stock" : "quick_bill"
              : line.newProduct
                ? line.newProduct.track_stock ? "stock" : "quick_bill"
                : null;
            const short =
              line.product?.track_stock &&
              Number(line.product.available ?? 0) < Number(line.quantity || 0);

            return (
              <div key={line.key} className="grid gap-2 p-3 lg:grid-cols-12">
                <div className="lg:col-span-4">
                  <Label className="text-xs lg:sr-only">Product</Label>
                  <ProductCombobox
                    value={line.product ? { label: line.product.label } : undefined}
                    typedName={line.typedName}
                    onlyTracked={mode === "stock"}
                    onTypedNameChange={(name) =>
                      patchLine(line.key, {
                        typedName: name,
                        product: undefined,
                        newProduct: undefined,
                      })
                    }
                    onPick={(p) =>
                      patchLine(line.key, {
                        product: p,
                        newProduct: undefined,
                        typedName: p.label,
                        uom_code: p.uom_code ?? "PCS",
                        tax_rate: p.tax_rate,
                        unit_price:
                          Number(p.suggested_price) > 0 ? p.suggested_price : line.unit_price,
                      })
                    }
                    onCreateNew={(name, payload) =>
                      patchLine(line.key, {
                        typedName: name,
                        product: undefined,
                        newProduct: payload,
                        uom_code: payload.uom_code,
                        unit_price: payload.sale_price ?? line.unit_price,
                        unit_cost: payload.purchase_cost ?? "",
                      })
                    }
                  />
                  {source && (
                    <span className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground">
                      {source === "stock" ? (
                        <><Package className="h-3 w-3" aria-hidden /> From stock</>
                      ) : (
                        <><PackageX className="h-3 w-3" aria-hidden /> Quick Bill — no stock</>
                      )}
                      {line.newProduct && " · new product"}
                    </span>
                  )}
                </div>

                <div className="lg:col-span-1">
                  <Label className="text-xs lg:sr-only">Unit</Label>
                  <Input value={line.uom_code} aria-label="Unit"
                    onChange={(e) => patchLine(line.key, { uom_code: e.target.value })} />
                </div>
                <div className="lg:col-span-1">
                  <Label className="text-xs lg:sr-only">Qty</Label>
                  <Input inputMode="decimal" value={line.quantity} aria-label="Quantity"
                    className={cn(short && "border-destructive")}
                    onChange={(e) => patchLine(line.key, { quantity: e.target.value })} />
                </div>
                <div className="lg:col-span-2">
                  <Label className="text-xs lg:sr-only">Rate</Label>
                  <Input inputMode="decimal" value={line.unit_price} aria-label="Unit price"
                    placeholder="0.00"
                    onChange={(e) => patchLine(line.key, { unit_price: e.target.value })} />
                </div>
                <div className="lg:col-span-1">
                  <Label className="text-xs lg:sr-only">Disc %</Label>
                  <Input inputMode="decimal" value={line.discount_percent} aria-label="Discount percent"
                    onChange={(e) => patchLine(line.key, { discount_percent: e.target.value })} />
                </div>
                <div className="lg:col-span-1">
                  <Label className="text-xs lg:sr-only">Tax %</Label>
                  <Input inputMode="decimal" value={line.tax_rate} aria-label="Tax rate"
                    onChange={(e) => patchLine(line.key, { tax_rate: e.target.value })} />
                </div>
                <div className="flex items-end justify-between gap-2 lg:col-span-2">
                  <span className="text-sm font-medium tabular-nums">{pkrExact(a.total)}</span>
                  <span className="flex gap-1">
                    <Button variant="ghost" size="icon-sm" aria-label="Duplicate line"
                      onClick={() =>
                        setLines((cur) => {
                          const copy = { ...line, key: crypto.randomUUID() };
                          const next = [...cur];
                          next.splice(index + 1, 0, copy);
                          return next;
                        })
                      }>
                      <Copy className="h-4 w-4" aria-hidden />
                    </Button>
                    <Button variant="ghost" size="icon-sm" aria-label="Remove line"
                      disabled={lines.length === 1}
                      onClick={() => setLines((cur) => cur.filter((l) => l.key !== line.key))}>
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  </span>
                </div>

                {short && (
                  <p className="text-xs text-destructive lg:col-span-12">
                    Only {line.product?.available} {line.product?.uom_code} available.
                    Reduce the quantity, receive stock, or sell it as a Quick Bill line.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* totals + payment */}
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 rounded-lg border border-border bg-card p-4 lg:col-span-2">
          <h2 className="text-sm font-semibold">Adjustments</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="dtype">Overall discount</Label>
              <select
                id="dtype"
                value={discountType}
                onChange={(e) => setDiscountType(e.target.value as "" | "percent" | "amount")}
                className="h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
              >
                <option value="">None</option>
                <option value="percent">Percentage</option>
                <option value="amount">Fixed amount</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="dval">Discount value</Label>
              <Input id="dval" inputMode="decimal" value={discountValue}
                disabled={!discountType}
                onChange={(e) => setDiscountValue(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="deliv">Delivery charge</Label>
              <Input id="deliv" inputMode="decimal" value={delivery}
                onChange={(e) => setDelivery(e.target.value)} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="notes">Notes on the invoice</Label>
              <Textarea id="notes" className="min-h-9" value={notes}
                onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="terms">Payment terms note</Label>
              <Textarea id="terms" className="min-h-9" value={termsNote}
                onChange={(e) => setTermsNote(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
          <Row label="Subtotal" value={pkrExact(totals.gross)} />
          {totals.lineDiscount > 0 && (
            <Row label="Line discounts" value={`-${pkrExact(totals.lineDiscount)}`} />
          )}
          {totals.tax > 0 && <Row label="Tax" value={pkrExact(totals.tax)} />}
          {totals.overall > 0 && (
            <Row label="Overall discount" value={`-${pkrExact(totals.overall)}`} />
          )}
          {Number(delivery || 0) > 0 && (
            <Row label="Delivery" value={pkrExact(Number(delivery))} />
          )}
          <div className="flex items-center justify-between border-t border-border pt-2 text-base font-semibold">
            <span>Total</span>
            <span className="tabular-nums">{pkr(totals.grand)}</span>
          </div>

          <div className="space-y-1 pt-2">
            <Label htmlFor="paid">Amount paid now</Label>
            <Input id="paid" inputMode="decimal" value={amountPaid}
              placeholder="0.00"
              onChange={(e) => setAmountPaid(e.target.value)} />
            <button
              type="button"
              className="text-xs text-primary hover:underline"
              onClick={() => setAmountPaid(totals.grand.toFixed(2))}
            >
              Pay in full
            </button>
          </div>
          <div className="space-y-1">
            <Label htmlFor="method">Method</Label>
            <select
              id="method"
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              className="h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
            >
              <option value="cash">Cash</option>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cheque">Cheque</option>
              <option value="online">Online</option>
              <option value="other">Other</option>
            </select>
          </div>
          <Row
            label="Balance after payment"
            value={pkrExact(Math.max(totals.grand - Number(amountPaid || 0), 0))}
          />
        </div>
      </section>

      {(shortages.length > 0 || missingCost.length > 0) && (
        <div className="space-y-2">
          {shortages.length > 0 && (
            <p className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {shortages.length} line{shortages.length > 1 ? "s" : ""} exceed available
              stock. Finalizing will be refused until the quantity fits.
            </p>
          )}
          {missingCost.length > 0 && (
            <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {missingCost.length} line{missingCost.length > 1 ? "s" : ""} have no
              purchase cost, so profit on this bill will be reported as incomplete.
            </p>
          )}
        </div>
      )}

      {/* sticky actions */}
      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card/95 p-3 backdrop-blur lg:pl-60">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-3">
          <span className="text-sm">
            <span className="text-muted-foreground">Total </span>
            <span className="text-lg font-semibold tabular-nums">{pkr(totals.grand)}</span>
            {readyLines.length > 0 && (
              <Badge variant="outline" className="ml-2">
                {readyLines.length} item{readyLines.length > 1 ? "s" : ""}
              </Badge>
            )}
          </span>
          <span className="flex gap-2">
            <Button variant="outline" disabled={busy}
              onClick={() => attempt(() => saveDraft.mutate())}>
              <Save className="mr-1.5 h-4 w-4" aria-hidden />
              Save draft
            </Button>
            <Button disabled={busy || !!problem}
              onClick={() => attempt(() => finalize.mutate())}>
              <FileText className="mr-1.5 h-4 w-4" aria-hidden />
              {finalize.isPending ? "Finalizing…" : "Finalize & bill"}
            </Button>
          </span>
        </div>
      </div>
    </main>
  );
}

/** useSearchParams needs a boundary, or the page cannot be prerendered. */
export default function CreateBillPage() {
  return (
    <Suspense
      fallback={
        <main className="space-y-4 p-6">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </main>
      }
    >
      <CreateBill />
    </Suspense>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
