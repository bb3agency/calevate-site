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
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useRef } from "react";

import type { components } from "./schema";

import { unscopedClientSession } from "@/lib/authn/realmSessions";

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
  calls: (org: string, filters: Record<string, unknown>) =>
    ["calls", org, filters] as const,
  call: (org: string, id: string) => ["call", org, id] as const,
  leads: (org: string, filters: Record<string, unknown>) =>
    ["leads", org, filters] as const,
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

/** The key both slug-less callers share — exported so a test can seed or clear it. */
export const UNSCOPED_ME_KEY = ["me", "unscoped"] as const;

/**
 * `/v1/me` for a page that is INSIDE a session and OUTSIDE an account — the two screens
 * that have a cookie and no slug.
 *
 * `core/auth._load_client_principal` answers without `X-Org-Slug` when the caller belongs
 * to exactly one account, which is what `unscopedClientSession()` exists for; somebody in
 * more than one gets `org_required` and every caller here renders that refusal rather than
 * choosing an account for them.
 *
 * ITS OWN KEY, never `queryKeys.me(slug)`: that one is keyed by the slug these callers do
 * not have, and answering it under `["me", ""]` would seed the console's cache from a read
 * that named no account (`tests/queryKeys.test.ts` is the guard for that class).
 *
 * A hook rather than a second copy of the `useQuery` block: `/c` (the console junction)
 * and `/auth/account` both ask the same question of the same endpoint with the same
 * credential, and two spellings of one read is where the failure handling drifts.
 */
export function useUnscopedMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: UNSCOPED_ME_KEY,
    queryFn: () => apiRequest<Me>(unscopedClientSession(), "/v1/me"),
    // `retry: false`: both callers show the refusal, and a person staring at a spinner
    // through three backoffs cannot tell a slow answer from a dead one.
    retry: false,
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
 * May this session use a control that WRITES? — the permission preview, in one place.
 *
 * ONE fact decides it, and it comes from the server: is the permission in `/v1/me`'s
 * `permissions`. That list is the EFFECTIVE set, not the role's — the API subtracts what a
 * view-as session may not exercise and adds what an owner's curation switch grants — so
 * this hook previews the server's ruling rather than re-deriving it.
 *
 * ⚠ **IT USED TO READ `impersonating` AS A SECOND FACT AND REFUSE EVERYTHING ON IT (D-22).
 * D-587 DELETED THAT BRANCH.** An operator in "view as client" may now fix the account they
 * are looking at, and every change is recorded against them (`audit_log.via_grant_id`), so
 * a browser-side rule saying "no" would have disabled the controls the reversal exists to
 * enable — and would have done it silently, since nothing in the API would have refused.
 * `impersonating` survives here for one job only: choosing which SENTENCE explains an
 * absent permission, because "only an account owner can" is false when the reader is an
 * operator rather than a member of the account.
 *
 * A preview, never a substitute: the endpoints still refuse, and every screen keeps its
 * ProblemNotice as the backstop.
 */
export function useWriteAccess(
  session: Session,
  permission: string,
  action: string,
): WriteAccess {
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
  if (!me.data.permissions.includes(permission)) {
    // D-587 REMOVED THE BLANKET `if (me.data.impersonating) refuse` THAT USED TO STAND
    // ABOVE THIS, and removing it is the point rather than a side effect: it was a copy of
    // a server policy ("view-as is read-only") living in the browser, and the moment the
    // server's answer became "these six mutations yes, those six no" the copy would have
    // been wrong for every control an operator is now meant to use.
    //
    // `/v1/me` already reports the EFFECTIVE permission set — it filters out what
    // `rbac.VIEW_AS_MUTATIONS` withholds from a view-as session, exactly as it already
    // added `kb:write` for a staff member whose owner switched curation on — so the list
    // below IS the server's ruling and this file needs no view-as rule of its own. What
    // remains is the WORDING: the same absence means two different things, and "only an
    // account owner can" is the wrong sentence to hand an operator who is not one.
    return {
      allowed: false,
      reason: me.data.impersonating
        ? `This stays with the client, so you cannot ${action} from a view-as session. Do it from the operator console, or ask the account to do it.`
        : `Only an account owner can ${action}.`,
      unknown: false,
    };
  }
  return { allowed: true, reason: null, unknown: false };
}

