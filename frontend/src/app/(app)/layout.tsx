"use client";

import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import { AppShell } from "@/components/app-shell";
import { AuthProvider } from "@/lib/auth-context";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <Providers>
      <AuthProvider>
        <AppShell>{children}</AppShell>
      </AuthProvider>
    </Providers>
  );
}
