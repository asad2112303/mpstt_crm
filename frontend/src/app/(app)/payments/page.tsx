"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth-context";
import type { Organization } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface PaymentRow {
  id: string;
  payment_number: string;
  organization_id: string;
  payment_date: string;
  amount: string;
  method: string;
  reference: string | null;
  status: "recorded" | "partially_allocated" | "allocated" | "reversed";
  unallocated: string;
  allocations: { id: string; invoice_id: string; allocated_amount: string }[];
  receipt: { receipt_number: string } | null;
}

interface OpenInvoice {
  invoice_id: string;
  invoice_number: string;
  outstanding: string;
  due_date: string | null;
  derived_status: string;
}

function statusStyle(status: PaymentRow["status"]): string {
  return {
    recorded: "bg-muted text-muted-foreground",
    partially_allocated: "bg-warning/20 text-warning-foreground",
    allocated: "bg-primary text-primary-foreground",
    reversed: "bg-destructive/15 text-destructive line-through",
  }[status];
}

function RecordPaymentDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [orgQ, setOrgQ] = useState("");
  const [org, setOrg] = useState<Organization | null>(null);
  const [form, setForm] = useState({
    amount: "", method: "bank_transfer", reference: "",
    payment_date: new Date().toISOString().slice(0, 10),
  });

  const { data: customers } = useQuery({
    queryKey: ["customers", { search: orgQ }],
    queryFn: async () =>
      (await api<Organization[]>("/api/v1/customers", {
        searchParams: { search: orgQ || undefined, page_size: 8 },
      })).data,
    enabled: open && !org,
  });

  const record = useMutation({
    mutationFn: () =>
      api("/api/v1/payments", {
        method: "POST",
        body: {
          organization_id: org!.id,
          payment_date: form.payment_date,
          amount: form.amount,
          method: form.method,
          reference: form.reference || null,
        },
      }),
    onSuccess: () => {
      toast.success("Payment recorded — allocate it to invoices next");
      queryClient.invalidateQueries({ queryKey: ["payments"] });
      setOpen(false); setOrg(null);
      setForm({ amount: "", method: "bank_transfer", reference: "",
        payment_date: new Date().toISOString().slice(0, 10) });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setOrg(null); }}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> Record payment
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{org ? `Payment from ${org.name}` : "Record payment — choose customer"}</DialogTitle>
        </DialogHeader>
        {!org ? (
          <>
            <Input autoFocus placeholder="Search customers…" value={orgQ}
              onChange={(e) => setOrgQ(e.target.value)} aria-label="Search customers" />
            <ul className="max-h-56 space-y-1 overflow-auto">
              {(customers ?? []).map((c) => (
                <li key={c.id}>
                  <button className="w-full rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                    onClick={() => setOrg(c)}>
                    {c.name}{" "}
                    <span className="text-xs text-muted-foreground">
                      {c.customer_profile?.customer_code}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); record.mutate(); }}>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="pm-amount">Amount (PKR) *</Label>
                <Input id="pm-amount" type="number" min="0.01" step="0.01" required
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pm-date">Date</Label>
                <Input id="pm-date" type="date" value={form.payment_date}
                  onChange={(e) => setForm({ ...form, payment_date: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pm-method">Method</Label>
                <Select value={form.method} onValueChange={(v) => setForm({ ...form, method: v ?? "bank_transfer" })}>
                  <SelectTrigger id="pm-method"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bank_transfer">Bank transfer</SelectItem>
                    <SelectItem value="cash">Cash</SelectItem>
                    <SelectItem value="cheque">Cheque</SelectItem>
                    <SelectItem value="online">Online</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pm-ref">Reference</Label>
                <Input id="pm-ref" placeholder="TRX / cheque no…" value={form.reference}
                  onChange={(e) => setForm({ ...form, reference: e.target.value })} />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOrg(null)}>Back</Button>
              <Button type="submit" disabled={!form.amount || record.isPending}>
                {record.isPending ? "Recording…" : "Record"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AllocateDialog({ payment }: { payment: PaymentRow }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [amounts, setAmounts] = useState<Record<string, string>>({});

  const { data: openInvoices } = useQuery({
    queryKey: ["receivables", payment.organization_id],
    queryFn: async () =>
      (await api<{ rows: OpenInvoice[] }>("/api/v1/receivables", {
        searchParams: { organization_id: payment.organization_id },
      })).data.rows,
    enabled: open,
  });

  const allocate = useMutation({
    mutationFn: () =>
      api(`/api/v1/payments/${payment.id}/allocate`, {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          allocations: Object.entries(amounts)
            .filter(([, v]) => Number(v) > 0)
            .map(([invoiceId, amount]) => ({ invoice_id: invoiceId, amount })),
        },
      }),
    onSuccess: () => {
      toast.success("Payment allocated");
      queryClient.invalidateQueries();
      setOpen(false); setAmounts({});
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Allocation failed"),
  });

  const totalEntered = Object.values(amounts).reduce((sum, v) => sum + Number(v || 0), 0);
  const valid = totalEntered > 0 && totalEntered <= Number(payment.unallocated) + 1e-9;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="inline-flex h-7 items-center rounded-md border border-border bg-card px-2.5 text-[0.8rem] hover:bg-muted">
        Allocate
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>
            Allocate {payment.payment_number} — unallocated PKR {payment.unallocated}
          </DialogTitle>
        </DialogHeader>
        {!openInvoices?.length ? (
          <p className="text-sm text-muted-foreground">
            No open invoices for this customer.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Invoice</TableHead>
                  <TableHead>Due</TableHead>
                  <TableHead className="text-right">Outstanding</TableHead>
                  <TableHead className="w-32">Allocate</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openInvoices.map((inv) => (
                  <TableRow key={inv.invoice_id}>
                    <TableCell className="font-medium">{inv.invoice_number}</TableCell>
                    <TableCell className="text-sm">{inv.due_date ?? "—"}</TableCell>
                    <TableCell className="text-right">{inv.outstanding}</TableCell>
                    <TableCell>
                      <Input type="number" min="0" max={inv.outstanding} step="0.01"
                        aria-label={`Allocate to ${inv.invoice_number}`}
                        value={amounts[inv.invoice_id] ?? ""}
                        onChange={(e) => setAmounts((p) => ({
                          ...p, [inv.invoice_id]: e.target.value,
                        }))} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-sm text-muted-foreground">
          Entered: PKR {totalEntered.toFixed(2)} of {payment.unallocated} unallocated.
          Over-allocation is blocked by the server.
        </p>
        <DialogFooter>
          <Button disabled={!valid || allocate.isPending} onClick={() => allocate.mutate()}>
            {allocate.isPending ? "Allocating…" : "Allocate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

async function openReceipt(paymentId: string, hasReceipt: boolean) {
  let headers: Record<string, string> = {};
  if (supabaseConfigured()) {
    const { data: { session } } = await createClient().auth.getSession();
    if (session) headers = { Authorization: `Bearer ${session.access_token}` };
  }
  if (!hasReceipt) {
    const resp = await fetch(`${API_BASE}/api/v1/payments/${paymentId}/receipt`, {
      method: "POST", headers,
    });
    if (!resp.ok) { toast.error("Could not create the receipt"); return; }
  }
  const resp = await fetch(`${API_BASE}/api/v1/payments/${paymentId}/receipt/pdf`, { headers });
  if (!resp.ok) { toast.error("Could not load the receipt PDF"); return; }
  const blob = await resp.blob();
  window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

export default function PaymentsPage() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["payments", { status, search, page }],
    queryFn: async () =>
      await api<PaymentRow[]>("/api/v1/payments", {
        searchParams: {
          status: status || undefined, search: search || undefined,
          page, page_size: 25,
        },
      }),
  });

  const reverse = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      api(`/api/v1/payments/${id}/reverse`, { method: "POST", body: { reason } }),
    onSuccess: () => {
      toast.success("Payment reversed");
      queryClient.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Reversal failed"),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Payments"
        description="Record, allocate to invoices, and issue receipts. Reversals are Admin-only."
        actions={<RecordPaymentDialog />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search payment no, reference, customer…" className="w-72"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search payments" />
        <div className="flex gap-1" role="group" aria-label="Filter by status">
          {["", "recorded", "partially_allocated", "allocated", "reversed"].map((s) => (
            <button key={s || "all"}
              onClick={() => { setStatus(s); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium capitalize",
                status === s
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}>
              {s === "" ? "All" : s.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load payments: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Banknote className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No payments match.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Payment</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="text-right">Unallocated</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.payment_number}</TableCell>
                    <TableCell>{p.payment_date}</TableCell>
                    <TableCell className="capitalize">{p.method.replace("_", " ")}</TableCell>
                    <TableCell className="text-right font-medium">{p.amount}</TableCell>
                    <TableCell className="text-right">{p.unallocated}</TableCell>
                    <TableCell>
                      <Badge className={cn("border-transparent capitalize", statusStyle(p.status))}>
                        {p.status.replace("_", " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="space-x-1 text-right">
                      {p.status !== "reversed" && Number(p.unallocated) > 0 && (
                        <AllocateDialog payment={p} />
                      )}
                      {p.status !== "reversed" && (
                        <Button variant="outline" size="sm"
                          onClick={() => void openReceipt(p.id, Boolean(p.receipt))}>
                          Receipt
                        </Button>
                      )}
                      {me?.role === "admin" && p.status !== "reversed" && (
                        <Button variant="ghost" size="sm"
                          onClick={() => {
                            const reason = window.prompt(
                              "Reversal reason (required, audited):",
                            );
                            if (reason) reverse.mutate({ id: p.id, reason });
                          }}>
                          Reverse
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} payments</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span>Page {page} of {pages}</span>
              <Button variant="outline" size="sm" disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
