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
    // Clear the browser-held session first (best effort), then hand over to the
    // server route, which deletes the cookie the middleware actually reads and
    // redirects. Doing it server-side is what makes sign-out reliable: a
    // surviving cookie would bounce /login straight back to /dashboard.
    try {
      if (supabaseConfigured()) {
        // Best effort: revoke the refresh token server-side. This fails with
        // 403 on an already-expired session, which must not block signing out.
        await createClient().auth.signOut({ scope: "global" });
      }
    } catch {
      // Session already invalid — continue; the server clears it regardless.
    }
    queryClient.clear(); // drop cached CRM data so the next user starts clean
    window.location.assign("/auth/signout");
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
