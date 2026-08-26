"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Upload } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import { formatKarachi } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

interface ImportRowOut {
  id: string;
  row_number: number;
  normalized: Record<string, unknown>;
  validation_errors: string[];
  duplicate_of: string | null;
  classification: "prospect" | "customer";
  status: string;
  reject_reason: string | null;
}

interface Batch {
  id: string;
  filename: string;
  status: "pending_review" | "imported" | "discarded";
  source_count: number;
  ready_count: number;
  error_count: number;
  duplicate_count: number;
  imported_count: number;
  rejected_count: number;
  checksum_sha256: string;
  created_at: string;
  rows?: ImportRowOut[];
}

async function authHeader(): Promise<Record<string, string>> {
  if (!supabaseConfigured()) return {};
  const { data: { session } } = await createClient().auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function rowBadge(status: string) {
  const styles: Record<string, string> = {
    ready: "bg-primary/15 text-primary",
    error: "bg-destructive/15 text-destructive",
    duplicate: "bg-warning/20 text-warning-foreground",
    imported: "bg-primary text-primary-foreground",
    rejected: "bg-destructive/15 text-destructive",
    skipped: "bg-muted text-muted-foreground",
  };
  return (
    <Badge className={`border-transparent capitalize ${styles[status] ?? ""}`}>{status}</Badge>
  );
}

function ImportsInner() {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const { data: batches, isLoading } = useQuery({
    queryKey: ["imports"],
    queryFn: async () => (await api<Batch[]>("/api/v1/admin/imports")).data,
  });
  const { data: detail } = useQuery({
    queryKey: ["imports", selected],
    queryFn: async () => (await api<Batch>(`/api/v1/admin/imports/${selected}`)).data,
    enabled: Boolean(selected),
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(`${API_BASE}/api/v1/admin/imports`, {
        method: "POST", headers: await authHeader(), body: form,
      });
      const json = await resp.json();
      if (!resp.ok) throw new ApiError(resp.status, json.error);
      return json.data as Batch;
    },
    onSuccess: (batch) => {
      toast.success(`Staged ${batch.source_count} rows for review`);
      queryClient.invalidateQueries({ queryKey: ["imports"] });
      setSelected(batch.id);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  });

  const approve = useMutation({
    mutationFn: (includeDuplicates: boolean) =>
      api(`/api/v1/admin/imports/${selected}/approve`, {
        method: "POST",
        body: { include_duplicates: includeDuplicates },
      }),
    onSuccess: () => {
      toast.success("Batch imported");
      queryClient.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Approval failed"),
  });

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Legacy data import"
        description="Parse → validate → review duplicates → Admin approve → transactional import. Never merged automatically."
        actions={
          <>
            <input ref={fileInput} type="file" hidden accept=".csv"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }} />
            <Button onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
              <FileUp className="mr-1 h-4 w-4" aria-hidden />
              {upload.isPending ? "Staging…" : "Upload CSV"}
            </Button>
          </>
        }
      />

      <p className="text-xs text-muted-foreground">
        Columns: <code>name</code> (required), <code>org_type</code>, <code>city</code>,{" "}
        <code>area</code>, <code>source</code>, <code>phone</code>, <code>contact_name</code>,{" "}
        <code>contact_phone</code>, <code>customer_since</code> (YYYY-MM-DD marks a confirmed
        customer), <code>payment_terms_days</code>, <code>notes</code>. Unknown columns are
        rejected rather than guessed.
      </p>

      {isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : !batches?.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Upload className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">No import batches yet.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead>Uploaded</TableHead>
                <TableHead className="text-right">Rows</TableHead>
                <TableHead className="text-right">Ready</TableHead>
                <TableHead className="text-right">Errors</TableHead>
                <TableHead className="text-right">Duplicates</TableHead>
                <TableHead className="text-right">Imported</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {batches.map((b) => (
                <TableRow key={b.id}
                  className={selected === b.id ? "bg-secondary/50" : "cursor-pointer"}
                  onClick={() => setSelected(b.id)}>
                  <TableCell className="font-medium">{b.filename}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatKarachi(b.created_at)}
                  </TableCell>
                  <TableCell className="text-right">{b.source_count}</TableCell>
                  <TableCell className="text-right">{b.ready_count}</TableCell>
                  <TableCell className="text-right">{b.error_count}</TableCell>
                  <TableCell className="text-right">{b.duplicate_count}</TableCell>
                  <TableCell className="text-right">{b.imported_count}</TableCell>
                  <TableCell>{rowBadge(b.status === "pending_review" ? "ready" : b.status)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {detail && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">
              {detail.filename} — review ({detail.rows?.length ?? 0} rows)
            </CardTitle>
            {detail.status === "pending_review" && (
              <div className="flex gap-2">
                <Button size="sm" disabled={approve.isPending}
                  onClick={() => {
                    if (window.confirm(
                      `Import ${detail.ready_count} ready rows? Duplicates will be skipped.`,
                    )) approve.mutate(false);
                  }}>
                  Approve (skip duplicates)
                </Button>
                {detail.duplicate_count > 0 && (
                  <Button size="sm" variant="outline" disabled={approve.isPending}
                    onClick={() => {
                      if (window.confirm(
                        "Import duplicates too? Only do this after confirming they are genuinely different organizations.",
                      )) approve.mutate(true);
                    }}>
                    Approve incl. duplicates
                  </Button>
                )}
              </div>
            )}
          </CardHeader>
          <CardContent>
            <div className="max-h-96 overflow-auto rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>City</TableHead>
                    <TableHead>Class</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Problems</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(detail.rows ?? []).map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{r.row_number}</TableCell>
                      <TableCell className="text-sm font-medium">
                        {String(r.normalized.name ?? "")}
                      </TableCell>
                      <TableCell className="text-sm">{String(r.normalized.org_type ?? "")}</TableCell>
                      <TableCell className="text-sm">{String(r.normalized.city ?? "—")}</TableCell>
                      <TableCell className="capitalize">{r.classification}</TableCell>
                      <TableCell>{rowBadge(r.status)}</TableCell>
                      <TableCell className="max-w-sm text-xs text-destructive">
                        {r.validation_errors.join("; ")}
                        {r.duplicate_of && "Similar organization already exists"}
                        {r.reject_reason}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Checksum {detail.checksum_sha256.slice(0, 16)}… · ready = imported + rejected
              after approval.
            </p>
          </CardContent>
        </Card>
      )}
    </main>
  );
}

export default function ImportsPage() {
  return (
    <RequireAdmin>
      <ImportsInner />
    </RequireAdmin>
  );
}