/**
 * Whether this session may perform one NAMED ACT, as distinct from holding a permission.
 *
 * **THE HALF `useWriteAccess` CANNOT ANSWER, AND THE DEFECT THAT PROVED IT.** D-587 made
 * view-as writable and filtered withheld PERMISSIONS out of `/v1/me`, so the console could
 * stop carrying a copy of the ruling. But six of the refusals are not permission-shaped:
 * `org:manage` and `kb:write` are both writable in a view-as session, and the server then
 * refuses `org.membership` and `kb.self_approve` INSIDE them (`rbac.VIEW_AS_WITHHELD_ACTS`,
 * enforced by `assert_view_as_may`). `useWriteAccess` asks only "is the permission in the
 * list", so it rendered a working Invite button and a working Submit for review that the
 * API then refused — a screen offering a control the server will not honour.
 *
 * So a control guarded by a named act asks BOTH: the permission first (a staff member
 * without `org:manage` is refused for the ordinary reason, in the ordinary words), then the
 * act. `withheld_acts` comes from the server whole, for `useWriteAccess`'s reason — the
 * ruling lives in one place and the browser asks it.
 *
 * `reason` is the operator's sentence, not the client's: these acts are withheld from
 * view-as and from nobody else, so a client session can never reach this branch.
 */
export function useActAccess(
  session: Session,
  permission: string,
  act: string,
  action: string,
): WriteAccess {
  const me = useMe(session);
  const write = useWriteAccess(session, permission, action);

  if (!write.allowed) return write;
  if (me.data?.withheld_acts?.includes(act)) {
    return {
      allowed: false,
      reason: `This stays with the client, so you cannot ${action} from a view-as session. Do it from the operator console, or ask the account to do it.`,
      unknown: false,
    };
  }
  return write;
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
      apiRequest<CallSummary[]>(
        session,
        `/v1/calls${query({ ...filters, limit: filters.limit ?? 50 })}`,
      ),
    refetchInterval: LIVE_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
}

/**
 * The call LOG — infinite, paged by offset, distinct from `useCalls` on purpose.
 *
 * `useCalls` serves the dashboard's six-row peek, where one bounded page is the whole
 * point. The log screen used to share it, which is how "yesterday's call" became
 * unreachable: a busy day pushes yesterday past row 100 and there was no control that
 * reached it (ux-audit CL2, a blocker). `/v1/calls` has taken `offset` since M1; this
 * hook is the missing client half. The endpoint returns a bare list (no total
 * envelope), so the end of the log is detected the only honest way available: a page
 * shorter than the page size.
 */
