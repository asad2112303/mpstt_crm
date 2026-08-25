"use client";

import type { AttributeDef } from "@/lib/types/catalogue";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export type AttributeValues = Record<string, string | number | boolean>;

/** Dynamic specification form driven by the category attribute schema. */
export function AttributeForm({
  defs,
  values,
  onChange,
  fieldErrors,
}: {
  defs: AttributeDef[];
  values: AttributeValues;
  onChange: (next: AttributeValues) => void;
  fieldErrors?: Record<string, string[]>;
}) {
  if (!defs.length) {
    return (
      <p className="text-sm text-muted-foreground">
        This category defines no specifications.
      </p>
    );
  }

  function set(key: string, value: string | number | boolean | undefined) {
    const next = { ...values };
    if (value === undefined || value === "") delete next[key];
    else next[key] = value;
    onChange(next);
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {defs.map((def) => {
        const id = `attr-${def.key}`;
        const errors = fieldErrors?.[`attributes.${def.key}`];
        const label = (
          <Label htmlFor={id}>
            {def.label}
            {def.unit ? ` (${def.unit})` : ""}
            {def.required && <span className="text-destructive"> *</span>}
          </Label>
        );
        return (
          <div key={def.key} className="space-y-1.5">
            {def.type !== "boolean" && label}
            {def.type === "text" && (
              <Input
                id={id}
                value={(values[def.key] as string) ?? ""}
                onChange={(e) => set(def.key, e.target.value)}
              />
            )}
            {def.type === "number" && (
              <Input
                id={id}
                type="number"
                min={def.min}
                max={def.max}
                step="any"
                value={values[def.key] === undefined ? "" : String(values[def.key])}
                onChange={(e) =>
                  set(def.key, e.target.value === "" ? undefined : Number(e.target.value))
                }
              />
            )}
            {def.type === "select" && (
              <Select
                value={(values[def.key] as string) ?? ""}
                onValueChange={(v) => set(def.key, v ?? undefined)}
              >
                <SelectTrigger id={id}>
                  <SelectValue placeholder="Select…" />
                </SelectTrigger>
                <SelectContent>
                  {(def.options ?? []).map((o) => (
                    <SelectItem key={o} value={o}>{o}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {def.type === "boolean" && (
              <label className="flex items-center gap-2 pt-6 text-sm" htmlFor={id}>
                <Checkbox
                  id={id}
                  checked={values[def.key] === true}
                  onCheckedChange={(v) => set(def.key, v === true)}
                />
                {def.label}
              </label>
            )}
            {errors?.map((msg) => (
              <p key={msg} role="alert" className="text-xs text-destructive">{msg}</p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
