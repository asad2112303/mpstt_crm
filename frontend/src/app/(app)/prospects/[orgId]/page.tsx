"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import {
  ORG_TYPE_LABELS, STAGE_LABELS, formatKarachi,
  type Organization, type ProspectStage,
} from "@/lib/types/crm";
import { ConvertDialog } from "@/components/convert-dialog";
import { EditOrganizationDialog } from "@/components/edit-org-dialog";
import {
  ActivitiesTab, BranchesTab, ContactsTab, PricesTab, RequirementsTab, SamplesTab,
  TasksTab,
} from "@/components/org-tabs";
import { PageHeader } from "@/components/page-header";
import { StageBadge } from "@/components/stage-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const MANUAL_STAGES: ProspectStage[] = [
  "targeted", "visited", "requirement_collected", "sample_provided",
  "quotation_sent", "negotiation", "deferred", "lost",
];

function OverviewTab({ org }: { org: Organization }) {
  const queryClient = useQueryClient();
  const profile = org.prospect_profile;
  const [stage, setStage] = useState<ProspectStage | "">("");
  const [reason, setReason] = useState("");

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/v1/prospects/${org.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      toast.success("Updated");
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      setStage(""); setReason("");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed"),
  });

  const needsReason = stage === "lost" || stage === "deferred";

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">Identity</CardTitle>
          <EditOrganizationDialog org={org} />
        </CardHeader>
        <CardContent className="space-y-1.5 text-sm">
          <p><span className="text-muted-foreground">Code:</span> {org.org_code}</p>
          <p><span className="text-muted-foreground">Type:</span> {ORG_TYPE_LABELS[org.org_type]}</p>
          <p><span className="text-muted-foreground">City / Area:</span> {org.city ?? "—"} {org.area ? `· ${org.area}` : ""}</p>
          <p><span className="text-muted-foreground">Phone:</span> {org.phone ?? "—"}</p>
          <p><span className="text-muted-foreground">Source:</span> {org.source ?? "—"}</p>
          <p><span className="text-muted-foreground">Created:</span> {formatKarachi(org.created_at, false)}</p>
          {org.notes && <p className="pt-2 text-muted-foreground">{org.notes}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Pipeline</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          {profile ? (
            <>
              <p className="flex items-center gap-2">
                <span className="text-muted-foreground">Stage:</span>
                <StageBadge stage={profile.stage} />
              </p>
              <p><span className="text-muted-foreground">Next action:</span> {profile.next_action_summary ?? "—"}</p>
              <p><span className="text-muted-foreground">Last activity:</span> {formatKarachi(profile.last_activity_at)}</p>
              {profile.lost_reason && <p><span className="text-muted-foreground">Lost reason:</span> {profile.lost_reason}</p>}
              {profile.deferred_reason && <p><span className="text-muted-foreground">Deferred reason:</span> {profile.deferred_reason}</p>}

              {profile.stage !== "won" && (
                <div className="space-y-2 border-t border-border pt-3">
                  <Label htmlFor="stage-move">Move stage</Label>
                  <div className="flex flex-wrap items-end gap-2">
                    <Select value={stage} onValueChange={(v) => setStage(v as ProspectStage)}>
                      <SelectTrigger id="stage-move" className="w-56">
                        <SelectValue placeholder="Select stage…" />
                      </SelectTrigger>
                      <SelectContent>
                        {MANUAL_STAGES.map((s) => (
                          <SelectItem key={s} value={s}>{STAGE_LABELS[s]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {needsReason && (
                      <Input className="w-64" placeholder="Reason (required)" value={reason}
                        onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
                    )}
                    <Button size="sm"
                      disabled={!stage || (needsReason && !reason) || patch.isPending}
                      onClick={() =>
                        patch.mutate({
                          stage,
                          ...(stage === "lost" ? { lost_reason: reason } : {}),
                          ...(stage === "deferred" ? { deferred_reason: reason } : {}),
                        })
                      }>
                      Apply
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    “Won” is set automatically by the first confirmed order.
                  </p>
                </div>
              )}
            </>
          ) : (
            <p className="text-muted-foreground">No prospect profile.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ProspectDetailPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  const { data: org, isLoading, error } = useQuery({
    queryKey: ["prospects", orgId],
    queryFn: async () => (await api<Organization>(`/api/v1/prospects/${orgId}`)).data,
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !org)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Organization not found.</p>
      </main>
    );

  return (
    <main className="space-y-6 p-6">
      <Link href="/prospects"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Prospects
      </Link>
      <PageHeader
        title={org.name}
        description={`${org.org_code} · ${ORG_TYPE_LABELS[org.org_type]}${org.city ? ` · ${org.city}` : ""}`}
        actions={
          <div className="flex items-center gap-2">
            {org.prospect_profile && <StageBadge stage={org.prospect_profile.stage} />}
            {org.lifecycle_status === "prospect" && (
              <ConvertDialog orgId={org.id} orgName={org.name} />
            )}
          </div>
        }
      />
      <Tabs defaultValue="overview">
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="contacts">Contacts</TabsTrigger>
          <TabsTrigger value="branches">Branches</TabsTrigger>
          <TabsTrigger value="requirements">Requirements</TabsTrigger>
          <TabsTrigger value="activities">Activities</TabsTrigger>
          <TabsTrigger value="samples">Samples</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
          <TabsTrigger value="prices">Prices</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="pt-4"><OverviewTab org={org} /></TabsContent>
        <TabsContent value="contacts" className="pt-4"><ContactsTab orgId={orgId} /></TabsContent>
        <TabsContent value="branches" className="pt-4"><BranchesTab orgId={orgId} /></TabsContent>
        <TabsContent value="requirements" className="pt-4"><RequirementsTab orgId={orgId} /></TabsContent>
        <TabsContent value="activities" className="pt-4"><ActivitiesTab orgId={orgId} /></TabsContent>
        <TabsContent value="samples" className="pt-4"><SamplesTab orgId={orgId} /></TabsContent>
        <TabsContent value="tasks" className="pt-4"><TasksTab orgId={orgId} /></TabsContent>
        <TabsContent value="prices" className="pt-4"><PricesTab orgId={orgId} /></TabsContent>
      </Tabs>
    </main>
  );
}
