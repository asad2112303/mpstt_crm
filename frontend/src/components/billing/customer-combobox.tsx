"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, UserRound } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { BillingCustomer } from "@/lib/types/billing";
import { ORG_TYPE_LABELS, type OrgType } from "@/lib/types/crm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

function InlineNewCustomer({
  name,
  onCancel,
  onCreated,
}: {
  name: string;
  onCancel: () => void;
  onCreated: (customer: BillingCustomer) => void;
}) {
  const [orgType, setOrgType] = useState<OrgType>("hospital");
  const [city, setCity] = useState("");
  const [phone, setPhone] = useState("");
  const [contact, setContact] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const resp = await api<{ id: string; name: string; org_code: string;
        city: string | null; phone: string | null; lifecycle_status: string }>(
        "/api/v1/prospects",
        {
          method: "POST",
          body: {
            name,
            org_type: orgType,
            city: city || null,
            phone: phone || null,
            contact_name: contact || null,
            // The user is billing them right now; duplicate warnings would
            // only get in the way at the counter.
            confirm_duplicate: true,
          },
        },
      );
      onCreated(resp.data);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not add the customer.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-primary/40 bg-card p-3 shadow-md">
      <p className="text-sm font-medium">Add “{name}” as a customer</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="nc-type" className="text-xs">Type</Label>
          <select
            id="nc-type"
            value={orgType}
            onChange={(e) => setOrgType(e.target.value as OrgType)}
            className="h-9 w-full rounded-lg border border-input bg-transparent px-2 text-sm"
          >
            {(Object.keys(ORG_TYPE_LABELS) as OrgType[]).map((t) => (
              <option key={t} value={t}>{ORG_TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="nc-city" className="text-xs">City</Label>
          <Input id="nc-city" value={city} onChange={(e) => setCity(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="nc-phone" className="text-xs">Phone</Label>
          <Input id="nc-phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="nc-contact" className="text-xs">Contact person</Label>
          <Input id="nc-contact" value={contact} onChange={(e) => setContact(e.target.value)} />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Add customer"}
        </Button>
      </div>
    </div>
  );
}

export function CustomerCombobox({
  selected,
  onSelect,
}: {
  selected: BillingCustomer | null;
  onSelect: (customer: BillingCustomer | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["billing-customers", query],
    queryFn: async () =>
      (
        await api<BillingCustomer[]>("/api/v1/billing/customers", {
          searchParams: { search: query.trim() || undefined },
        })
      ).data,
    enabled: open && !adding,
  });

  useEffect(() => {
    function away(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
        setAdding(false);
      }
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const results = data ?? [];

  return (
    <div className="relative" ref={boxRef}>
      <Input
        value={selected ? selected.name : query}
        placeholder="Search customers…"
        aria-label="Customer"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          if (selected) onSelect(null);
          setQuery(e.target.value);
          setOpen(true);
        }}
      />
      {open && (
        <div className="absolute z-30 mt-1 w-[min(30rem,90vw)] rounded-lg border border-border bg-popover shadow-lg">
          {adding ? (
            <InlineNewCustomer
              name={query.trim()}
              onCancel={() => setAdding(false)}
              onCreated={(c) => {
                onSelect(c);
                setAdding(false);
                setOpen(false);
              }}
            />
          ) : (
            <ul className="max-h-64 overflow-auto py-1">
              {results.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(c);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted",
                      selected?.id === c.id && "bg-muted",
                    )}
                  >
                    <UserRound className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{c.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {c.org_code}
                        {c.city ? ` · ${c.city}` : ""}
                        {c.phone ? ` · ${c.phone}` : ""}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
              {results.length === 0 && (
                <li className="px-3 py-2 text-sm text-muted-foreground">
                  {query ? "No matching customer." : "Start typing to search."}
                </li>
              )}
              {query.trim().length > 1 && (
                <li className="border-t border-border">
                  <button
                    type="button"
                    onClick={() => setAdding(true)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium text-primary hover:bg-muted"
                  >
                    <Plus className="h-4 w-4" aria-hidden />
                    Add “{query.trim()}” as a customer
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