export function useCallsLog(
  session: Session,
  filters: { status?: string; pageSize: number },
): UseInfiniteQueryResult<InfiniteData<CallSummary[]>> {
  const { status, pageSize } = filters;
  return useInfiniteQuery({
    queryKey: ["calls-log", session.orgSlug, { status, pageSize }],
    queryFn: ({ pageParam }) =>
      apiRequest<CallSummary[]>(
        session,
        `/v1/calls${query({ status, limit: pageSize, offset: pageParam || undefined })}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === pageSize
        ? allPages.reduce((n, page) => n + page.length, 0)
        : undefined,
    // Polling refetches every loaded page (TanStack refetches an infinite query whole),
    // so the live cadence is kept but the reader's place is too — rows are deduped by id
    // at the render because a new call landing shifts rows across page boundaries.
    refetchInterval: LIVE_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useCall(
  session: Session,
  callId: string,
): UseQueryResult<CallDetail> {
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
      apiRequest<components["schemas"]["CallbackOut"]>(
        session,
        `/v1/calls/${callId}/callback`,
        {
          method: "POST",
        },
      ),
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: ["callback-check", session.orgSlug, callId],
      });
      void client.invalidateQueries({ queryKey: ["calls", session.orgSlug] });
    },
  });
}

/**
 * Ask the assistant to re-summarise one call (D-127 — the G-2/G-5/G-6 surface).
 *
 * **ONE `Idempotency-Key` PER LOGICAL ATTEMPT, HELD ACROSS THAT ATTEMPT'S RETRIES.** The
 * server REQUIRES the header (`crm/routes.assist_call`) because a repeat of this request
 * is a second silent payment to the assistant model — Azure OpenAI since D-410, Gemini
 * before it, and the vendor is not the point: the point is that the money leaves before
 * the answer comes back. The key only buys anything if it is REUSED; a key minted per
 * `mutate()` call is a header that satisfies the server's validation and protects nobody,
 * which is what this hook used to send.
 *
 * The event it now prevents is a LOST RESPONSE. `AssistCard`'s `ProblemNotice` offers
 * "Try again" after a failure, and a failure whose cause was a 504 or a dropped
 * connection on a run the server COMPLETED is one the client has already been charged
 * for. With the key reused, that retry is answered `replay` from the stored response
 * (`claim.state == "replay"`) instead of paying a second time.
 *
 * ## The lifecycle, which is the whole of the correctness
 *
 * The key lives in a ref beside the call it belongs to, and each of the three transitions
 * is a rule the server can see the other side of:
 *
 * - **A retry of a failed attempt keeps it.** That is the case above, and it is only safe
 *   because the server now RELEASES a claim it took on a refusal raised before the
 *   provider was paid: `assist_call`'s `try` opens at `load_assist_source` and its
 *   `except` calls `fail_idempotency`, and `claim_idempotency` re-claims a `failed` record
 *   as `fresh`. Until that arm covered the two pre-payment refusals, reusing a key traded
 *   a rare double charge for a constant `idempotent_request_in_flight` on ordinary paths —
 *   which is why this hook deliberately did NOT reuse keys before, and why the change had
 *   to wait for the server rather than being an oversight.
 * - **Success clears it**, because the next press is a person asking for a SECOND reading
 *   and expecting to pay for one. Keeping it would answer them from the stored response
 *   forever — a button that silently stops working, which is worse than the charge.
 * - **`reset()` clears it**, which is the same rule seen from the other side: the card
 *   resets after the wallet top-up (`onBought`), and what follows a purchase is a new
 *   attempt, not a retry of the one that was refused.
 *
 * The call id is held WITH the key rather than assumed, because the two must not come
 * apart: the server hashes `{"call_id": ...}` into `request_hash`, so the same key on a
 * different call is refused outright as `idempotency_key_reused`. A hook re-rendered with
 * a new `callId` mints a new key from that fact rather than from an effect that might not
 * have run yet.
 *
 * `retry: false` remains the app-wide mutation default (`app/providers.tsx`) and is now
 * held for its own reason rather than for this one. TanStack retries a mutation by
 * re-invoking `mutationFn`, so a framework retry would once have minted a new key and
 * paid again; with the ref it would reuse the key and be safe. It stays off because the
 * failures worth surfacing here are refusals with a remediation (`ai_quota_exceeded`
 * opens the wallet dialog), and retrying one three times shows the person the same
 * refusal three times.
 *
 * On success the AI allowance is invalidated rather than patched: the assist moved
 * `used_inr` by an amount only the server knows, and a browser that guessed it would be
 * dividing rupees, which is what `lib/api/aiQuota.ts` exists not to do.
 */
export function useCallAssist(session: Session, callId: string) {
  const client = useQueryClient();
  // A ref rather than state: nothing on screen reads the key, and re-rendering the card
  // to store it would be a render caused by a header.
  const attempt = useRef<{ callId: string; key: string } | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const held = attempt.current;
      const key =
        held !== null && held.callId === callId
          ? held.key
          : crypto.randomUUID();
      attempt.current = { callId, key };
      return apiRequest<components["schemas"]["CallAssistOut"]>(
        session,
        `/v1/calls/${callId}/assist`,
        { method: "POST", idempotencyKey: key },
      );
    },
    onSuccess: () => {
      // BEFORE the invalidation, and unconditionally: this attempt is over, and the next
      // press must be able to buy a second reading.
      attempt.current = null;
      void client.invalidateQueries({ queryKey: aiQuotaKey(session.orgSlug) });
    },
  });

  // `reset()` is WRAPPED rather than re-exported, so a caller cannot clear the mutation's
  // error and leave the key that belonged to it behind. Spreading the result is what
  // `useMutation` itself returns (`{ ...result, mutate, mutateAsync }`), so nothing here
  // is reaching past the library's own shape.
  return {
    ...mutation,
    reset: () => {
      attempt.current = null;
      mutation.reset();
    },
  };
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
