"use client";

import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Card, CardContent } from "@/components/ui/card";

/** Stub — the full company-settings editor ships with module M11. */
export default function AdminSettingsPage() {
  return (
    <RequireAdmin>
      <main className="space-y-6 p-6">
        <PageHeader
          title="Company settings"
          description="Identity, bank details, numbering, and document defaults."
        />
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Company settings become editable when the Documents &amp; Settings
            module (M11) is enabled.
          </CardContent>
        </Card>
      </main>
    </RequireAdmin>
  );
}
