"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Download, Plus, Printer, Trash2 } from "lucide-react";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import {
  pkrExact,
  type BillingCustomer, type BillingProduct, type RateLine, type RateQuotation,
} from "@/lib/types/billing";
import { CustomerCombobox } from "@/components/billing/customer-combobox";
import {
  downloadDocument, InvoiceActions, printDocument,
} from "@/components/billing/invoice-share";
import { ProductPicker } from "@/components/billing/product-picker";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

function blankLine(): RateLine {
  return { key: crypto.randomUUID(), unit_price: "" };
}

const pdfPath = (id: string) => `/api/v1/rate-quotations/${id}/pdf`;

export default function RateQuotationPage() {
  const [named, setNamed] = useState(false);
  const [customer, setCustomer] = useState<BillingCustomer | null>(null);
  const [customerName, setCustomerName] = useState("");
  const [contactPerson, setContactPerson] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<RateLine[]>([blankLine()]);
  const [issued, setIssued] = useState<RateQuotation | null>(null);
  const [thenDo, setThenDo] = useState<"none" | "print" | "pdf">("none");
  const [idemKey] = useState(newIdempotencyKey);

  const ready = useMemo(() => lines.filter((l) => l.product), [lines]);

  function patch(key: string, next: Partial<RateLine>) {
    setLines((cur) => cur.map((l) => (l.key === key ? { ...l, ...next } : l)));
  }

  function validate(): string | null {
    if (ready.length === 0) return "Add at least one product.";
    if (ready.some((l) => l.unit_price === "")) return "Every product needs a rate.";
    if (ready.some((l) => Number(l.unit_price) < 0)) return "A rate cannot be negative.";
    return null;
  }

  const save = useMutation({
    mutationFn: async () =>
      (
        await api<RateQuotation>("/api/v1/rate-quotations", {
          method: "POST",
          // One key for the life of the form: a double tap cannot publish
          // the same rate list twice.
          idempotencyKey: idemKey,
          body: {
            organization_id: named ? customer?.id ?? null : null,
            customer_name: named ? null : customerName || null,
            contact_person: contactPerson || null,
            contact_phone: contactPhone || null,
            valid_until: validUntil || null,
            notes: notes || null,
            items: ready.map((l) => ({
              product_variant_id: l.product!.product_variant_id,
              unit_price: l.unit_price || "0",
            })),
          },
        })
      ).data,
    onSuccess: async (quote) => {
      setIssued(quote);
      try {
        if (thenDo === "print") await printDocument(pdfPath(quote.id), quote.quotation_number);
        if (thenDo === "pdf") await downloadDocument(pdfPath(quote.id), quote.quotation_number);
      } catch {
        toast.error("Saved, but the PDF could not be prepared. Try again below.");
      }
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : "Could not save the rate list."),
  });

  function attempt(after: "none" | "print" | "pdf") {
    const issue = validate();
    if (issue) {
      toast.error(issue);
      return;
    }
    setThenDo(after);
    save.mutate();
  }

  if (issued) {
    return (
      <main className="mx-auto max-w-lg space-y-5 p-4 sm:p-6">
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-5 text-center">
          <CheckCircle2 className="mx-auto h-10 w-10 text-primary" aria-hidden />
          <h1 className="mt-2 text-lg font-semibold">{issued.quotation_number}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Rate list for {issued.items.length} product
            {issued.items.length === 1 ? "" : "s"}
            {issued.valid_until ? ` · valid until ${issued.valid_until}` : ""}
          </p>
        </div>

        <InvoiceActions
          invoiceId={issued.id}
          invoiceNumber={issued.quotation_number}
          pdfPath={pdfPath(issued.id)}
          label="A rate list quotes prices per unit. It has no quantities and no total."
        />

        <div className="grid gap-2">
          <Button render={<Link href="/rate-quotation" />}
            onClick={() => window.location.reload()}>
            New rate list
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main className="space-y-4 p-4 pb-28 sm:p-6">
      <PageHeader
        title="Rate list"
        description="Quote what each product costs per unit. No quantities, and nothing to total."
      />

      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Prepared for</h2>
          <div className="flex gap-1" role="group" aria-label="Customer type">
            {([[false, "Type a name"], [true, "Saved customer"]] as [boolean, string][]).map(
              ([value, label]) => (
                <button
                  key={String(value)}
                  onClick={() => setNamed(value)}
                  aria-pressed={named === value}
                  className={
                    named === value
                      ? "rounded-full border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                      : "rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium"
                  }
                >
                  {label}
                </button>
              ),
            )}
          </div>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="rq-cust">Customer</Label>
            {named ? (
              <CustomerCombobox selected={customer} onSelect={setCustomer} />
            ) : (
              <Input id="rq-cust" value={customerName} placeholder="Optional"
                onChange={(e) => setCustomerName(e.target.value)} />
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rq-contact">Contact person</Label>
            <Input id="rq-contact" value={contactPerson}
              onChange={(e) => setContactPerson(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rq-phone">Phone</Label>
            <Input id="rq-phone" type="tel" inputMode="tel" value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rq-valid">Rates valid until</Label>
            <Input id="rq-valid" type="date" value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)} />
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Products and rates</h2>
          <span className="text-xs text-muted-foreground">{ready.length} added</span>
        </div>

        <ul className="space-y-3">
          {lines.map((line) => (
            <li key={line.key} className="rounded-lg border border-border bg-card p-3">
              <ProductPicker
                value={line.product ?? null}
                onlyTracked={false}
                onPick={(p: BillingProduct) =>
                  patch(line.key, {
                    product: p,
                    unit_price:
                      Number(p.suggested_price) > 0 ? p.suggested_price : line.unit_price,
                  })
                }
                // A rate list quotes the catalogue, so nothing is created here.
                onCreateNew={() =>
                  toast.info("Add new products from Create Bill or the catalogue.")
                }
              />

              <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
                <div className="min-w-32 flex-1 space-y-1">
                  <Label htmlFor={`rate-${line.key}`} className="text-xs">
                    Rate per {line.product?.uom_code ?? "unit"}
                  </Label>
                  <Input
                    id={`rate-${line.key}`}
                    inputMode="decimal"
                    value={line.unit_price}
                    placeholder="0.00"
                    onChange={(e) => patch(line.key, { unit_price: e.target.value })}
                  />
                </div>
                <Button variant="ghost" size="sm" disabled={lines.length === 1}
                  onClick={() => setLines((cur) => cur.filter((l) => l.key !== line.key))}>
                  <Trash2 className="mr-1 h-4 w-4" aria-hidden /> Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>

        <Button variant="outline" className="w-full"
          onClick={() => setLines((l) => [...l, blankLine()])}>
          <Plus className="mr-1.5 h-4 w-4" aria-hidden /> Add product
        </Button>
      </section>

      <section className="space-y-1.5 rounded-lg border border-border bg-card p-4">
        <Label htmlFor="rq-notes">Notes on the rate list</Label>
        <Textarea id="rq-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </section>

      {/* No running total: a rate list has nothing to add up. */}
      <div
        className="fixed inset-x-0 z-30 border-t border-border bg-card/95 backdrop-blur lg:pl-60"
        style={{ bottom: "var(--bottom-nav-space)" }}
      >
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-2 px-3 py-2.5">
          <span className="min-w-0 flex-1 text-xs text-muted-foreground">
            {ready.length} product{ready.length === 1 ? "" : "s"}
            {ready.length > 0 && (
              <span className="block truncate">
                {ready
                  .map((l) => `${l.product?.product_name} @ ${pkrExact(l.unit_price || 0)}`)
                  .join(" · ")}
              </span>
            )}
          </span>
          <span className="flex shrink-0 gap-2">
            <Button variant="outline" disabled={save.isPending}
              onClick={() => attempt("print")}>
              <Printer className="mr-1.5 h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Save &amp; print</span>
            </Button>
            <Button variant="outline" disabled={save.isPending}
              onClick={() => attempt("pdf")}>
              <Download className="mr-1.5 h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Save &amp; PDF</span>
            </Button>
            <Button disabled={save.isPending} onClick={() => attempt("none")}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </span>
        </div>
      </div>
    </main>
  );
}
