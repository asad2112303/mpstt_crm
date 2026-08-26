"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import {
  formatKarachi,
  type Activity, type Branch, type Contact,
  type SampleRow, type Task, type PriceRow,
} from "@/lib/types/crm";
import type { SearchHit } from "@/lib/types/catalogue";
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
import { Textarea } from "@/components/ui/textarea";

/* ---------- catalogue variant picker (search-based) ---------- */

export function VariantPicker({
  onPick, placeholder = "Search product / variant…",
}: { onPick: (hit: SearchHit) => void; placeholder?: string }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["catalogue", "search", q],
    queryFn: async () =>
      (await api<SearchHit[]>("/api/v1/catalogue/search", { searchParams: { q } })).data,
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <Input value={q} placeholder={placeholder} aria-label="Search catalogue"
        onChange={(e) => setQ(e.target.value)} />
      {q.length >= 2 && data && (
        <ul className="absolute z-20 mt-1 max-h-52 w-full overflow-auto rounded-md border border-border bg-popover shadow-md">
          {data.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">No matches</li>
          )}
          {data.map((h) => (
            <li key={`${h.product_id}-${h.variant_id}`}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => { onPick(h); setQ(""); }}
              >
                {h.label} <span className="text-xs text-muted-foreground">({h.sku})</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ---------- contacts & branches ---------- */

export function ContactsTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "contacts"],
    queryFn: async () => (await api<Contact[]>(`/api/v1/organizations/${orgId}/contacts`)).data,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ full_name: "", designation: "", phone_primary: "", email: "", whatsapp: "" });

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/organizations/${orgId}/contacts`, {
        method: "POST",
        body: {
          full_name: form.full_name,
          designation: form.designation || null,
          phone_primary: form.phone_primary || null,
          email: form.email || null,
          whatsapp: form.whatsapp || null,
        },
      }),
    onSuccess: () => {
      toast.success("Contact added");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "contacts"] });
      setOpen(false);
      setForm({ full_name: "", designation: "", phone_primary: "", email: "", whatsapp: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-card px-3 text-sm hover:bg-muted">
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add contact
        </DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Add contact</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            {(
              [
                ["full_name", "Full name *"],
                ["designation", "Designation"],
                ["phone_primary", "Phone"],
                ["whatsapp", "WhatsApp"],
                ["email", "Email"],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`ct-${key}`}>{label}</Label>
                <Input id={`ct-${key}`} value={form[key]}
                  required={key === "full_name"}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
              </div>
            ))}
            <DialogFooter>
              <Button type="submit" disabled={!form.full_name || create.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No contacts recorded.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead><TableHead>Designation</TableHead>
                <TableHead>Phone</TableHead><TableHead>WhatsApp</TableHead>
                <TableHead>Email</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">
                    {c.full_name} {c.is_primary && <Badge variant="secondary">Primary</Badge>}
                  </TableCell>
                  <TableCell>{c.designation ?? "—"}</TableCell>
                  <TableCell>{c.phone_primary ?? "—"}</TableCell>
                  <TableCell>{c.whatsapp ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{c.email ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export function BranchesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "branches"],
    queryFn: async () => (await api<Branch[]>(`/api/v1/organizations/${orgId}/branches`)).data,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ branch_name: "", city: "", area: "", delivery_address: "" });

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/organizations/${orgId}/branches`, {
        method: "POST",
        body: {
          branch_name: form.branch_name,
          city: form.city || null,
          area: form.area || null,
          delivery_address: form.delivery_address || null,
        },
      }),
    onSuccess: () => {
      toast.success("Branch added");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "branches"] });
      setOpen(false);
      setForm({ branch_name: "", city: "", area: "", delivery_address: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-card px-3 text-sm hover:bg-muted">
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add branch
        </DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Add branch</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="br-name">Branch name *</Label>
              <Input id="br-name" required value={form.branch_name}
                onChange={(e) => setForm({ ...form, branch_name: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="br-city">City</Label>
                <Input id="br-city" value={form.city}
                  onChange={(e) => setForm({ ...form, city: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="br-area">Area</Label>
                <Input id="br-area" value={form.area}
                  onChange={(e) => setForm({ ...form, area: e.target.value })} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="br-addr">Delivery address</Label>
              <Textarea id="br-addr" value={form.delivery_address}
                onChange={(e) => setForm({ ...form, delivery_address: e.target.value })} />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!form.branch_name || create.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No branches recorded.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Branch</TableHead><TableHead>City / Area</TableHead>
                <TableHead>Delivery address</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-medium">
                    {b.branch_name} {b.is_primary && <Badge variant="secondary">Primary</Badge>}
                  </TableCell>
                  <TableCell>{b.city ?? "—"} {b.area ? `· ${b.area}` : ""}</TableCell>
                  <TableCell className="max-w-md text-sm text-muted-foreground">
                    {b.delivery_address ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

/* ---------- activities ---------- */

export function ActivitiesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "activities"],
    queryFn: async () => (await api<Activity[]>(`/api/v1/prospects/${orgId}/activities`)).data,
  });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    activity_type: "visit", outcome: "", notes: "", products_discussed: "",
    next_action_title: "", next_action_due: "",
  });

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/prospects/${orgId}/activities`, {
        method: "POST",
        body: {
          activity_type: form.activity_type,
          outcome: form.outcome || null,
          notes: form.notes || null,
          products_discussed: form.products_discussed || null,
          next_action_title: form.next_action_title || null,
          next_action_due_at: form.next_action_due
            ? new Date(form.next_action_due).toISOString()
            : null,
        },
      }),
    onSuccess: () => {
      toast.success("Activity recorded");
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      setOpen(false);
      setForm({ activity_type: "visit", outcome: "", notes: "", products_discussed: "", next_action_title: "", next_action_due: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-card px-3 text-sm hover:bg-muted">
          <Plus className="h-3.5 w-3.5" aria-hidden /> Record activity
        </DialogTrigger>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Record activity</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="ac-type">Type</Label>
              <Select value={form.activity_type}
                onValueChange={(v) => setForm({ ...form, activity_type: v ?? "visit" })}>
                <SelectTrigger id="ac-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["visit", "call", "whatsapp", "email", "meeting", "follow_up"].map((t) => (
                    <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ac-outcome">Outcome</Label>
              <Input id="ac-outcome" value={form.outcome}
                onChange={(e) => setForm({ ...form, outcome: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ac-products">Products discussed</Label>
              <Input id="ac-products" value={form.products_discussed}
                onChange={(e) => setForm({ ...form, products_discussed: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ac-notes">Notes</Label>
              <Textarea id="ac-notes" value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
              <div className="space-y-1.5">
                <Label htmlFor="ac-next">Next action</Label>
                <Input id="ac-next" placeholder="e.g. Send quotation" value={form.next_action_title}
                  onChange={(e) => setForm({ ...form, next_action_title: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ac-due">Due</Label>
                <Input id="ac-due" type="datetime-local" value={form.next_action_due}
                  onChange={(e) => setForm({ ...form, next_action_due: e.target.value })} />
              </div>
            </div>
            <DialogFooter>
              <Button type="submit"
                disabled={create.isPending || (Boolean(form.next_action_title) && !form.next_action_due)}>
                Save activity
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No activities yet.</p>
      ) : (
        <ol className="space-y-2">
          {data.map((a) => (
            <li key={a.id} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center justify-between">
                <Badge variant="secondary">{a.activity_type.replace("_", " ")}</Badge>
                <span className="text-xs text-muted-foreground">{formatKarachi(a.happened_at)}</span>
              </div>
              {a.outcome && <p className="mt-1 text-sm font-medium">{a.outcome}</p>}
              {a.products_discussed && (
                <p className="text-xs text-muted-foreground">Products: {a.products_discussed}</p>
              )}
              {a.notes && <p className="mt-1 text-sm text-muted-foreground">{a.notes}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/* ---------- samples ---------- */

export function SamplesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "samples"],
    queryFn: async () => (await api<SampleRow[]>(`/api/v1/prospects/${orgId}/samples`)).data,
  });
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<SearchHit | null>(null);
  const [form, setForm] = useState({ quantity: "1", receiver_name: "", feedback_due_date: "" });

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/prospects/${orgId}/samples`, {
        method: "POST",
        body: {
          product_id: picked!.product_id,
          product_variant_id: picked!.variant_id,
          quantity: form.quantity,
          receiver_name: form.receiver_name || null,
          feedback_due_date: form.feedback_due_date || null,
        },
      }),
    onSuccess: () => {
      toast.success("Sample issued");
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      setOpen(false); setPicked(null);
      setForm({ quantity: "1", receiver_name: "", feedback_due_date: "" });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const feedback = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => {
      const text = window.prompt("Feedback notes (optional):") ?? "";
      return api(`/api/v1/prospects/samples/${id}/feedback`, {
        method: "PATCH", body: { status, feedback: text || null },
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "samples"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-card px-3 text-sm hover:bg-muted">
          <Plus className="h-3.5 w-3.5" aria-hidden /> Issue sample
        </DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Issue sample</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <div className="space-y-1.5">
              <Label>Product / variant *</Label>
              {picked ? (
                <div className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                  <span>{picked.label}</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setPicked(null)}>
                    Change
                  </Button>
                </div>
              ) : (
                <VariantPicker onPick={setPicked} />
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="sm-qty">Quantity *</Label>
                <Input id="sm-qty" type="number" min="0.001" step="any" required value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sm-due">Feedback due</Label>
                <Input id="sm-due" type="date" value={form.feedback_due_date}
                  onChange={(e) => setForm({ ...form, feedback_due_date: e.target.value })} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sm-recv">Receiver</Label>
              <Input id="sm-recv" value={form.receiver_name}
                onChange={(e) => setForm({ ...form, receiver_name: e.target.value })} />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!picked || create.isPending}>Issue</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No samples issued.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Issued</TableHead><TableHead>Qty</TableHead>
                <TableHead>Receiver</TableHead><TableHead>Feedback due</TableHead>
                <TableHead>Status</TableHead><TableHead>Feedback</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((s) => (
                <TableRow key={s.id}>
                  <TableCell>{formatKarachi(s.issued_at, false)}</TableCell>
                  <TableCell>{s.quantity}</TableCell>
                  <TableCell>{s.receiver_name ?? "—"}</TableCell>
                  <TableCell>{s.feedback_due_date ?? "—"}</TableCell>
                  <TableCell><Badge variant="secondary">{s.status.replace("_", " ")}</Badge></TableCell>
                  <TableCell className="max-w-52 truncate text-sm text-muted-foreground">
                    {s.feedback ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    {s.status === "issued" && (
                      <Button variant="outline" size="sm"
                        onClick={() => feedback.mutate({ id: s.id, status: "feedback_received" })}>
                        Record feedback
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

/* ---------- tasks ---------- */

export function TasksTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "tasks"],
    queryFn: async () => (await api<Task[]>(`/api/v1/prospects/${orgId}/tasks`)).data,
  });
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/prospects/${orgId}/tasks`, {
        method: "POST",
        body: { title, due_at: new Date(due).toISOString() },
      }),
    onSuccess: () => {
      setTitle(""); setDue("");
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const complete = useMutation({
    mutationFn: (taskId: string) =>
      api(`/api/v1/prospects/tasks/${taskId}`, { method: "PATCH", body: { status: "done" } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "tasks"] }),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => { e.preventDefault(); if (title && due) create.mutate(); }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="tk-title">New task</Label>
          <Input id="tk-title" className="w-64" value={title}
            onChange={(e) => setTitle(e.target.value)} placeholder="Follow up on quotation…" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tk-due">Due</Label>
          <Input id="tk-due" type="datetime-local" value={due}
            onChange={(e) => setDue(e.target.value)} />
        </div>
        <Button type="submit" disabled={!title || !due || create.isPending}>Add</Button>
      </form>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No tasks.</p>
      ) : (
        <ul className="space-y-2">
          {data.map((t) => {
            const overdue = t.status === "open" && new Date(t.due_at) < new Date();
            return (
              <li key={t.id}
                className="flex items-center justify-between rounded-lg border border-border bg-card p-3">
                <div>
                  <p className={t.status === "done" ? "text-sm line-through text-muted-foreground" : "text-sm font-medium"}>
                    {t.title}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Due {formatKarachi(t.due_at)}{" "}
                    {overdue && <Badge variant="destructive">Overdue</Badge>}
                  </p>
                </div>
                {t.status === "open" && (
                  <Button variant="outline" size="sm" onClick={() => complete.mutate(t.id)}>
                    Mark done
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ---------- prices ---------- */

export function PricesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "prices"],
    queryFn: async () => (await api<PriceRow[]>(`/api/v1/organizations/${orgId}/prices`)).data,
  });
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<SearchHit | null>(null);
  const [form, setForm] = useState({
    unit_price: "", price_type: "quoted", effective_from: new Date().toISOString().slice(0, 10),
  });

  const create = useMutation({
    mutationFn: () =>
      api(`/api/v1/organizations/${orgId}/prices`, {
        method: "POST",
        body: {
          product_id: picked!.product_id,
          product_variant_id: picked!.variant_id,
          unit_price: form.unit_price,
          price_type: form.price_type,
          effective_from: form.effective_from,
        },
      }),
    onSuccess: () => {
      toast.success("Price recorded");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "prices"] });
      setOpen(false); setPicked(null);
      setForm({ unit_price: "", price_type: "quoted", effective_from: new Date().toISOString().slice(0, 10) });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  const expire = useMutation({
    mutationFn: (priceId: string) =>
      api(`/api/v1/organizations/prices/${priceId}/expire`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "prices"] }),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-card px-3 text-sm hover:bg-muted">
          <Plus className="h-3.5 w-3.5" aria-hidden /> Record price
        </DialogTrigger>
        <DialogContent>
          <DialogHeader><DialogTitle>Record customer price</DialogTitle></DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <div className="space-y-1.5">
              <Label>Product / variant *</Label>
              {picked ? (
                <div className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                  <span>{picked.label}</span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setPicked(null)}>Change</Button>
                </div>
              ) : (
                <VariantPicker onPick={setPicked} />
              )}
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="pr-price">Unit price (PKR) *</Label>
                <Input id="pr-price" type="number" min="0.01" step="0.01" required value={form.unit_price}
                  onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pr-type">Type</Label>
                <Select value={form.price_type}
                  onValueChange={(v) => setForm({ ...form, price_type: v ?? "quoted" })}>
                  <SelectTrigger id="pr-type"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="quoted">Quoted</SelectItem>
                    <SelectItem value="agreed">Agreed</SelectItem>
                    <SelectItem value="list">List</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pr-from">Effective from</Label>
                <Input id="pr-from" type="date" value={form.effective_from}
                  onChange={(e) => setForm({ ...form, effective_from: e.target.value })} />
              </div>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!picked || !form.unit_price || create.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {!data?.length ? (
        <p className="text-sm text-muted-foreground">No price history.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead><TableHead className="text-right">Price (PKR)</TableHead>
                <TableHead>From</TableHead><TableHead>To</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((p) => {
                const active = !p.effective_to || p.effective_to >= new Date().toISOString().slice(0, 10);
                return (
                  <TableRow key={p.id}>
                    <TableCell><Badge variant="secondary">{p.price_type}</Badge></TableCell>
                    <TableCell className="text-right font-medium">{p.unit_price}</TableCell>
                    <TableCell>{p.effective_from}</TableCell>
                    <TableCell>{p.effective_to ?? "Open"}</TableCell>
                    <TableCell className="text-right">
                      {active && (
                        <Button variant="ghost" size="sm" onClick={() => expire.mutate(p.id)}>
                          Expire
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

