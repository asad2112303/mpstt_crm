"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileDown } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import { formatKarachi } from "@/lib/types/crm";
import { DeliveryStatusBadge, type DeliveryRow } from "../page";
import { DocumentsPanel, type DocumentRow } from "@/components/documents-panel";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function openChallanPdf(deliveryId: string) {
  let headers: Record<string, string> = {};
  if (supabaseConfigured()) {
    const { data: { session } } = await createClient().auth.getSession();
    if (session) headers = { Authorization: `Bearer ${session.access_token}` };
  }
  const resp = await fetch(`${API_BASE}/api/v1/deliveries/${deliveryId}/challan`, { headers });
  if (!resp.ok) { toast.error("Could not load the challan PDF"); return; }
  const blob = await resp.blob();
  window.open(URL.createObjectURL(blob), "_blank", "noopener");
}

function CompleteForm({ delivery }: { delivery: DeliveryRow }) {
  const queryClient = useQueryClient();
  const [receiver, setReceiver] = useState("");
  const [designation, setDesignation] = useState("");
  const [results, setResults] = useState<Record<string, { delivered: string; rejected: string }>>(
    Object.fromEntries(
      delivery.items.map((i) => [i.id, { delivered: i.dispatched_quantity, rejected: "0" }]),
    ),
  );

  // POD document must exist (uploaded via the panel below).
  const { data: docs } = useQuery({
    queryKey: ["documents", "delivery", delivery.id],
    queryFn: async () =>
      (await api<DocumentRow[]>("/api/v1/documents", {
        searchParams: { entity_type: "delivery", entity_id: delivery.id },
      })).data,
    refetchInterval: 5000,
  });
  const signedDoc = docs?.[0];

  const complete = useMutation({
    mutationFn: () =>
      api(`/api/v1/deliveries/${delivery.id}/complete`, {
        method: "POST",
        idempotencyKey: newIdempotencyKey(),
        body: {
          receiver_name: receiver,
          receiver_designation: designation || null,
          signed_challan_document_id: signedDoc?.id ?? null,
          line_results: delivery.items.map((i) => ({
            delivery_item_id: i.id,
            delivered_quantity: results[i.id]?.delivered ?? i.dispatched_quantity,
            rejected_quantity: results[i.id]?.rejected ?? "0",
          })),
        },
      }),
    onSuccess: () => {
      toast.success("Delivery completed — stock and order status updated");
      queryClient.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Completion failed"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Complete delivery (POD required)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!signedDoc && (
          <Alert className="border-warning">
            <AlertTitle>Signed challan required</AlertTitle>
            <AlertDescription>
              Upload the signed challan (photo/scan) in the documents panel below
              before completing. Completion is blocked without POD evidence.
            </AlertDescription>
          </Alert>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="pod-name">Receiver name *</Label>
            <Input id="pod-name" required value={receiver}
              onChange={(e) => setReceiver(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pod-desig">Designation</Label>
            <Input id="pod-desig" value={designation}
              onChange={(e) => setDesignation(e.target.value)} />
          </div>
        </div>
        <div className="overflow-x-auto rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Dispatched</TableHead>
                <TableHead className="w-28">Delivered</TableHead>
                <TableHead className="w-28">Rejected</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {delivery.items.map((i) => (
                <TableRow key={i.id}>
                  <TableCell className="text-sm">{i.description_snapshot}</TableCell>
                  <TableCell className="text-right">{i.dispatched_quantity}</TableCell>
                  <TableCell>
                    <Input type="number" min="0" step="any"
                      aria-label="Delivered quantity"
                      value={results[i.id]?.delivered ?? ""}
                      onChange={(e) => setResults((p) => ({
                        ...p, [i.id]: { ...p[i.id], delivered: e.target.value },
                      }))} />
                  </TableCell>
                  <TableCell>
                    <Input type="number" min="0" step="any"
                      aria-label="Rejected quantity"
                      value={results[i.id]?.rejected ?? "0"}
                      onChange={(e) => setResults((p) => ({
                        ...p, [i.id]: { ...p[i.id], rejected: e.target.value },
                      }))} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <Button
          disabled={!receiver || !signedDoc || complete.isPending}
          onClick={() => {
            if (window.confirm(
              "Complete this delivery? Stock will be issued and the order status derived.",
            ))
              complete.mutate();
          }}>
          {complete.isPending ? "Completing…" : "Complete with POD"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function DeliveryDetailPage({
  params,
}: {
  params: Promise<{ deliveryId: string }>;
}) {
  const { deliveryId } = use(params);
  const queryClient = useQueryClient();

  const { data: delivery, isLoading, error } = useQuery({
    queryKey: ["deliveries", deliveryId],
    queryFn: async () => (await api<DeliveryRow>(`/api/v1/deliveries/${deliveryId}`)).data,
  });

  const act = useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) =>
      api(`/api/v1/deliveries/${deliveryId}/${action}`, { method: "POST", body }),
    onSuccess: () => {
      toast.success("Done");
      queryClient.invalidateQueries({ queryKey: ["deliveries"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Action failed"),
  });

  if (isLoading) return <main className="p-6"><Skeleton className="h-80 w-full" /></main>;
  if (error || !delivery)
    return (
      <main className="p-6">
        <p role="alert" className="text-sm text-destructive">Delivery not found.</p>
      </main>
    );

  return (
    <main className="space-y-6 p-6">
      <Link href="/deliveries"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Deliveries
      </Link>
      <PageHeader
        title={delivery.challan_number}
        description={`Order: `}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <DeliveryStatusBadge status={delivery.status} />
            <Button variant="outline" size="sm" onClick={() => void openChallanPdf(delivery.id)}>
              <FileDown className="mr-1 h-4 w-4" aria-hidden /> Challan PDF
            </Button>
            {delivery.status === "draft" && (
              <Button size="sm" variant="outline" disabled={act.isPending}
                onClick={() => act.mutate({ action: "dispatch" })}>
                Mark dispatched
              </Button>
            )}
            {["draft", "dispatched"].includes(delivery.status) && (
              <Button size="sm" variant="destructive" disabled={act.isPending}
                onClick={() => {
                  const reason = window.prompt("Cancellation reason (required):");
                  if (reason) act.mutate({ action: "cancel", body: { reason } });
                }}>
                Cancel
              </Button>
            )}
          </div>
        }
      />

      <Card>
        <CardHeader><CardTitle className="text-base">Challan lines</CardTitle></CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead>UOM</TableHead>
                  <TableHead className="text-right">Dispatched</TableHead>
                  <TableHead className="text-right">Delivered</TableHead>
                  <TableHead className="text-right">Rejected</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {delivery.items.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell className="text-sm">{i.description_snapshot}</TableCell>
                    <TableCell>{i.uom_code}</TableCell>
                    <TableCell className="text-right">{i.dispatched_quantity}</TableCell>
                    <TableCell className="text-right">{i.delivered_quantity}</TableCell>
                    <TableCell className="text-right">
                      {Number(i.rejected_quantity) > 0 ? (
                        <span className="text-destructive">{i.rejected_quantity}</span>
                      ) : i.rejected_quantity}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {delivery.pod && (
            <p className="mt-3 text-sm text-muted-foreground">
              POD: received by <strong>{delivery.pod.receiver_name}</strong>
              {delivery.pod.receiver_designation && ` (${delivery.pod.receiver_designation})`}
              {" "}on {formatKarachi(delivery.pod.received_at)}
            </p>
          )}
        </CardContent>
      </Card>

      {["draft", "dispatched"].includes(delivery.status) && (
        <CompleteForm delivery={delivery} />
      )}

      <div className="max-w-xl">
        <DocumentsPanel
          entityType="delivery"
          entityId={delivery.id}
          documentType="signed_challan"
          organizationId={delivery.organization_id}
          title="POD evidence (signed challan / photos)"
        />
      </div>
    </main>
  );
}
