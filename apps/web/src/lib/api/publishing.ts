"use client";

/**
 * Two-speed publishing (SURFACES §2b) — the frontend half of `agents/publishing.py`.
 *
 * The API splits this feature across two realms on purpose, and the split is the
 * whole reason this module exists rather than a few hooks bolted onto `agents.ts`:
 *
 *   GET   /v1/agents/lanes                                  client realm, `agents:read`
 *   GET   /v1/agents/{agent_id}/pending                     client realm, `agents:read`
 *   POST  /v1/admin/tenants/{tid}/agents/{aid}/apply        ADMIN realm, `agents:write`
 *   POST  /v1/admin/tenants/{tid}/agents/{aid}/undo         ADMIN realm
 *   PATCH /v1/admin/tenants/{tid}/agents/{aid}/call-cap     ADMIN realm
 *
 * A client can SEE that a script is waiting; only an operator can apply it, because
 * only an operator can author it (`publishing_routes.py` states the argument at
 * length). So there is deliberately NO client-realm apply hook here — the same rule
 * `agents.ts` and `kb.ts` already follow: a button that could only ever 403 is worse
 * than no button, and the client screen says who does apply it instead.
 *
 * The admin console reads the two GETs through IMPERSONATION (`viewAsSession`) and
 * writes through its own admin session — the D-22 split `admin.ts::useTenantKbQueue`
 * established. Both paths share `publishingKeys`, keyed by org slug, so an Apply made
 * from the console invalidates the very cache entry the client screen reads.
 *
 * MONEY. `worst_case_call_cost_inr` is an exact NUMERIC that crosses the wire as a
 * STRING and stays one all the way to the screen (hard rule 7). It is `null` when the
 * plan quotes no rate, and null means "we cannot say" — never ₹0. Nothing in this
 * module or its callers coerces it with `Number()`.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { adminSession, viewAsSession } from "./admin";
import { apiRequest, type Session } from "./client";
import { promptHistoryKey } from "./prompts";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The lane table: which settings apply immediately, which wait for Apply. */
export type Lanes = Schemas["LanesOut"];
export type Lane = Schemas["LaneOut"];

/** What the unsaved-changes banner renders, in one read. */
export type PendingState = Schemas["PendingOut"];
export type PendingChange = Schemas["PendingChangeOut"];

export type ApplyIn = Schemas["ApplyIn"];
export type ApplyOut = Schemas["ApplyOut"];
export type UndoOut = Schemas["UndoOut"];
export type SetCallCapIn = Schemas["SetCallCapIn"];
export type CallCapOut = Schemas["CallCapOut"];

export const publishingKeys = {
  /** Static per deployment, but still org-keyed: one cache per session identity. */
  lanes: (org: string) => ["agent-lanes", org] as const,
  pending: (org: string, agentId: string) => ["agent-pending", org, agentId] as const,
};

/**
 * The lane table cannot change without a deploy — `LANES` is a Python tuple, not a
 * row — so it is cached hard. `Infinity` would survive a deploy in a long-lived tab;
 * an hour is the compromise the rest of this app's slow reads already use.
 */
const LANES_STALE_MS = 60 * 60_000;

/**
 * A staged script appears when an operator saves a version, which is a human action
 * measured in minutes. No polling (a client screen watching an agent that changes
 * twice a month is a load generator); refetch-on-focus does the useful half.
 */
const PENDING_STALE_MS = 30_000;

function lanesOptions(session: Session) {
  return {
    queryKey: publishingKeys.lanes(session.orgSlug),
    queryFn: () => apiRequest<Lanes>(session, "/v1/agents/lanes"),
    staleTime: LANES_STALE_MS,
  };
}

function pendingOptions(session: Session, agentId: string) {
  return {
    queryKey: publishingKeys.pending(session.orgSlug, agentId),
    queryFn: () => apiRequest<PendingState>(session, `/v1/agents/${agentId}/pending`),
    enabled: Boolean(agentId),
    staleTime: PENDING_STALE_MS,
  };
}

/* ------------------------------------------------------------------ client realm */

export function useLanes(session: Session): UseQueryResult<Lanes> {
  return useQuery(lanesOptions(session));
}

export function usePendingChanges(
  session: Session,
  agentId: string,
): UseQueryResult<PendingState> {
  return useQuery(pendingOptions(session, agentId));
}

/* ------------------------------------------------------------------- admin realm */

/**
 * The same two reads, from the console, through the impersonation session.
 *
 * They are separate exported hooks rather than "call the client hook with a different
 * session" so the realm choice is visible at the call site — but they share ONE
 * options builder each, so the URL, the key and the stale window cannot drift between
 * the screen a client sees and the screen an operator acts on.
 */
