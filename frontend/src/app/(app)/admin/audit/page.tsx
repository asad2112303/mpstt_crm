"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { formatKarachi } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

interface AuditRow {
  id: number;
  user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  old_data: Record<string, unknown> | null;
  new_data: Record<string, unknown> | null;
  reason: string | null;
  request_id: string | null;
  created_at: string;
}

function AuditTable() {
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit", { action, entityType, page }],
    queryFn: async () =>
      await api<AuditRow[]>("/api/v1/admin/audit", {
        searchParams: {
          action: action || undefined,
          entity_type: entityType || undefined,
          page,
          page_size: 50,
        },
      }),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Input placeholder="Filter by action (e.g. order.)" className="w-64" value={action}
          onChange={(e) => { setAction(e.target.value); setPage(1); }}
          aria-label="Filter by action" />
        <Input placeholder="Entity type (e.g. sales_order)" className="w-56" value={entityType}
          onChange={(e) => { setEntityType(e.target.value); setPage(1); }}
          aria-label="Filter by entity type" />
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load audit log: {error instanceof ApiError ? error.message : "unknown"}
        </p>
      ) : !data?.data.length ? (
        <p className="text-sm text-muted-foreground">No audit entries match.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Entity</TableHead>
                  <TableHead>Change</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatKarachi(r.created_at)}
                    </TableCell>
                    <TableCell><Badge variant="secondary">{r.action}</Badge></TableCell>
                    <TableCell className="text-xs">
                      {r.entity_type}
                      {r.entity_id && (
                        <span className="block max-w-40 truncate text-muted-foreground">
                          {r.entity_id}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-md">
                      <pre className="max-h-24 overflow-auto whitespace-pre-wrap text-[11px] text-muted-foreground">
{JSON.stringify({ old: r.old_data, new: r.new_data }, null, 1)}
                      </pre>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{r.reason ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} entries (append-only)</span>
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
    </div>
  );
}

export default function AuditPage() {
  return (
    <RequireAdmin>
      <main className="space-y-6 p-6">
        <PageHeader
          title="Audit log"
          description="Tamper-resistant record of every important mutation."
        />
        <AuditTable />
      </main>
    </RequireAdmin>
  );
}
