"use client";

import type { ReactNode } from "react";
import { ShieldAlert } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

/** Client-side gate for admin pages. The API enforces the real authorization. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const { me, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (me?.role !== "admin") {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-12 text-center">
        <ShieldAlert className="h-8 w-8 text-warning" aria-hidden />
        <p className="font-medium">Administrator access required</p>
        <p className="text-sm text-muted-foreground">
          You do not have permission to view this page.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
