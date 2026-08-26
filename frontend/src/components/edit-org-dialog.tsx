"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ORG_TYPE_LABELS, type Organization, type OrgType } from "@/lib/types/crm";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

/** Edits organization identity — works for prospects and customers alike. */
export function EditOrganizationDialog({ org }: { org: Organization }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: org.name,
    org_type: org.org_type as OrgType,
    city: org.city ?? "",
    area: org.area ?? "",
    phone: org.phone ?? "",
    source: org.source ?? "",
    ntn: org.ntn ?? "",
    notes: org.notes ?? "",
  });

  const save = useMutation({
    mutationFn: () =>
      api(`/api/v1/prospects/${org.id}`, {
        method: "PATCH",
        body: {
          name: form.name,
          org_type: form.org_type,
          city: form.city || null,
          area: form.area || null,
          phone: form.phone || null,
          source: form.source || null,
          ntn: form.ntn || null,
          notes: form.notes || null,
        },
      }),
    onSuccess: () => {
      toast.success("Organization updated");
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      queryClient.invalidateQueries({ queryKey: ["customers"] });
      setOpen(false);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Update failed"),
  });

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Pencil className="mr-1 h-3.5 w-3.5" aria-hidden /> Edit details
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Edit {org.org_code}</DialogTitle></DialogHeader>
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(e) => { e.preventDefault(); save.mutate(); }}
          >
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="eo-name">Organization name *</Label>
              <Input id="eo-name" required minLength={2} value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-type">Type</Label>
              <Select value={form.org_type}
                onValueChange={(v) => setForm({ ...form, org_type: v as OrgType })}>
                <SelectTrigger id="eo-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ORG_TYPE_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-phone">Phone</Label>
              <Input id="eo-phone" value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-city">City</Label>
              <Input id="eo-city" value={form.city}
                onChange={(e) => setForm({ ...form, city: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-area">Area</Label>
              <Input id="eo-area" value={form.area}
                onChange={(e) => setForm({ ...form, area: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-source">Source</Label>
              <Input id="eo-source" value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="eo-ntn">NTN</Label>
              <Input id="eo-ntn" value={form.ntn}
                onChange={(e) => setForm({ ...form, ntn: e.target.value })} />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="eo-notes">Notes</Label>
              <Textarea id="eo-notes" rows={4} value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
            <DialogFooter className="sm:col-span-2">
              <Button type="submit" disabled={!form.name || save.isPending}>
                {save.isPending ? "Saving…" : "Save changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
