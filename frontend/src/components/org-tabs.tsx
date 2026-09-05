"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import {
  formatKarachi,
  type Activity, type Branch, type Contact,
  type SampleRow, type Task, type PriceRow, type ProductProfileRow,
} from "@/lib/types/crm";
import type { SearchHit, Uom } from "@/lib/types/catalogue";
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
  const [editing, setEditing] = useState<Contact | null>(null);
  const empty = { full_name: "", designation: "", phone_primary: "", email: "", whatsapp: "" };
  const [form, setForm] = useState(empty);

  function openFor(contact: Contact | null) {
    setEditing(contact);
    setForm(contact ? {
      full_name: contact.full_name,
      designation: contact.designation ?? "",
      phone_primary: contact.phone_primary ?? "",
      email: contact.email ?? "",
      whatsapp: contact.whatsapp ?? "",
    } : empty);
    setOpen(true);
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        full_name: form.full_name,
        designation: form.designation || null,
        phone_primary: form.phone_primary || null,
        email: form.email || null,
        whatsapp: form.whatsapp || null,
        branch_id: editing?.branch_id ?? null,
        is_primary: editing?.is_primary ?? false,
        is_active: editing?.is_active ?? true,
      };
      return editing
        ? api(`/api/v1/organizations/contacts/${editing.id}`, { method: "PATCH", body })
        : api(`/api/v1/organizations/${orgId}/contacts`, { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(editing ? "Contact updated" : "Contact added");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "contacts"] });
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Button variant="outline" size="sm" onClick={() => openFor(null)}>
        <Plus className="mr-1 h-3.5 w-3.5" aria-hidden /> Add contact
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.full_name}` : "Add contact"}</DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
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
              <Button type="submit" disabled={!form.full_name || save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
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
                <TableHead className="text-right">Actions</TableHead>
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
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => openFor(c)}>Edit</Button>
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

export function BranchesTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "branches"],
    queryFn: async () => (await api<Branch[]>(`/api/v1/organizations/${orgId}/branches`)).data,
  });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Branch | null>(null);
  const empty = { branch_name: "", city: "", area: "", delivery_address: "", map_url: "" };
  const [form, setForm] = useState(empty);

  function openFor(branch: Branch | null) {
    setEditing(branch);
    setForm(branch ? {
      branch_name: branch.branch_name,
      city: branch.city ?? "",
      area: branch.area ?? "",
      delivery_address: branch.delivery_address ?? "",
      map_url: branch.map_url ?? "",
    } : empty);
    setOpen(true);
  }

  const save = useMutation({
    mutationFn: () => {
      const body = {
        branch_name: form.branch_name,
        city: form.city || null,
        area: form.area || null,
        delivery_address: form.delivery_address || null,
        map_url: form.map_url || null,
        billing_address: editing?.billing_address ?? null,
        route_cluster: editing?.route_cluster ?? null,
        is_primary: editing?.is_primary ?? false,
        is_active: editing?.is_active ?? true,
      };
      return editing
        ? api(`/api/v1/organizations/branches/${editing.id}`, { method: "PATCH", body })
        : api(`/api/v1/organizations/${orgId}/branches`, { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(editing ? "Branch updated" : "Branch added");
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "branches"] });
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <Button variant="outline" size="sm" onClick={() => openFor(null)}>
        <Plus className="mr-1 h-3.5 w-3.5" aria-hidden /> Add branch
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? `Edit ${editing.branch_name}` : "Add branch"}</DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
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
            <div className="space-y-1.5">
              <Label htmlFor="br-map">Map link</Label>
              <Input id="br-map" value={form.map_url}
                onChange={(e) => setForm({ ...form, map_url: e.target.value })} />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!form.branch_name || save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
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
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((b) => (
                <TableRow key={b.id}>
                  <TableCell className="font-medium">
                    {b.branch_name} {b.is_primary && <Badge variant="secondary">Primary</Badge>}
                    {b.map_url && (
                      <a className="ml-2 text-xs text-primary underline" target="_blank"
                        rel="noopener noreferrer" href={b.map_url}>map</a>
                    )}
                  </TableCell>
                  <TableCell>{b.city ?? "—"} {b.area ? `· ${b.area}` : ""}</TableCell>
                  <TableCell className="max-w-md text-sm text-muted-foreground">
                    {b.delivery_address ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => openFor(b)}>Edit</Button>
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
        <DialogContent className="sm:max-w-lg">
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

  const patch = useMutation({
    mutationFn: ({ taskId, body }: { taskId: string; body: Record<string, unknown> }) =>
      api(`/api/v1/prospects/tasks/${taskId}`, { method: "PATCH", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "tasks"] }),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  function editTask(t: Task) {
    const newTitle = window.prompt("Task title:", t.title);
    if (newTitle === null) return;
    const currentLocal = new Date(t.due_at).toISOString().slice(0, 16);
    const newDue = window.prompt("Due (YYYY-MM-DDTHH:MM):", currentLocal);
    if (newDue === null) return;
    const parsed = new Date(newDue);
    if (Number.isNaN(parsed.getTime())) { toast.error("Invalid date"); return; }
    patch.mutate({ taskId: t.id, body: { title: newTitle || t.title, due_at: parsed.toISOString() } });
  }

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
                  <span className="flex gap-1">
                    <Button variant="ghost" size="sm" onClick={() => editTask(t)}>Edit</Button>
                    <Button variant="outline" size="sm"
                      onClick={() => patch.mutate({ taskId: t.id, body: { status: "done" } })}>
                      Mark done
                    </Button>
                  </span>
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


/* ---------- requirements (what the organization consumes) ---------- */

const FREQUENCIES = ["weekly", "monthly", "quarterly", "adhoc"] as const;

interface RequirementDraft {
  product_id: string;
  product_variant_id: string | null;
  label: string;
  frequency: string;
  min_quantity: string;
  max_quantity: string;
  uom_id: string;
  current_supplier: string;
  current_rate: string;
  specification_notes: string;
}

const EMPTY_REQUIREMENT: RequirementDraft = {
  product_id: "", product_variant_id: null, label: "", frequency: "monthly",
  min_quantity: "", max_quantity: "", uom_id: "", current_supplier: "",
  current_rate: "", specification_notes: "",
};

function toDraft(row: ProductProfileRow): RequirementDraft {
  return {
    product_id: row.product_id,
    product_variant_id: row.product_variant_id,
    label: [row.product_name, row.variant_name].filter(Boolean).join(" — ") || "Product",
    frequency: row.frequency ?? "",
    min_quantity: row.min_quantity ?? "",
    max_quantity: row.max_quantity ?? "",
    uom_id: row.uom_id ?? "",
    current_supplier: row.current_supplier ?? "",
    current_rate: row.current_rate ?? "",
    specification_notes: row.specification_notes ?? "",
  };
}

/** Blank strings become null: the API rejects "" and requires quantities > 0. */
function toPayload(d: RequirementDraft) {
  return {
    product_id: d.product_id,
    product_variant_id: d.product_variant_id,
    frequency: d.frequency || null,
    min_quantity: d.min_quantity || null,
    max_quantity: d.max_quantity || null,
    uom_id: d.uom_id || null,
    current_supplier: d.current_supplier || null,
    current_rate: d.current_rate || null,
    specification_notes: d.specification_notes || null,
  };
}

export function RequirementsTab({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, "product-profiles"],
    queryFn: async () =>
      (await api<ProductProfileRow[]>(`/api/v1/prospects/${orgId}/product-profiles`)).data,
  });
  const { data: uoms } = useQuery({
    queryKey: ["catalogue", "uoms"],
    queryFn: async () => (await api<Uom[]>("/api/v1/catalogue/uoms")).data,
  });

  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<RequirementDraft>(EMPTY_REQUIREMENT);

  // The endpoint replaces the whole set in one transaction, so every change
  // sends the full list — with the edited row swapped in or the removed one
  // left out. Recording requirements also advances the prospect stage.
  const save = useMutation({
    mutationFn: (rows: RequirementDraft[]) =>
      api(`/api/v1/prospects/${orgId}/product-profiles`, {
        method: "PUT",
        body: rows.map(toPayload),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["org", orgId, "product-profiles"] });
      queryClient.invalidateQueries({ queryKey: ["org", orgId] });
      setOpen(false);
      setEditingId(null);
      setDraft(EMPTY_REQUIREMENT);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not save requirement"),
  });

  const rows = data ?? [];

  function submit() {
    const drafts = rows.map(toDraft);
    if (editingId) {
      const index = rows.findIndex((r) => r.id === editingId);
      drafts[index] = draft;
    } else {
      drafts.push(draft);
    }
    save.mutate(drafts);
  }

  function remove(id: string) {
    save.mutate(rows.filter((r) => r.id !== id).map(toDraft));
  }

  function openAdd() {
    setEditingId(null);
    setDraft(EMPTY_REQUIREMENT);
    setOpen(true);
  }

  function openEdit(row: ProductProfileRow) {
    setEditingId(row.id);
    setDraft(toDraft(row));
    setOpen(true);
  }

  if (isLoading) return <Skeleton className="h-40 w-full" />;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Estimated consumption per product — the basis for quoting. Imported rows keep
          their original wording and any assumption made during migration.
        </p>
        <Button variant="outline" size="sm" onClick={openAdd} disabled={save.isPending}>
          <Plus className="mr-1 h-3.5 w-3.5" aria-hidden /> Add requirement
        </Button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingId ? "Edit requirement" : "Add requirement"}</DialogTitle>
          </DialogHeader>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <div className="space-y-1.5">
              <Label>Product / variant *</Label>
              {draft.product_id ? (
                <div className="flex items-center justify-between rounded-md border border-border p-2 text-sm">
                  <span>{draft.label}</span>
                  <Button type="button" variant="ghost" size="sm"
                    onClick={() => setDraft({ ...draft, product_id: "", product_variant_id: null, label: "" })}>
                    Change
                  </Button>
                </div>
              ) : (
                <VariantPicker
                  onPick={(hit) => setDraft({
                    ...draft, product_id: hit.product_id,
                    product_variant_id: hit.variant_id, label: hit.label,
                  })}
                />
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="space-y-1.5">
                <Label htmlFor="rq-freq">Frequency</Label>
                <Select value={draft.frequency}
                  onValueChange={(v) => setDraft({ ...draft, frequency: v ?? "" })}>
                  <SelectTrigger id="rq-freq"><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {FREQUENCIES.map((f) => (
                      <SelectItem key={f} value={f} className="capitalize">{f}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rq-min">Qty from</Label>
                <Input id="rq-min" type="number" min="0.001" step="0.001" value={draft.min_quantity}
                  onChange={(e) => setDraft({ ...draft, min_quantity: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rq-max">Qty to</Label>
                <Input id="rq-max" type="number" min="0.001" step="0.001" value={draft.max_quantity}
                  onChange={(e) => setDraft({ ...draft, max_quantity: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rq-uom">Unit</Label>
                <Select value={draft.uom_id}
                  onValueChange={(v) => setDraft({ ...draft, uom_id: v ?? "" })}>
                  <SelectTrigger id="rq-uom"><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {(uoms ?? []).map((u) => (
                      <SelectItem key={u.id} value={u.id}>{u.code}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="rq-supplier">Current supplier</Label>
                <Input id="rq-supplier" value={draft.current_supplier}
                  onChange={(e) => setDraft({ ...draft, current_supplier: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rq-rate">Their current rate (PKR)</Label>
                <Input id="rq-rate" type="number" min="0.01" step="0.01" value={draft.current_rate}
                  onChange={(e) => setDraft({ ...draft, current_rate: e.target.value })} />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rq-notes">Specification / notes</Label>
              <Textarea id="rq-notes" rows={3} value={draft.specification_notes}
                onChange={(e) => setDraft({ ...draft, specification_notes: e.target.value })} />
            </div>

            <DialogFooter>
              <Button type="submit" disabled={!draft.product_id || save.isPending}>
                {save.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {!rows.length ? (
        <p className="text-sm text-muted-foreground">
          No requirements recorded yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Product</TableHead>
                <TableHead>Frequency</TableHead>
                <TableHead className="text-right">Estimated quantity</TableHead>
                <TableHead>Current supplier</TableHead>
                <TableHead className="text-right">Their rate</TableHead>
                <TableHead>Notes</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const min = row.min_quantity ? Number(row.min_quantity) : null;
                const max = row.max_quantity ? Number(row.max_quantity) : null;
                const range = min !== null && max !== null && min !== max
                  ? `${min}–${max}` : (min ?? max) !== null ? String(min ?? max) : "—";
                return (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      {row.product_name ?? "—"}
                      {row.variant_name && (
                        <span className="block text-xs text-muted-foreground">{row.variant_name}</span>
                      )}
                    </TableCell>
                    <TableCell className="capitalize">{row.frequency ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {range}
                      {row.uom_code && range !== "—" && (
                        <span className="ml-1 text-xs text-muted-foreground">{row.uom_code}</span>
                      )}
                    </TableCell>
                    <TableCell>{row.current_supplier ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.current_rate ? Number(row.current_rate).toLocaleString("en-PK") : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {/* Migration notes run long; clamp so they cannot slide
                          under the action buttons. */}
                      <span className="line-clamp-2 max-w-[22rem]" title={row.specification_notes ?? undefined}>
                        {row.specification_notes ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button variant="ghost" size="sm" aria-label={`Edit ${row.product_name ?? "requirement"}`}
                        onClick={() => openEdit(row)} disabled={save.isPending}>
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                      </Button>
                      <Button variant="ghost" size="sm" aria-label={`Remove ${row.product_name ?? "requirement"}`}
                        onClick={() => remove(row.id)} disabled={save.isPending}>
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </Button>
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
