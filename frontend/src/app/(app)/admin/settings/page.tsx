"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

interface CompanySettings {
  company_name: string;
  legal_name: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  ntn: string | null;
  strn: string | null;
  address: string | null;
  city: string | null;
  bank_details: string | null;
  default_currency: string;
  timezone: string;
  default_payment_terms_days: number;
  quotation_terms: string | null;
  document_footer: string | null;
  logo_document_id: string | null;
  updated_at: string;
}

function SettingsForm() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => (await api<CompanySettings>("/api/v1/settings")).data,
  });
  // Local edits overlay the loaded settings; no state-sync effect needed.
  const [edits, setEdits] = useState<Partial<CompanySettings>>({});
  const form: CompanySettings | null = data ? { ...data, ...edits } : null;
  const setForm = (next: CompanySettings) => setEdits(next);

  const save = useMutation({
    mutationFn: () => {
      const { updated_at: _updatedAt, ...body } = form!;
      return api("/api/v1/admin/settings", { method: "PUT", body });
    },
    onSuccess: () => {
      toast.success("Company settings saved");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Save failed"),
  });

  if (isLoading || !form) return <Skeleton className="h-96 w-full" />;

  const text = (key: keyof CompanySettings, label: string, props: object = {}) => (
    <div className="space-y-1.5">
      <Label htmlFor={`st-${key}`}>{label}</Label>
      <Input id={`st-${key}`} value={(form[key] as string | number | null) ?? ""}
        {...props}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
    </div>
  );

  return (
    <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Card>
        <CardHeader><CardTitle className="text-base">Company identity</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {text("company_name", "Company name *", { required: true })}
          {text("legal_name", "Legal name")}
          {text("phone", "Phone")}
          {text("email", "Email")}
          {text("website", "Website")}
          {text("city", "City")}
          {text("ntn", "NTN")}
          {text("strn", "STRN")}
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="st-address">Address</Label>
            <Textarea id="st-address" value={form.address ?? ""}
              onChange={(e) => setForm({ ...form, address: e.target.value })} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Commercial defaults</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          {text("default_currency", "Currency", { maxLength: 3 })}
          {text("timezone", "Timezone")}
          <div className="space-y-1.5">
            <Label htmlFor="st-terms">Default payment terms (days)</Label>
            <Input id="st-terms" type="number" min={0} max={365}
              value={form.default_payment_terms_days}
              onChange={(e) =>
                setForm({ ...form, default_payment_terms_days: Number(e.target.value) })} />
          </div>
          <div className="space-y-1.5 sm:col-span-3">
            <Label htmlFor="st-bank">Bank / payment details (printed on documents)</Label>
            <Textarea id="st-bank" value={form.bank_details ?? ""}
              onChange={(e) => setForm({ ...form, bank_details: e.target.value })} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Document text</CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="st-qterms">Default quotation terms</Label>
            <Textarea id="st-qterms" rows={4} value={form.quotation_terms ?? ""}
              onChange={(e) => setForm({ ...form, quotation_terms: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="st-footer">Document footer</Label>
            <Input id="st-footer" value={form.document_footer ?? ""}
              onChange={(e) => setForm({ ...form, document_footer: e.target.value })} />
          </div>
        </CardContent>
      </Card>

      <Button type="submit" disabled={save.isPending || !form.company_name}>
        {save.isPending ? "Saving…" : "Save settings"}
      </Button>
      <p className="text-xs text-muted-foreground">
        Settings changes are audited and drive official quotation / invoice /
        challan / receipt output.
      </p>
    </form>
  );
}

export default function AdminSettingsPage() {
  return (
    <RequireAdmin>
      <main className="max-w-3xl space-y-6 p-6">
        <PageHeader
          title="Company settings"
          description="Identity, bank details, and document defaults for official output."
        />
        <SettingsForm />
      </main>
    </RequireAdmin>
  );
}
