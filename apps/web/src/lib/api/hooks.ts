"use client";

/**
 * TanStack Query hooks — the real-time transport for v1 (D-24).
 *
 * D-24 chose POLLING over WebSockets and deferred SSE to M3, and the reasoning is
 * worth keeping next to the code: our flow is strictly server→client (live call tiles,
 * lead toasts), polling meets the 2-minute post-call SLO with zero new infrastructure,
 * and SSE (plain HTTP, no proxy changes) is the planned upgrade — not WebSockets,
 * which only pay off with client→server streaming we do not have.
 *
 * Intervals below are therefore a product decision, not a default: fast enough that a
 * lead appears within the SLO, slow enough that an idle dashboard is not a load
 * generator. Refetch-on-focus does the rest — a user coming back to the tab is the
 * moment staleness actually matters.
 */

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { components } from "./schema";

import {
  apiRequest,
  type CallDetail,
  type CallLeadResult,
  type CallSummary,
  type Dashboard,
  type Lead,
  type LeadList,
  type LeadStatus,
  type Me,
  type Session,
} from "./client";

/** The post-call SLO is "lead visible within 2 minutes"; 20s leaves plenty of room. */
const LIVE_INTERVAL_MS = 20_000;
const SLOW_INTERVAL_MS = 60_000;

export const queryKeys = {
  me: (org: string) => ["me", org] as const,
  dashboard: (org: string) => ["dashboard", org] as const,
  calls: (org: string, filters: Record<string, unknown>) => ["calls", org, filters] as const,
  call: (org: string, id: string) => ["call", org, id] as const,
  leads: (org: string, filters: Record<string, unknown>) => ["leads", org, filters] as const,
};

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function useMe(session: Session): UseQueryResult<Me> {
  return useQuery({
    queryKey: queryKeys.me(session.orgSlug),
    queryFn: () => apiRequest<Me>(session, "/v1/me"),
    staleTime: 5 * 60_000,
  });
}

export function useDashboard(session: Session): UseQueryResult<Dashboard> {
  return useQuery({
    queryKey: queryKeys.dashboard(session.orgSlug),
    queryFn: () => apiRequest<Dashboard>(session, "/v1/dashboard"),
    refetchInterval: LIVE_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useCalls(
  session: Session,
  filters: { status?: string; limit?: number } = {},
): UseQueryResult<CallSummary[]> {
  return useQuery({
    queryKey: queryKeys.calls(session.orgSlug, filters),
    queryFn: () =>
      apiRequest<CallSummary[]>(session, `/v1/calls${query({ ...filters, limit: filters.limit ?? 50 })}`),
    refetchInterval: LIVE_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useCall(session: Session, callId: string): UseQueryResult<CallDetail> {
  return useQuery({
    queryKey: queryKeys.call(session.orgSlug, callId),
    queryFn: () => apiRequest<CallDetail>(session, `/v1/calls/${callId}`),
    // A call detail page opened while the pipeline is still running fills in as the
    // extraction lands; once it has, there is nothing left to poll for.
    refetchInterval: (q) => (q.state.data?.summary ? false : SLOW_INTERVAL_MS),
  });
}

export function useLeads(
  session: Session,
  filters: { status?: string; search?: string; limit?: number; offset?: number } = {},
): UseQueryResult<LeadList> {
  return useQuery({
    queryKey: queryKeys.leads(session.orgSlug, filters),
    queryFn: () => apiRequest<LeadList>(session, `/v1/leads${query(filters)}`),
    refetchInterval: SLOW_INTERVAL_MS,
    refetchOnWindowFocus: true,
    // Changing a filter chip or the search box is a re-filter, not a navigation:
    // keeping the previous rows on screen beats blanking the table to a skeleton
    // (and, worse, flashing "No leads yet") on every change of the query key.
    placeholderData: keepPreviousData,
  });
}

/**
 * CSV export — the same `leads:read` endpoint the table uses, fetched WITH the
 * session headers.
 *
 * It cannot be a plain `<a href>`: the API authenticates every request from the
 * Authorization and X-Org-Slug headers, which a browser navigation does not carry,
 * so a link answers with a 401 problem+json instead of a file. Fetching it here and
 * handing the browser a blob keeps the download while letting a refusal render
 * through ProblemNotice like every other error.
 */
export function useExportLeads(session: Session) {
  return useMutation({
    mutationFn: () => apiRequest<string>(session, "/v1/leads/export.csv"),
    onSuccess: (csv) => {
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
      // In the document and revoked a tick later: a detached anchor is a no-op in
      // some browsers, and revoking synchronously can cancel the save.
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  });
}

export function useUpdateLeadStatus(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, status }: { leadId: string; status: LeadStatus }) =>
      apiRequest<Lead>(session, `/v1/leads/${leadId}`, { method: "PATCH", body: { status } }),
    onSuccess: () => {
      // Invalidate rather than patch the cache: the server may also have moved the
      // lead (a hot-lead rule fires on the pipeline side), and the list is cheap.
      void client.invalidateQueries({ queryKey: ["leads", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["dashboard", session.orgSlug] });
    },
  });
}

export function useCallLead(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      leadId,
      agentId,
      contextNote,
    }: {
      leadId: string;
      agentId: string;
      contextNote?: string;
    }) =>
      apiRequest<CallLeadResult>(session, `/v1/leads/${leadId}/call`, {
        method: "POST",
        body: { agent_id: agentId, context_note: contextNote },
        // A double-click must not ring a customer twice. The key is per attempt, and
        // React Query's retry would otherwise reuse the same mutation function.
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}

/**
 * D-21 M2: follow up a call that ended without a resolution.
 *
 * Eligibility is a QUERY, not a post-click surprise — the call detail screen renders
 * the button disabled with the reason beside it, the same doctrine the campaign
 * launch check follows. The server re-runs both the eligibility rules and the
 * compliance gate on POST; this is a preview of that answer, never a substitute.
 */
export function useCallbackEligibility(session: Session, callId: string) {
  return useQuery({
    queryKey: ["callback-check", callId],
    queryFn: () =>
      apiRequest<components["schemas"]["CallbackEligibilityOut"]>(
        session,
        `/v1/calls/${callId}/callback`,
      ),
    enabled: Boolean(callId),
  });
}

export function useCallBack(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<components["schemas"]["CallbackOut"]>(session, `/v1/calls/${callId}/callback`, {
        method: "POST",
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["callback-check", callId] });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}

/** Usage + spend for the current billing month (IST). `billing:read`, owners only. */
export interface UsagePanel {
  month: string;
  minutes_used: string;
  calls: number;
  included_minutes: number;
  overage_minutes: string;
  overage_cost_inr: string;
  monthly_fee_inr: string | null;
  cap_minutes: number | null;
  capped: boolean;
  spend_used_inr: string;
  minutes_left: number | null;
  plan_tier: string;
  credit_balance_inr: string | null;
}

export function useUsage(session: Session): UseQueryResult<UsagePanel> {
  return useQuery({
    queryKey: ["usage", session.orgSlug],
    queryFn: () => apiRequest<UsagePanel>(session, "/v1/usage"),
    // Metering lands with the post-call pipeline, not live during a call.
    staleTime: 60_000,
  });
}
