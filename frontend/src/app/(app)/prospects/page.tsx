"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import {
  ORG_TYPE_LABELS,
  STAGE_LABELS,
  formatKarachi,
  type Organization,
  type OrgType,
  type ProspectStage,
} from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { StageBadge } from "@/components/stage-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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

interface DuplicateHit {
  organization_id: string;
  org_code: string;
  name: string;
  city: string | null;
  lifecycle_status: string;
  same_phone: boolean;
}

function NewProspectDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: "", org_type: "hospital" as OrgType, city: "", area: "",
    source: "", phone: "", contact_name: "",
  });
  const [duplicates, setDuplicates] = useState<DuplicateHit[] | null>(null);

  const create = useMutation({
    mutationFn: (confirmDuplicate: boolean) =>
      api<Organization>("/api/v1/prospects", {
        method: "POST",
        body: {
          ...form,
          city: form.city || null,
          area: form.area || null,
          source: form.source || null,
          phone: form.phone || null,
          contact_name: form.contact_name || null,
          confirm_duplicate: confirmDuplicate,
        },
      }),
    onSuccess: (resp) => {
      toast.success(`Prospect ${resp.data.org_code} created`);
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      setOpen(false);
      setDuplicates(null);
      setForm({ name: "", org_type: "hospital", city: "", area: "", source: "", phone: "", contact_name: "" });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "DUPLICATE_SUSPECTED") {
        const hits = (e.fieldErrors["duplicates"] ?? []).map(
          (raw) => JSON.parse(raw) as DuplicateHit,
        );
        setDuplicates(hits);
        return;
      }
      toast.error(e instanceof ApiError ? e.message : "Failed to create prospect");
    },
  });

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setDuplicates(null); }}>
      <DialogTrigger className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Plus className="h-4 w-4" aria-hidden /> New prospect
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>New prospect</DialogTitle></DialogHeader>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); create.mutate(false); }}
        >
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="np-name">Organization name *</Label>
            <Input id="np-name" required minLength={2} value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-type">Type *</Label>
            <Select value={form.org_type}
              onValueChange={(v) => setForm({ ...form, org_type: v as OrgType })}>
              <SelectTrigger id="np-type"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(ORG_TYPE_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-city">City</Label>
            <Input id="np-city" value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-area">Area</Label>
            <Input id="np-area" value={form.area}
              onChange={(e) => setForm({ ...form, area: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-source">Source</Label>
            <Input id="np-source" placeholder="field visit, referral…" value={form.source}
              onChange={(e) => setForm({ ...form, source: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-phone">Phone</Label>
            <Input id="np-phone" value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="np-contact">Contact person</Label>
            <Input id="np-contact" value={form.contact_name}
              onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
          </div>

          {duplicates && (
            <Alert className="sm:col-span-2 border-warning">
              <AlertTitle>Similar organizations already exist</AlertTitle>
              <AlertDescription>
                <ul className="mt-1 list-disc pl-4 text-xs">
                  {duplicates.map((d) => (
                    <li key={d.organization_id}>
                      <Link href={`/prospects/${d.organization_id}`} className="text-primary underline">
                        {d.org_code} — {d.name}
                      </Link>{" "}
                      ({d.lifecycle_status}{d.same_phone ? ", same phone" : ""})
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs">
                  Records are never merged automatically. Create anyway only if this
                  is genuinely a different organization.
                </p>
              </AlertDescription>
            </Alert>
          )}

          <DialogFooter className="sm:col-span-2">
            {duplicates ? (
              <Button type="button" variant="destructive" disabled={create.isPending}
                onClick={() => create.mutate(true)}>
                Create anyway
              </Button>
            ) : (
              <Button type="submit" disabled={!form.name || create.isPending}>
                {create.isPending ? "Creating…" : "Create prospect"}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const FILTER_STAGES: (ProspectStage | "")[] = [
  "", "targeted", "visited", "requirement_collected", "sample_provided",
  "quotation_sent", "negotiation", "deferred", "lost",
];

export default function ProspectsPage() {
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState<ProspectStage | "">("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["prospects", { search, stage, page }],
    queryFn: async () =>
      await api<Organization[]>("/api/v1/prospects", {
        searchParams: { search: search || undefined, stage: stage || undefined, page, page_size: 25 },
      }),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Prospects"
        description="Field-sales pipeline from first target to first order."
        actions={<NewProspectDialog />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search name, code, city, phone…"
          className="w-72"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          aria-label="Search prospects"
        />
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by stage">
          {FILTER_STAGES.map((s) => (
            <button
              key={s || "all"}
              onClick={() => { setStage(s); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                stage === s
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card hover:bg-muted",
              )}
            >
              {s === "" ? "All" : STAGE_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load prospects: {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Building2 className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No prospects match. Create the first one.</p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Code</TableHead>
                  <TableHead>Organization</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>City</TableHead>
                  <TableHead>Stage</TableHead>
                  <TableHead>Next action</TableHead>
                  <TableHead>Last activity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.org_code}</TableCell>
                    <TableCell>
                      <Link href={`/prospects/${p.id}`} className="font-medium text-primary hover:underline">
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell>{ORG_TYPE_LABELS[p.org_type]}</TableCell>
                    <TableCell className="text-muted-foreground">{p.city ?? "—"}</TableCell>
                    <TableCell>
                      {p.prospect_profile && <StageBadge stage={p.prospect_profile.stage} />}
                    </TableCell>
                    <TableCell className="max-w-56 truncate text-sm text-muted-foreground">
                      {p.prospect_profile?.next_action_summary ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatKarachi(p.prospect_profile?.last_activity_at, false)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} prospects</span>
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