export function useTenantLanes(slug: string): UseQueryResult<Lanes> {
  return useQuery({ ...lanesOptions(viewAsSession(slug)), enabled: Boolean(slug) });
}

export function useTenantPending(slug: string, agentId: string): UseQueryResult<PendingState> {
  const options = pendingOptions(viewAsSession(slug), agentId);
  return useQuery({ ...options, enabled: Boolean(slug) && Boolean(agentId) });
}

interface AgentTarget {
  tenantId: string;
  agentId: string;
  /** Needed to invalidate the org-keyed read caches the two GETs populate. */
  slug: string;
}

/**
 * Invalidate everything an apply/undo/cap change can have moved, and WAIT for it.
 *
 * Returning the promise from `onSuccess` keeps the mutation pending until the refetch
 * lands, so the button stays busy instead of flicking back to "Apply" over a banner
 * still showing the change it just applied
 * (https://tanstack.com/query/v5/docs/framework/react/reference/useMutation —
 * "Returning a Promise on onSuccess makes sure the data is updated before the
 * mutation is entirely complete"). `prompts.ts` fires its invalidation with `void`
 * because a version list one paint late looks like nothing at all; here the stale
 * paint contradicts the button that caused it.
 */
function useAfterPublish({ tenantId, agentId, slug }: AgentTarget) {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: publishingKeys.pending(slug, agentId) }),
      client.invalidateQueries({ queryKey: promptHistoryKey(tenantId, agentId) }),
      // `published`/`status` on the agent roster can move when a publish reaches the
      // engine, and the client screen reads that list beside this banner.
      client.invalidateQueries({ queryKey: ["agents", slug] }),
      client.invalidateQueries({ queryKey: ["admin", "agents", slug] }),
    ]);
}

/**
 * The same refresh, for the mutation that CREATES the pending state.
 *
 * Saving a prompt version stages it (`prompts.py`: `system_prompt_id` is the draft
 * pointer), so the Apply banner is out of date the instant `useWritePrompt` succeeds
 * — and `prompts.ts` cannot invalidate it on its own, because the pending cache is
 * keyed by org SLUG (the client realm has no tenant id) and that module only knows
 * the tenant id. Rather than thread a slug through the prompt hooks for one caller,
 * the screen that has both composes them.
 */
export function usePublishingRefresh(target: AgentTarget): () => Promise<unknown> {
  return useAfterPublish(target);
}

function agentPath({ tenantId, agentId }: AgentTarget, action: string): string {
  return `/v1/admin/tenants/${tenantId}/agents/${agentId}/${action}`;
}

/**
 * "Apply to live calls".
 *
 * `expected_version` is the CAS token (BACKEND-PATTERNS §5) — the staged version the
 * operator actually looked at. It is optional in the API for callers with no screen;
 * this one HAS a screen, so it always sends it. A stale token comes back as
 * `stale_pending_change` (409) with its own problem+json message, which the caller
 * renders through `ProblemNotice` rather than pre-empting with a rule of its own.
 */
export function useApplyChanges(
  target: AgentTarget,
): UseMutationResult<ApplyOut, Error, ApplyIn> {
  const refresh = useAfterPublish(target);
  return useMutation({
    mutationFn: (payload: ApplyIn) =>
      apiRequest<ApplyOut>(adminSession(), agentPath(target, "apply"), {
        method: "POST",
        body: payload,
      }),
    onSuccess: refresh,
  });
}

/** "Undo" — discards the staged script by moving a pointer; no version is deleted. */
export function useUndoChanges(target: AgentTarget): UseMutationResult<UndoOut, Error, void> {
  const refresh = useAfterPublish(target);
  return useMutation({
    mutationFn: () =>
      apiRequest<UndoOut>(adminSession(), agentPath(target, "undo"), { method: "POST" }),
    onSuccess: refresh,
  });
}

/**
 * The cost-runaway guard (§2b:107). Applies immediately — a live agent is re-published
 * in the same transaction — so there is no Apply step for this one, which is exactly
 * what the lane table says and why the table is worth rendering.
 *
 * `null` restores the platform default and never means unlimited. Out-of-range values
 * are refused server-side with `call_cap_out_of_range`; the bounds are published by
 * `GET /v1/agents/lanes` so the form can hint them without hardcoding a second copy.
 */
export function useSetCallCap(
  target: AgentTarget,
): UseMutationResult<CallCapOut, Error, SetCallCapIn> {
  const refresh = useAfterPublish(target);
  return useMutation({
    mutationFn: (payload: SetCallCapIn) =>
      apiRequest<CallCapOut>(adminSession(), agentPath(target, "call-cap"), {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: refresh,
  });
}
