"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { formatKarachi, type ActionQueueRow } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { StageBadge } from "@/components/stage-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

type Filter = "all" | "overdue" | "missing";

export default function FollowUpsPage() {
  const [filter, setFilter] = useState<Filter>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["action-queue", filter],
    queryFn: async () =>
      (
        await api<ActionQueueRow[]>("/api/v1/prospects/action-queue", {
          searchParams: {
            overdue_only: filter === "overdue" ? true : undefined,
            missing_next_action: filter === "missing" ? true : undefined,
          },
        })
      ).data,
    refetchInterval: 60_000,
  });

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Follow-up queue"
        description="Every active prospect stays visible — no opportunity goes silent."
      />

      <div className="flex gap-1" role="group" aria-label="Queue filter">
        {(
          [
            ["all", "All active"],
            ["overdue", "Overdue"],
            ["missing", "No next action"],
          ] as [Filter, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setFilter(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium",
              filter === value
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-muted",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load queue: {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : !data?.length ? (
        <div className="rounded-lg border border-dashed border-border p-12 text-center text-sm text-muted-foreground">
          Nothing here — every active prospect has a scheduled next action.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Prospect</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead>Next action</TableHead>
                <TableHead>Due</TableHead>
                <TableHead>Last activity</TableHead>
                <TableHead>Flags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => (
                <TableRow key={r.organization_id}>
                  <TableCell>
                    <Link href={`/prospects/${r.organization_id}`}
                      className="font-medium text-primary hover:underline">
                      {r.name}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {r.org_code}{r.city ? ` · ${r.city}` : ""}
                    </p>
                  </TableCell>
                  <TableCell><StageBadge stage={r.stage} /></TableCell>
                  <TableCell className="max-w-56 truncate text-sm">
                    {r.next_action_summary ?? "—"}
                  </TableCell>
                  <TableCell className="text-sm">{formatKarachi(r.next_task_due_at)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {r.days_since_last_activity != null
                      ? `${r.days_since_last_activity}d ago`
                      : "Never"}
                  </TableCell>
                  <TableCell className="space-x-1">
                    {r.overdue && <Badge variant="destructive">Overdue</Badge>}
                    {r.missing_next_action && (
                      <Badge className="border-transparent bg-warning/20 text-warning-foreground">
                        No next action
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  );
}
