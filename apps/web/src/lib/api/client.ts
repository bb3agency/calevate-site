/**
 * The ONE way the frontend talks to the API.
 *
 * CLAUDE.md conventions: "typed client generated from OpenAPI; TanStack Query; no
 * ad-hoc fetch". This module is the seam that makes the second half enforceable — it
 * is the only place `fetch` appears, so auth headers, the org header and problem+json
 * handling cannot be forgotten one screen at a time.
 *
 * Errors are RFC-9457 (BACKEND-PATTERNS §3). `ApiProblem` preserves `kind`,
 * `retryable`, `remediation` and `fields`, so a screen can decide what to render —
 * a field-level message, a retry button, or an explanation — instead of showing a
 * generic "something went wrong" for all of them.
 */

import type { components } from "./schema";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiProblem extends Error {
  readonly status: number;
  readonly kind: string;
  readonly code: string;
  readonly retryable: boolean;
  readonly remediation?: string;
  readonly fields?: { field: string; rule: string; message: string }[];
  readonly traceId?: string;

  constructor(status: number, body: Record<string, unknown>) {
    super(String(body.detail ?? body.title ?? "Request failed"));
    this.name = "ApiProblem";
    this.status = status;
    this.kind = String(body.kind ?? "internal");
    // `type` is a URL whose last segment is the stable machine code.
    this.code = String(body.type ?? "").split("/").pop() ?? "unknown";
    this.retryable = Boolean(body.retryable);
    this.remediation = body.remediation as string | undefined;
    this.fields = body.fields as ApiProblem["fields"];
    this.traceId = body.trace_id as string | undefined;
  }
}

/**
 * Session context the API needs on every call.
 *
 * `token` is a Clerk session token in staging/prod. Locally, when Clerk is not
 * configured, the API accepts `dev:<realm>:<clerk_user_id>` — see `core/auth.py`,
 * where that path requires BOTH `APP_ENV=local` AND an absent Clerk secret.
 */
export interface Session {
  token: string;
  orgSlug: string;
  /** Admin realm only (D-22): read-only "view as client". */
  impersonateOrg?: string;
}

export function devSession(orgSlug: string): Session {
  const user = process.env.NEXT_PUBLIC_DEV_USER ?? "user_local";
  return { token: `dev:client:${user}`, orgSlug };
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  /** Required by the API on any endpoint that can place a call or spend money. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  session: Session,
  path: string,
  { method = "GET", body, idempotencyKey, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${session.token}`,
    "X-Org-Slug": session.orgSlug,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  if (session.impersonateOrg) headers["X-Impersonate-Org"] = session.impersonateOrg;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let problem: Record<string, unknown> = {};
    try {
      problem = await response.json();
    } catch {
      problem = { detail: response.statusText };
    }
    throw new ApiProblem(response.status, problem);
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return (await response.text()) as T;
  return (await response.json()) as T;
}

/**
 * Response types, aliased from the GENERATED schema so they cannot drift from the API.
 * Regenerate with `pnpm gen:api` after any change to a response model; the openapi
 * freshness guardrail (ENGINEERING-PRACTICES §2) checks this file is current.
 */
type Schemas = components["schemas"];

export type Dashboard = Schemas["DashboardOut"];
export type CallSummary = Schemas["CallSummaryOut"];
export type CallDetail = Schemas["CallDetailOut"];
export type LeadList = Schemas["LeadListOut"];
export type Lead = Schemas["LeadOut"];
export type LeadColumn = Schemas["ExtractionField"];
export type Me = Schemas["MeOut"];
export type CallLeadResult = Schemas["CallLeadOut"];
export type AgentSummary = Schemas["AgentOut"];
export type LeadStatus = Lead["status"];
