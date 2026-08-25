"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
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
  const router = useRouter();
  const { data, isLoading, error } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => (await api<Me>("/api/v1/auth/me")).data,
    retry: false,
    staleTime: 5 * 60_000,
  });

  async function signOut() {
    if (supabaseConfigured()) {
      await createClient().auth.signOut();
    }
    router.replace("/login");
    router.refresh();
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
