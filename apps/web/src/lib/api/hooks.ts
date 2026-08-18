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
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { components } from "./schema";

import { aiQuotaKey } from "./aiQuota";
import {
  apiRequest,
  type CallDetail,
  type CallLeadResult,
  type CallSummary,
  type Dashboard,
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

/** What a gated control needs to know: whether to enable itself, and what to say. */
export interface WriteAccess {
  /** Enable the control only when this is true. */
  allowed: boolean;
  /**
   * Why not, in the client's words — rendered BESIDE the disabled control. Null while
   * we do not yet know (the `/v1/me` request is still in flight), so a control never
   * flashes an explanation it is about to retract.
   */
  reason: string | null;
  /**
   * `allowed: false` because we could not FIND OUT, rather than because the server said
   * no. Both cases close the control — that is the fail-closed default and it does not
   * change — but they are different answers, and a screen that hides a control on a
   * known refusal must still say something on an unknown one (BUILD-LOG §52).
   *
   * The distinction was previously unavailable to callers, and the integrations screen
   * paid for it: it renders no payload column for a reader who genuinely lacks
   * `calls:read_raw`, which is correct and needs no sentence, and had no way to tell
   * that case apart from a dead `/v1/me` — where the same silence implies a refusal we
   * never received. Read this, not `reason !== null`: a known refusal has a reason too.
   */
  unknown: boolean;
}

/**
 * May this session use a control that WRITES? — the D-22 read-only sweep, in one place.
 *
 * Two facts decide it, both from the server's own answer to `/v1/me` and never from a
 * hardcoded role list: the permission the endpoint requires, and `impersonating`.
 *
 * The second is the one that changed. "View as client" now genuinely lands an operator
 * on client screens, and `requires()` refuses every permission in `MUTATING_PERMISSIONS`
 * for an impersonating principal (core/auth.py). So each mutating control became
 * reachable-but-refused: the operator clicks, waits, and gets a 403 that reads like a
 * fault. Disabled WITH the reason turns that into an answer given before the click —
 * the same doctrine the campaign launch-check already follows for its blockers.
 *
 * Note `/v1/me` returns the ROLE's full permission set, impersonation included — it does
 * not subtract the mutating ones — which is why `impersonating` has to be read as well
 * as `permissions`. This is a preview of the server's answer, never a substitute for it:
 * the endpoints still refuse, and every screen keeps its ProblemNotice as the backstop.
 */
export function useWriteAccess(session: Session, permission: string, action: string): WriteAccess {
  const me = useMe(session);

  if (me.error) {
    // A permanently dead control with no explanation is the worst of both worlds; say
    // that we could not find out rather than implying a refusal we did not receive.
    return {
      allowed: false,
      reason: `We could not check whether you can ${action}. Reload the page to try again.`,
      unknown: true,
    };
  }
  // Still in flight: also unknown, and deliberately WITHOUT a sentence — a control that
  // flashes an explanation and then retracts it teaches the reader to ignore the next one.
  if (!me.data) return { allowed: false, reason: null, unknown: true };
  if (me.data.impersonating) {
    return {
      allowed: false,
      reason: `You are viewing this account read-only, so you cannot ${action} from here. Do it from the admin console instead.`,
      unknown: false,
    };
  }
  if (!me.data.permissions.includes(permission)) {
    return { allowed: false, reason: `Only an account owner can ${action}.`, unknown: false };
  }
  return { allowed: true, reason: null, unknown: false };
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

/**
 * `useExportLeads` MOVED to `lib/api/leads.ts` and now takes the same `LeadLens` the
 * list takes — the column chooser and the facet filters have to reach the file, and a
 * hook whose type could not name them was the reason the old one sent `agent_id` alone
 * while the screen was filtered to "hot". Deleted here rather than deprecated: two ways
 * to download one file is how the two get different filters again.
 */

/**
 * `useUpdateLeadStatus` MOVED to `lib/api/leads.ts` and became `useEditLead`, with both
 * callers moved in the same change. It and `useAssignLead` were two hooks issuing the
 * same `PATCH /v1/leads/{id}` with two invalidation sets and two error channels — one
 * route, two ways — and a row can only surface one failure at a time, so the two
 * competed for the same pixel. Deleted here rather than deprecated, for the reason the
 * note above gives about the export.
 */

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
    // Keyed by org slug, like every other client-realm query. The id is a uuid_v7 so two
    // tenants cannot collide TODAY — but that makes the isolation a property of the id
    // generator rather than of the cache, in a `QueryClient` that genuinely holds more
    // than one tenant's data at a time: a D-22 operator following "View as client" into
    // tenant A, back out, and into tenant B does all of it inside one client instance
    // (`app/providers.tsx` creates it once per shell mount). `tests/queryKeys.test.ts`
    // enforces this across the whole client realm rather than trusting the next author.
    queryKey: ["callback-check", session.orgSlug, callId],
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
      void client.invalidateQueries({ queryKey: ["callback-check", session.orgSlug, callId] });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}

/**
 * Ask the assistant to re-summarise one call (D-127 — the G-2/G-5/G-6 surface).
 *
 * **The `Idempotency-Key` is minted here, once per hook instance, and reused on retry.**
 * The server REQUIRES one (`crm/routes.assist_call`) because a repeat of this request is
 * a second silent payment to Google — and the value has to be stable across a retry of
 * the SAME attempt while being fresh for a new one, which is exactly what a value bound
 * to a mutation's lifetime is not. So it is minted per SUBMISSION: `mutationFn` takes no
 * argument and generates the key at call time, so the two clicks a person makes a minute
 * apart are two attempts and the framework's own retry of one click is one.
 *
 * `retry: false` is the app-wide mutation default (`app/providers.tsx`) and is right
 * here for its own reason: the failures worth surfacing are refusals with a remediation
 * (`ai_quota_exceeded` opens the wallet dialog), and retrying one three times shows the
 * person the same refusal three times.
 *
 * On success the AI allowance is invalidated rather than patched: the assist moved
 * `used_inr` by an amount only the server knows, and a browser that guessed it would be
 * dividing rupees, which is what `lib/api/aiQuota.ts` exists not to do.
 */
export function useCallAssist(session: Session, callId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<components["schemas"]["CallAssistOut"]>(session, `/v1/calls/${callId}/assist`, {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: aiQuotaKey(session.orgSlug) });
    },
  });
}

/**
 * Usage + spend for the current billing month (IST). `billing:read`, owners only.
 *
 * Aliased from the generated schema, not hand-written: the local interface it replaces
 * had drifted, omitting `overage_rate_inr` — so the Usage screen could show what the
 * extra minutes cost but never what a minute costs, and nobody could tell.
 *
 * Every money field is an exact decimal STRING and must stay one all the way to the
 * screen (hard rule 7's frontend shadow); `Number()` on INR is how ₹10,159.00 becomes
 * ₹10,158.999999999998.
 */
export type UsagePanel = components["schemas"]["UsagePanelOut"];

export function useUsage(session: Session): UseQueryResult<UsagePanel> {
  return useQuery({
    queryKey: ["usage", session.orgSlug],
    queryFn: () => apiRequest<UsagePanel>(session, "/v1/usage"),
    // Metering lands with the post-call pipeline, not live during a call.
    staleTime: 60_000,
  });
}
