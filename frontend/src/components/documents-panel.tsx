"use client";

import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";
import { formatKarachi } from "@/lib/types/crm";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface DocumentRow {
  id: string;
  entity_type: string;
  entity_id: string;
  document_type: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
}

async function authHeader(): Promise<Record<string, string>> {
  if (!supabaseConfigured()) return {};
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

/** Upload + list + download for any entity's private documents. */
export function DocumentsPanel({
  entityType,
  entityId,
  documentType = "attachment",
  organizationId,
  title = "Documents",
}: {
  entityType: string;
  entityId: string;
  documentType?: string;
  organizationId?: string;
  title?: string;
}) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["documents", entityType, entityId],
    queryFn: async () =>
      (
        await api<DocumentRow[]>("/api/v1/documents", {
          searchParams: { entity_type: entityType, entity_id: entityId },
        })
      ).data,
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      form.append("entity_type", entityType);
      form.append("entity_id", entityId);
      form.append("document_type", documentType);
      if (organizationId) form.append("organization_id", organizationId);
      const resp = await fetch(`${API_BASE}/api/v1/documents/upload`, {
        method: "POST",
        headers: await authHeader(),
        body: form,
      });
      const json = await resp.json();
      if (!resp.ok) {
        throw new ApiError(resp.status, json.error);
      }
      return json;
    },
    onSuccess: () => {
      toast.success("File uploaded");
      queryClient.invalidateQueries({ queryKey: ["documents", entityType, entityId] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Upload failed"),
  });

  async function download(doc: DocumentRow) {
    const resp = await fetch(`${API_BASE}/api/v1/documents/${doc.id}/download`, {
      headers: await authHeader(),
    });
    if (!resp.ok) {
      toast.error("Download failed");
      return;
    }
    const contentType = resp.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      // Supabase backend: short-lived signed URL.
      const json = await resp.json();
      window.open(json.data.url, "_blank", "noopener");
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.original_filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-medium">
          <Paperclip className="h-4 w-4 text-muted-foreground" aria-hidden />
          {title}
        </h3>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".pdf,.png,.jpg,.jpeg,.webp,.xlsx,.csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
        <Button variant="outline" size="sm" disabled={upload.isPending}
          onClick={() => fileInput.current?.click()}>
          <FileUp className="mr-1 h-3.5 w-3.5" aria-hidden />
          {upload.isPending ? "Uploading…" : "Upload"}
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : !data?.length ? (
        <p className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
          No files attached. Allowed: PDF, PNG, JPG, WEBP, XLSX, CSV (max 20 MB).
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border bg-card">
          {data.map((doc) => (
            <li key={doc.id} className="flex items-center justify-between gap-2 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{doc.original_filename}</p>
                <p className="text-xs text-muted-foreground">
                  {(doc.size_bytes / 1024).toFixed(0)} KB · {formatKarachi(doc.created_at)}
                </p>
              </div>
              <Button variant="ghost" size="icon-sm" aria-label={`Download ${doc.original_filename}`}
                onClick={() => void download(doc)}>
                <Download className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
