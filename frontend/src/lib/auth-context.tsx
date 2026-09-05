"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { createClient, supabaseConfigured } from "@/lib/supabase/client";

export interface Me {
  id: string;
  full_name: string;
  email: string | null;
  role: "admin" | "user";
  aal: "aal1" | "aal2";
}

interface AuthContextValue {
  me: Me | null;
  isLoading: boolean;
  error: ApiError | null;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => (await api<Me>("/api/v1/auth/me")).data,
    retry: false,
    staleTime: 5 * 60_000,
  });

  async function signOut() {
    // Never let a failed provider call trap the user in the app: an expired or
    // already-revoked session makes a global sign-out return 403, and the old
    // code then threw before navigating. Clear locally, always continue.
    try {
      if (supabaseConfigured()) {
        await createClient().auth.signOut({ scope: "local" });
      }
    } catch {
      // Session was already invalid — the local cookies are cleared regardless.
    }
    queryClient.clear(); // drop cached CRM data so the next user starts clean
    // Full page load, so middleware re-evaluates with the cleared cookies
    // instead of a client-side transition reusing cached state.
    window.location.assign("/login");
  }

  return (
    <AuthContext.Provider
      value={{
        me: data ?? null,
        isLoading,
        error: error instanceof ApiError ? error : null,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
