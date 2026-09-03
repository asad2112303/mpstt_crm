"use client";

import { createClient, supabaseConfigured } from "@/lib/supabase/client";

/**
 * Normalizes the configured API origin.
 *
 * Hosting dashboards are often given a bare hostname ("api.example.com"), which
 * makes `new URL()` throw *before* any request is sent — the app then fails with
 * no network activity and nothing in the console. Assume HTTPS for a bare host,
 * and tolerate stray whitespace or a trailing slash.
 */
export function normalizeApiBase(raw: string | undefined): string {
  const value = (raw ?? "").trim().replace(/\/+$/, "");
  if (!value) return "http://localhost:8000";
  if (/^https?:\/\//i.test(value)) return value;
  return `https://${value}`;
}

export const API_BASE = normalizeApiBase(process.env.NEXT_PUBLIC_API_BASE_URL);

export interface ApiMeta {
  request_id: string;
  page?: number;
  page_size?: number;
  total?: number;
}

export interface ApiEnvelope<T> {
  data: T;
  meta: ApiMeta;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  field_errors: Record<string, string[]>;
  request_id: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: Record<string, string[]>;
  readonly requestId: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.fieldErrors = body.field_errors ?? {};
    this.requestId = body.request_id ?? "";
  }
}

async function accessToken(): Promise<string | null> {
  if (!supabaseConfigured()) return null;
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** For high-impact POST actions (confirm, issue, allocate, convert…). */
  idempotencyKey?: string;
  searchParams?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

export async function api<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiEnvelope<T>> {
  const token = await accessToken();
  const url = new URL(`${API_BASE}${path}`);
  for (const [key, value] of Object.entries(options.searchParams ?? {})) {
    if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  const resp = await fetch(url.toString(), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (resp.status === 204) {
    return { data: undefined as T, meta: { request_id: "" } };
  }

  const json = await resp.json().catch(() => null);
  if (!resp.ok) {
    const errBody: ApiErrorBody = json?.error ?? {
      code: "NETWORK_ERROR",
      message: "The server returned an unexpected response.",
      field_errors: {},
      request_id: "",
    };
    throw new ApiError(resp.status, errBody);
  }
  return json as ApiEnvelope<T>;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
