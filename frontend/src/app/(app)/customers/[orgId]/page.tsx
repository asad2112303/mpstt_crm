"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ORG_TYPE_LABELS, formatKarachi, type Organization } from "@/lib/types/crm";
import {
  ActivitiesTab, BranchesTab, ContactsTab, PricesTab, SamplesTab, TasksTab,
} from "@/components/org-tabs";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface TimelineEvent {
  kind: string;
  at: string;
  title: string;
  detail: string | null;
  reference_id: string | null;
}

function CommercialCard({ org }: { org: Organization }) {
  const queryClient = useQueryClient();
  const profile = org.customer_profile!;
  const [terms, setTerms] = useState(String(profile.payment_terms_days));
  const [creditLimit, setCreditLimit] = useState(profile.credit_limit ?? "");

  const patch = useMutation({
    mutationFn: () =>
      api(`/api/v1/customers/${org.id}`, {
        method: "PATCH",
        body: {
          payment_terms_days: Number(terms),
          credit_limit: creditLimit === "" ? null : creditLimit,
        },
      }),
    onSuccess: () => {
      toast.success("Commercial profile updated");
      queryClient.invalidateQueries({ queryKey: ["customers", org.id] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed"),
  });

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Commercial profile</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p><span className="text-muted-foreground">Customer code:</span> {profile.customer_code}</p>
        <p><span className="text-muted-foreground">Customer since:</span> {profile.customer_since}</p>
        <p className="flex items-center gap-2">
          <span className="text-muted-foreground">Account:</span>
          <Badge variant={profile.account_status === "active" ? "outline" : "destructive"}>
            {profile.account_status}
          </Badge>
        </p>
        <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
          <div className="space-y-1.5">
            <Label htmlFor="cc-terms">Payment terms (days)</Label>
            <Input id="cc-terms" type="number" min="0" max="365" value={terms}
              onChange={(e) => setTerms(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cc-credit">Credit limit (PKR)</Label>
            <Input id="cc-credit" type="number" min="0" step="0.01" value={creditLimit}
              placeholder="None" onChange={(e) => setCreditLimit(e.target.value)} />
          </div>
        </div>
        <Button size="sm" onClick={() => patch.mutate()} disabled={patch.isPending}>
          Save
        </Button>
      </CardContent>
    </Card>
  );
}

function TimelineTab({ orgId }: { orgId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["customers", orgId, "timeline"],
    queryFn: async () =>
      (await api<TimelineEvent[]>(`/api/v1/customers/${orgId}/timeline`)).data,
  });
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!data?.length) return <p className="text-sm text-muted-foreground">No history yet.</p>;
  return (
    <ol className="space-y-2">
      {data.map((e, i) => (
        <li key={`${e.reference_id}-${i}`} className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-center justify-between">
            <Badge variant="secondary">{e.kind}</Badge>
            <span className="text-xs text-muted-foreground">{formatKarachi(e.at)}</span>
          </div>
          <p className="mt-1 text-sm font-medium">{e.title}</p>
          {e.detail && <p className="text-sm text-muted-foreground">{e.detail}</p>}
        </li>
      ))}
    </ol>
  );
}

export default function CustomerDetailPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  const { data: org, isLoading, error } = useQuery({
    queryKey: ["customers", orgId],
    queryFn: async () => (await api<Organization>(`/api/v1/customers/${orgId}`)).data,
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !org)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Customer not found.</p>
      </main>
    );

  return (
    <main className="space-y-6 p-6">
      <Link href="/customers"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Customers
      </Link>
      <PageHeader
        title={org.name}
        description={`${org.customer_profile?.customer_code} · ${ORG_TYPE_LABELS[org.org_type]}${org.city ? ` · ${org.city}` : ""}`}
        actions={<Badge className="bg-primary text-primary-foreground border-transparent">Customer</Badge>}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Identity</CardTitle></CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            <p><span className="text-muted-foreground">Org code:</span> {org.org_code}</p>
            <p><span className="text-muted-foreground">Phone:</span> {org.phone ?? "—"}</p>
            <p><span className="text-muted-foreground">NTN:</span> {org.ntn ?? "—"}</p>
            <p><span className="text-muted-foreground">Converted:</span> {formatKarachi(org.converted_at, false)}</p>
            <p className="text-xs text-muted-foreground">
              Prospect history (activities, samples, prices) is preserved below.
            </p>
          </CardContent>
        </Card>
        <CommercialCard org={org} />
      </div>

      <Tabs defaultValue="timeline">
        <TabsList className="flex-wrap">
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="contacts">Contacts</TabsTrigger>
          <TabsTrigger value="branches">Branches</TabsTrigger>
          <TabsTrigger value="activities">Activities</TabsTrigger>
          <TabsTrigger value="samples">Samples</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
          <TabsTrigger value="prices">Prices</TabsTrigger>
        </TabsList>
        <TabsContent value="timeline" className="pt-4"><TimelineTab orgId={orgId} /></TabsContent>
        <TabsContent value="contacts" className="pt-4"><ContactsTab orgId={orgId} /></TabsContent>
        <TabsContent value="branches" className="pt-4"><BranchesTab orgId={orgId} /></TabsContent>
        <TabsContent value="activities" className="pt-4"><ActivitiesTab orgId={orgId} /></TabsContent>
        <TabsContent value="samples" className="pt-4"><SamplesTab orgId={orgId} /></TabsContent>
        <TabsContent value="tasks" className="pt-4"><TasksTab orgId={orgId} /></TabsContent>
        <TabsContent value="prices" className="pt-4"><PricesTab orgId={orgId} /></TabsContent>
      </Tabs>
    </main>
  );
}
