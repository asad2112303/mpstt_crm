"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronDown,
  Copy, Minus, Package, PackageX, Plus, Save, Trash2, Zap,
} from "lucide-react";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import {
  lineAmounts, pkr, pkrExact,
  type BillingCustomer, type BillingMode, type BillingProduct,
  type DraftLine, type Invoice, type QuickProductPayload,
} from "@/lib/types/billing";
import { CustomerCombobox } from "@/components/billing/customer-combobox";
import { InvoiceActions } from "@/components/billing/invoice-share";
import { ProductPicker } from "@/components/billing/product-picker";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type Step = 1 | 2 | 3;
const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: "Customer" },
  { n: 2, label: "Products" },
  { n: 3, label: "Review" },
];

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

/** Quantity with tap targets either side, and the keypad for typing. */
function QuantityStepper({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  function bump(by: number) {
    const current = Number(value || 0);
    const next = Math.max(0, Math.round((current + by) * 1000) / 1000);
    onChange(String(next));
  }
  return (
    <div className="flex items-stretch">
      <button
        type="button"
        aria-label="Decrease quantity"
        disabled={disabled}
        onClick={() => bump(-1)}
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-l-lg border border-r-0 border-input disabled:opacity-50 md:h-8 md:w-8"
      >
        <Minus className="h-4 w-4" aria-hidden />
      </button>
      <Input
        value={value}
        // Decimals matter: things sold by the kilogram are not whole numbers.
        inputMode="decimal"
        aria-label="Quantity"
        className="h-11 w-16 rounded-none text-center md:h-8 md:w-14"
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        type="button"
        aria-label="Increase quantity"
        disabled={disabled}
        onClick={() => bump(1)}
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-r-lg border border-l-0 border-input disabled:opacity-50 md:h-8 md:w-8"
      >
        <Plus className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={cn("flex items-center justify-between", strong && "text-base font-semibold")}>
      <span className={cn(!strong && "text-muted-foreground")}>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}

function CreateBill() {
  const params = useSearchParams();
  const [mode, setMode] = useState<BillingMode>(
    params.get("mode") === "stock" ? "stock" : "quick",
  );
  const [step, setStep] = useState<Step>(1);

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
  const [moreDetails, setMoreDetails] = useState(false);

  const [discountType, setDiscountType] = useState<"" | "percent" | "amount">("");
  const [discountValue, setDiscountValue] = useState("");
  const [delivery, setDelivery] = useState("");

  const [lines, setLines] = useState<DraftLine[]>([blankLine()]);
  const [amountPaid, setAmountPaid] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");

  const [draftId, setDraftId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [issued, setIssued] = useState<Invoice | null>(null);

  function patchLine(key: string, patch: Partial<DraftLine>) {
    setLines((current) => current.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  const readyLines = useMemo(
    () => lines.filter((l) => l.product || l.newProduct),
    [lines],
  );

  const totals = useMemo(() => {
    let gross = 0, lineDiscount = 0, tax = 0, linesTotal = 0;
    for (const line of readyLines) {
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
    return {
      gross, lineDiscount, tax, linesTotal,
      overall: capped,
      overflowed: overall > linesTotal,
      grand: linesTotal - capped + Number(delivery || 0),
    };
  }, [readyLines, discountType, discountValue, delivery]);

  const shortages = readyLines.filter(
    (l) => l.product?.track_stock && Number(l.product.available ?? 0) < Number(l.quantity || 0),
  );
  const missingCost = readyLines.filter(
    (l) => !l.unit_cost && !(l.product?.has_cost ?? false) && !l.newProduct?.purchase_cost,
  );

  const buildPayload = useCallback(() => ({
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
  }), [walkIn, walkInName, customer, invoiceDate, dueDate, reference, contactPerson,
       contactPhone, billingAddress, deliveryAddress, notes, termsNote, discountType,
       discountValue, delivery, readyLines]);

  function validate(): string | null {
    if (readyLines.length === 0) return "Add at least one product.";
    if (!walkIn && !customer) return "Choose a customer, or switch to walk-in.";
    if (readyLines.some((l) => Number(l.quantity || 0) <= 0))
      return "Every line needs a quantity above zero.";
    if (readyLines.some((l) => l.unit_price === "")) return "Every line needs a price.";
    if (totals.overflowed) return "The discount is larger than the invoice total.";
    return null;
  }

  const canSaveDraft = readyLines.length > 0 && (walkIn || !!customer);

  // --- autosave -----------------------------------------------------------
  // A draft is only worth keeping once it has a line and a customer decision,
  // so an abandoned empty form never leaves a record behind. New products are
  // created server-side on first save, so after that the draft is re-sent by
  // id rather than duplicating them.
  const saving = useRef(false);
  const dirty = useRef(false);

  useEffect(() => {
    if (issued) return;
    dirty.current = true;
  }, [buildPayload, issued]);

  useEffect(() => {
    if (issued || !canSaveDraft) return;
    const timer = setTimeout(async () => {
      if (saving.current || !dirty.current) return;
      saving.current = true;
      dirty.current = false;
      setSaveState("saving");
      try {
        const body = buildPayload();
        const resp = draftId
          ? await api<Invoice>(`/api/v1/billing/invoices/${draftId}`, { method: "PUT", body })
          : await api<Invoice>("/api/v1/billing/invoices", { method: "POST", body });
        setDraftId(resp.data.id);
        // Lines the server materialised now have real ids; keep editing the
        // local copy, which is what the next PUT replaces wholesale.
        setSaveState("saved");
      } catch {
        // Autosave must never interrupt: the form keeps everything typed and
        // the indicator says it has not saved.
        dirty.current = true;
        setSaveState("error");
      } finally {
        saving.current = false;
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [buildPayload, canSaveDraft, draftId, issued]);

  // --- submit -------------------------------------------------------------
  const [idemKey] = useState(newIdempotencyKey);

  const saveDraft = useMutation({
    mutationFn: async () => {
      const body = buildPayload();
      const resp = draftId
        ? await api<Invoice>(`/api/v1/billing/invoices/${draftId}`, { method: "PUT", body })
        : await api<Invoice>("/api/v1/billing/invoices", { method: "POST", body });
      return resp.data;
    },
    onSuccess: (invoice) => {
      setDraftId(invoice.id);
      setSaveState("saved");
      toast.success("Draft saved. Stock is untouched until you finalize.");
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not save the draft."),
  });

  const finalize = useMutation({
    mutationFn: async () => {
      const body = buildPayload();
      const draft = draftId
        ? (await api<Invoice>(`/api/v1/billing/invoices/${draftId}`, { method: "PUT", body })).data
        : (await api<Invoice>("/api/v1/billing/invoices", { method: "POST", body })).data;
      setDraftId(draft.id);
      return (
        await api<Invoice>(`/api/v1/billing/invoices/${draft.id}/finalize`, {
          method: "POST",
          // One key for the life of this form, so a double tap or a retry
          // after a dropped connection cannot bill twice.
          idempotencyKey: idemKey,
          body: { amount_paid: amountPaid || null, payment_method: paymentMethod },
        })
      ).data;
    },
    // Only a confirmed server response marks the bill finalized.
    onSuccess: (invoice) => setIssued(invoice),
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

  // ------------------------------------------------------------------ done
  if (issued) {
    return (
      <main className="mx-auto max-w-lg space-y-5 p-4 sm:p-6">
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-5 text-center">
          <CheckCircle2 className="mx-auto h-10 w-10 text-primary" aria-hidden />
          <h1 className="mt-2 text-lg font-semibold">{issued.invoice_number}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Finalized · {pkr(issued.grand_total)}
          </p>
          <p className="mt-1 text-sm">
            {Number(issued.outstanding) > 0 ? (
              <>Balance due <strong>{pkrExact(issued.outstanding)}</strong></>
            ) : (
              <span className="text-primary">Paid in full</span>
            )}
          </p>
          {issued.stock?.stock_moved && (
            <p className="mt-2 text-xs text-muted-foreground">
              Stock deducted for {issued.stock.lines_stocked} tracked line
              {issued.stock.lines_stocked === 1 ? "" : "s"}.
            </p>
          )}
        </div>

        <InvoiceActions
          invoiceId={issued.id}
          invoiceNumber={issued.invoice_number ?? "invoice"}
        />

        <div className="grid gap-2">
          <Button variant="outline" render={<Link href={`/invoices/${issued.id}`} />}>
            View invoice
          </Button>
          <Button render={<Link href="/create-bill" />} onClick={() => window.location.reload()}>
            <Zap className="mr-1.5 h-4 w-4" aria-hidden /> New bill
          </Button>
        </div>
      </main>
    );
  }

  // ------------------------------------------------------------------ form
  const stepVisible = (n: Step) => (step === n ? "" : "max-lg:hidden");

  return (
    <main className="space-y-4 p-4 sm:p-6">
      <div className="hidden lg:block">
        <PageHeader
          title="Create bill"
          description="Pick products from stock, or just type what you are selling. Nothing moves until you finalize."
        />
      </div>

      {/* mobile progress */}
      <div className="lg:hidden">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Create bill</h1>
          <SaveIndicator state={saveState} />
        </div>
        <ol className="mt-3 flex gap-1.5" aria-label="Progress">
          {STEPS.map((s) => (
            <li key={s.n} className="flex-1">
              <button
                type="button"
                // Earlier steps stay reachable; nothing typed is lost moving
                // between them because it all lives in one form state.
                onClick={() => setStep(s.n)}
                aria-current={step === s.n ? "step" : undefined}
                className="w-full text-left"
              >
                <span
                  className={cn(
                    "block h-1 rounded-full",
                    s.n <= step ? "bg-primary" : "bg-muted",
                  )}
                />
                <span
                  className={cn(
                    "mt-1 block text-xs",
                    s.n === step ? "font-semibold text-foreground" : "text-muted-foreground",
                  )}
                >
                  {s.n}. {s.label}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </div>

      {/* ---------------------------------------------------------- step 1 */}
      <section className={cn("space-y-4", stepVisible(1))}>
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["quick", "Quick Bill", Zap, "Type anything. Products are saved as you go."],
              ["stock", "From Stock", Package, "Choose from what you hold."],
            ] as [BillingMode, string, typeof Zap, string][]
          ).map(([value, label, Icon, hint]) => (
            <button
              key={value}
              onClick={() => setMode(value)}
              aria-pressed={mode === value}
              className={cn(
                "rounded-lg border p-3 text-left",
                mode === value
                  ? "border-primary bg-primary/5 ring-1 ring-primary"
                  : "border-border bg-card",
              )}
            >
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Icon className="h-4 w-4" aria-hidden />
                {label}
                {mode === value && <Check className="ml-auto h-4 w-4" aria-hidden />}
              </span>
              <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
            </button>
          ))}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Bill to</h2>
            <div className="flex gap-1" role="group" aria-label="Customer type">
              {([[true, "Walk-in"], [false, "Saved customer"]] as [boolean, string][]).map(
                ([value, label]) => (
                  <button
                    key={String(value)}
                    onClick={() => setWalkIn(value)}
                    aria-pressed={walkIn === value}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs font-medium",
                      walkIn === value
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-card",
                    )}
                  >
                    {label}
                  </button>
                ),
              )}
            </div>
          </div>

          <div className="mt-3 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="cust">{walkIn ? "Customer name (optional)" : "Customer"}</Label>
              {walkIn ? (
                <Input id="cust" value={walkInName} placeholder="Walk-in Customer"
                  onChange={(e) => setWalkInName(e.target.value)} />
              ) : (
                <CustomerCombobox selected={customer} onSelect={setCustomer} />
              )}
            </div>

            <button
              type="button"
              onClick={() => setMoreDetails((v) => !v)}
              aria-expanded={moreDetails}
              className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-sm"
            >
              More details
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", moreDetails && "rotate-180")}
                aria-hidden
              />
            </button>

            {moreDetails && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="contact">Contact person</Label>
                  <Input id="contact" value={contactPerson}
                    onChange={(e) => setContactPerson(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="phone">Phone</Label>
                  <Input id="phone" type="tel" inputMode="tel" autoComplete="tel"
                    value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ref">PO / reference</Label>
                  <Input id="ref" value={reference} onChange={(e) => setReference(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="idate">Invoice date</Label>
                  <Input id="idate" type="date" value={invoiceDate}
                    onChange={(e) => setInvoiceDate(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ddate">Due date</Label>
                  <Input id="ddate" type="date" value={dueDate}
                    onChange={(e) => setDueDate(e.target.value)} />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="baddr">Billing address</Label>
                  <Textarea id="baddr" value={billingAddress}
                    onChange={(e) => setBillingAddress(e.target.value)} />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="daddr">Delivery address</Label>
                  <Textarea id="daddr" value={deliveryAddress}
                    onChange={(e) => setDeliveryAddress(e.target.value)} />
                </div>
              </div>
            )}

            {walkIn && (
              <p className="text-xs text-muted-foreground">
                A walk-in sale must be paid in full. Choose a saved customer to
                leave a balance outstanding.
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- step 2 */}
      <section className={cn("space-y-3", stepVisible(2))}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Items</h2>
          <span className="text-xs text-muted-foreground">
            {readyLines.length} added
          </span>
        </div>

        <ul className="space-y-3">
          {lines.map((line, index) => {
            const a = lineAmounts(line);
            const chosen = line.product ?? null;
            const source = chosen
              ? chosen.track_stock ? "stock" : "quick_bill"
              : line.newProduct
                ? line.newProduct.track_stock ? "stock" : "quick_bill"
                : null;
            const short =
              chosen?.track_stock &&
              Number(chosen.available ?? 0) < Number(line.quantity || 0);

            return (
              <li key={line.key} className="rounded-lg border border-border bg-card p-3">
                <ProductPicker
                  value={
                    chosen
                      ? chosen
                      : line.newProduct
                        ? { label: `${line.newProduct.name} (new)` }
                        : null
                  }
                  onlyTracked={mode === "stock"}
                  onPick={(p: BillingProduct) =>
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
                  onCreateNew={(name: string, payload: QuickProductPayload) =>
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
                  <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                    {source === "stock" ? (
                      <><Package className="h-3 w-3" aria-hidden /> From stock</>
                    ) : (
                      <><PackageX className="h-3 w-3" aria-hidden /> Quick Bill — no stock</>
                    )}
                    {line.newProduct && " · new product"}
                    {chosen?.uom_code ? ` · sold in ${chosen.uom_code}` : ""}
                  </p>
                )}

                <div className="mt-3 flex flex-wrap items-end gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">Qty</Label>
                    <QuantityStepper
                      value={line.quantity}
                      onChange={(q) => patchLine(line.key, { quantity: q })}
                    />
                  </div>
                  <div className="min-w-24 flex-1 space-y-1">
                    <Label htmlFor={`price-${line.key}`} className="text-xs">
                      Price / {line.uom_code}
                    </Label>
                    <Input
                      id={`price-${line.key}`}
                      inputMode="decimal"
                      value={line.unit_price}
                      placeholder="0.00"
                      onChange={(e) => patchLine(line.key, { unit_price: e.target.value })}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor={`disc-${line.key}`} className="text-xs">Disc %</Label>
                    <Input
                      id={`disc-${line.key}`}
                      inputMode="decimal"
                      className="w-20"
                      value={line.discount_percent}
                      onChange={(e) => patchLine(line.key, { discount_percent: e.target.value })}
                    />
                  </div>
                </div>

                {short && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-destructive">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                    Only {chosen?.available} {chosen?.uom_code} available. Reduce the
                    quantity, receive stock, or sell it as a Quick Bill line.
                  </p>
                )}

                <div className="mt-3 flex items-center justify-between border-t border-border pt-2">
                  <span className="text-sm font-semibold tabular-nums">
                    {pkrExact(a.total)}
                  </span>
                  <span className="flex gap-1">
                    <Button
                      variant="ghost" size="sm" aria-label="Duplicate item"
                      onClick={() =>
                        setLines((cur) => {
                          const copy = { ...line, key: crypto.randomUUID() };
                          const next = [...cur];
                          next.splice(index + 1, 0, copy);
                          return next;
                        })
                      }
                    >
                      <Copy className="mr-1 h-4 w-4" aria-hidden /> Duplicate
                    </Button>
                    <Button
                      variant="ghost" size="sm" aria-label="Remove item"
                      disabled={lines.length === 1}
                      onClick={() => setLines((cur) => cur.filter((l) => l.key !== line.key))}
                    >
                      <Trash2 className="mr-1 h-4 w-4" aria-hidden /> Remove
                    </Button>
                  </span>
                </div>
              </li>
            );
          })}
        </ul>

        <Button variant="outline" className="w-full"
          onClick={() => setLines((l) => [...l, blankLine()])}>
          <Plus className="mr-1.5 h-4 w-4" aria-hidden /> Add product
        </Button>
      </section>

      {/* ---------------------------------------------------------- step 3 */}
      <section className={cn("space-y-4", stepVisible(3))}>
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold">Adjustments</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="dtype">Overall discount</Label>
              <select
                id="dtype"
                value={discountType}
                onChange={(e) => setDiscountType(e.target.value as "" | "percent" | "amount")}
                className="h-11 w-full rounded-lg border border-input bg-transparent px-2 text-base md:h-8 md:text-sm"
              >
                <option value="">None</option>
                <option value="percent">Percentage</option>
                <option value="amount">Fixed amount</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dval">Discount value</Label>
              <Input id="dval" inputMode="decimal" value={discountValue} disabled={!discountType}
                onChange={(e) => setDiscountValue(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="deliv">Delivery charge</Label>
              <Input id="deliv" inputMode="decimal" value={delivery}
                onChange={(e) => setDelivery(e.target.value)} />
            </div>
          </div>
          {totals.overflowed && (
            <p className="mt-2 text-xs text-destructive">
              The discount is larger than the invoice total.
            </p>
          )}
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="notes">Notes on the invoice</Label>
              <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="terms">Payment terms note</Label>
              <Textarea id="terms" value={termsNote}
                onChange={(e) => setTermsNote(e.target.value)} />
            </div>
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
          <h2 className="mb-1 text-sm font-semibold">Total</h2>
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
          <div className="border-t border-border pt-2">
            <Row label="Invoice total" value={pkr(totals.grand)} strong />
          </div>

          <div className="space-y-1.5 pt-3">
            <Label htmlFor="paid">Amount received</Label>
            <div className="flex gap-2">
              <Input id="paid" inputMode="decimal" value={amountPaid} placeholder="0.00"
                onChange={(e) => setAmountPaid(e.target.value)} />
              <Button variant="outline" onClick={() => setAmountPaid(totals.grand.toFixed(2))}>
                Full
              </Button>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="method">Payment method</Label>
            <select
              id="method"
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
              className="h-11 w-full rounded-lg border border-input bg-transparent px-2 text-base md:h-8 md:text-sm"
            >
              <option value="cash">Cash</option>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cheque">Cheque</option>
              <option value="online">Online</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div className="border-t border-border pt-2">
            <Row
              label="Balance due"
              value={pkrExact(Math.max(totals.grand - Number(amountPaid || 0), 0))}
              strong
            />
          </div>
        </div>

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
      </section>

      {/* sticky actions — sit above the bottom navigation, never on top of it */}
      <div
        className="fixed inset-x-0 z-30 border-t border-border bg-card/95 backdrop-blur lg:pl-60"
        style={{ bottom: "var(--bottom-nav-space)" }}
      >
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-3 py-2.5">
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted-foreground">
              Total{readyLines.length > 0 ? ` · ${readyLines.length} item${readyLines.length > 1 ? "s" : ""}` : ""}
            </span>
            <span className="block truncate text-base font-semibold tabular-nums">
              {pkr(totals.grand)}
            </span>
          </span>

          {/* mobile: step through. desktop: both actions at once. */}
          <span className="flex shrink-0 gap-2 lg:hidden">
            {step > 1 && (
              <Button variant="outline" size="lg" aria-label="Previous step"
                onClick={() => setStep((s) => (s - 1) as Step)}>
                <ArrowLeft className="h-4 w-4" aria-hidden />
              </Button>
            )}
            {step < 3 ? (
              <Button size="lg" onClick={() => setStep((s) => (s + 1) as Step)}>
                Next <ArrowRight className="ml-1.5 h-4 w-4" aria-hidden />
              </Button>
            ) : (
              <Button size="lg" disabled={busy || !!problem}
                onClick={() => attempt(() => finalize.mutate())}>
                {finalize.isPending ? "Finalizing…" : "Finalize"}
              </Button>
            )}
          </span>

          <span className="hidden shrink-0 gap-2 lg:flex">
            <Button variant="outline" disabled={busy || !canSaveDraft}
              onClick={() => attempt(() => saveDraft.mutate())}>
              <Save className="mr-1.5 h-4 w-4" aria-hidden /> Save draft
            </Button>
            <Button disabled={busy || !!problem}
              onClick={() => attempt(() => finalize.mutate())}>
              {finalize.isPending ? "Finalizing…" : "Finalize & bill"}
            </Button>
          </span>
        </div>
      </div>

      {/* keeps the last field clear of the sticky bar */}
      <div aria-hidden className="h-16" />
    </main>
  );
}

function SaveIndicator({ state }: { state: "idle" | "saving" | "saved" | "error" }) {
  if (state === "idle") return null;
  return (
    <span
      role="status"
      className={cn(
        "flex items-center gap-1 text-xs",
        state === "error" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {state === "saving" && "Saving…"}
      {state === "saved" && (
        <>
          <Check className="h-3.5 w-3.5" aria-hidden /> Draft saved
        </>
      )}
      {state === "error" && (
        <>
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> Not saved
        </>
      )}
    </span>
  );
}

/** useSearchParams needs a boundary, or the page cannot be prerendered. */
export default function CreateBillPage() {
  return (
    <Suspense
      fallback={
        <main className="space-y-4 p-4 sm:p-6">
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
