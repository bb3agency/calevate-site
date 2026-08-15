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

/**
 * One voice at one moment: the id stored on the agent, and the catalogue entry when the
 * server recognises it. `catalog` is null for a voice we no longer offer — the id is
 * still there, so a retired voice reads as itself rather than as "no voice".
 */
export type AgentVoice = Schemas["AgentVoiceOut"];

/**
 * CONFIGURED versus LIVE, which for a voice are two different facts.
 *
 * `PATCH /v1/admin/tenants/{tenant_id}/agents/{agent_id}/voice` writes our row and does
 * not touch the engine, so a live
 * agent keeps its old voice until the next publish. A screen showing one of these and
 * calling it "the voice" would be making a claim about a client's phone line that
 * nobody checked — the same defect `live_prompt_id` fixed for the script.
 *
 * `live` is null when nothing is recorded as sent, and that reads two ways: an
 * unpublished agent has nothing live, and a published one was published before the
 * server recorded what it sent. Read it WITH `PendingState.published`, and never as
 * "in sync" — `republish_required` is the server's answer and it errs towards
 * "publish again" in both cases.
 */
export type AgentVoiceState = Schemas["VoiceStateOut"];

/** What the unsaved-changes banner and the voice picker render, in one read. */
export type PendingState = Schemas["PendingOut"];
export type PendingChange = Schemas["PendingChangeOut"];

/**
 * What a READ-BACK confirmed, as opposed to what we sent.
 *
 * `AgentVoiceState` above splits CONFIGURED from SENT. This splits SENT from CONFIRMED,
 * and it is the fact "live" used to assert with no evidence: a 2xx from the voice
 * platform says it took the bytes, not that the agent is running them.
 *
 * `state` is `unverified` | `applied` | `unreadable` | `unreachable`. Render `confirmed`
 * — never `state !== "unverified"` — because "we could not tell" is not "it matched",
 * and the whole point of the four values is that they are four different answers.
 */
export type EngineVerification = Schemas["VerificationOut"];

/**
 * What the voice platform is running RIGHT NOW, read on demand.
 *
 * A vendor round trip per call, which is why it is a separate query with `enabled`
 * off by default rather than part of the pending banner. It is the only read that can
 * see an agent edited in the vendor's own dashboard, or a publish that failed on our
 * side after the vendor had already accepted it.
 */
export type EngineState = Schemas["EngineStateOut"];

/**
 * What `POST …/agents/{id}/publish` answers: the engine's own ref for this agent.
 *
 * The fully-qualified schema key, because `admin/routes.py` has a `PublishOut` of its
 * own (KB publishing) and the generator namespaces both rather than picking one.
 */
export type PublishOut = Schemas["apps__api__agents__routes__PublishOut"];

export type ApplyIn = Schemas["ApplyIn"];
export type ApplyOut = Schemas["ApplyOut"];
export type UndoOut = Schemas["UndoOut"];
export type SetCallCapIn = Schemas["SetCallCapIn"];
export type CallCapOut = Schemas["CallCapOut"];

export const publishingKeys = {
  /** Static per deployment, but still org-keyed: one cache per session identity. */
  lanes: (org: string) => ["agent-lanes", org] as const,
  pending: (org: string, agentId: string) => ["agent-pending", org, agentId] as const,
  engineState: (org: string, agentId: string) =>
    ["agent-engine-state", org, agentId] as const,
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

/**
 * Read the voice platform back, on demand.
 *
 * `enabled` is the caller's, and it defaults to OFF everywhere it is used: every call
 * costs one request to the vendor, so a query that ran on mount would dial them once
 * per page view of every agent screen. The operator presses a button; that is what
 * `enabled` flips.
 *
 * `staleTime: 0` deliberately: the answer is about the vendor's state at an instant,
 * and a cached "in sync" is exactly the reassurance this read exists to stop anyone
 * giving. `gcTime` keeps the last answer on screen between presses.
 */
export function useTenantEngineState(
  slug: string,
  agentId: string,
  enabled: boolean,
): UseQueryResult<EngineState> {
  const session = viewAsSession(slug);
  return useQuery({
    queryKey: publishingKeys.engineState(slug, agentId),
    queryFn: () => apiRequest<EngineState>(session, `/v1/agents/${agentId}/engine-state`),
    enabled: enabled && Boolean(slug) && Boolean(agentId),
    staleTime: 0,
  });
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

/**
 * "Put this agent on the voice platform" — the FIRST publish (FLOWS §1 step 7).
 *
 * ## The hole this fills
 *
 * `POST /v1/admin/tenants/{tid}/agents/{aid}/publish` has been mounted and tested since
 * the route moved onto the tenant path, and **nothing in either realm called it**. Every
 * other publish in the product is a RE-publish that runs only when the agent is already
 * live: `apply_to_live` guards its engine push on `row.is_live`, `set_call_cap` and
 * `recompile_t0` on `status == 'live' AND engine_agent_ref`. So an agent minted by the
 * wizard — `status='draft'`, `engine_agent_ref=NULL` — could never become live from any
 * screen. A founder could sign a client, run the whole wizard, invite the owner, and the
 * agent would sit in `draft` with no control anywhere that moved it.
 *
 * ## Why it lives here and not in `agents.ts`
 *
 * `agents.ts` is the ROSTER — the list five screens read for a name and an id. This is
 * the third instance of the one question this module already owns: what is configured,
 * what is live, and what closes the gap. Apply, the call cap and the voice all answer it
 * for an agent that is already on the engine; this answers it for one that is not, and it
 * shares `useAfterPublish`, so a first publish invalidates exactly the caches Apply does.
 *
 * ADMIN realm, `agents:write`, tenant in the path — the same shape as Apply and Undo, and
 * for the same reason: only an operator can author the script this pushes.
 */
export function usePublishAgent(
  target: AgentTarget,
): UseMutationResult<PublishOut, Error, void> {
  const refresh = useAfterPublish(target);
  return useMutation({
    mutationFn: () =>
      apiRequest<PublishOut>(adminSession(), agentPath(target, "publish"), { method: "POST" }),
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

/* ------------------------------------------------- A/B script testing (ROADMAP M3) */

/**
 * The experiment hooks live HERE rather than in `prompts.ts`, and the reason is the one
 * that decides most of this module's shape: **concluding an experiment publishes**.
 * Promoting an arm mints a prompt version and applies it through `apply_to_live`, so it
 * moves the staged/live pointers, the version history and the agent roster — exactly the
 * four caches `useAfterPublish` already invalidates. Putting these hooks in `prompts.ts`
 * would need that helper imported the other way round, and `publishing.ts` already
 * imports `promptHistoryKey`: a cycle between the two modules for one call site.
 */
export type ExperimentState = Schemas["ExperimentStateOut"];
export type Experiment = Schemas["ExperimentOut"];
export type ExperimentVariant = Schemas["VariantOut"];
export type ExperimentRules = Schemas["ExperimentRulesOut"];
export type StartExperimentIn = Schemas["StartExperimentIn"];
export type StartExperimentOut = Schemas["StartExperimentOut"];
/**
 * `experiment_id` is REQUIRED on this body, and that is the whole point of the type.
 *
 * The endpoint used to conclude "whatever is running on this agent", so a retry arriving
 * after a LATER test had started ended the later test. Naming the experiment makes the
 * request answerable about the test it names and never redirected onto another one — the
 * generated type now carries the requirement, so a caller that forgets it does not
 * compile.
 */
export type ConcludeExperimentIn = Schemas["ConcludeExperimentIn"];
export type ConcludeExperimentOut = Schemas["ConcludeExperimentOut"];

export const experimentKey = (org: string, agentId: string) =>
  ["agent-experiment", org, agentId] as const;

/**
 * Counts move with every dial, so this one is genuinely stale within a minute — but it
 * is still not polled. An A/B test is read to make a DECISION about promoting a script,
 * which is a thing a human does once a day at most, and a screen that refetched itself
 * every few seconds would add load to answer a question nobody asked again.
 */
const EXPERIMENT_STALE_MS = 30_000;

/** Client-realm read (`agents:read`), reached from the console by impersonation — the
 *  same D-22 split as `useTenantPending` above. */
export function useTenantExperiment(
  slug: string,
  agentId: string,
): UseQueryResult<ExperimentState> {
  const session = viewAsSession(slug);
  return useQuery({
    queryKey: experimentKey(slug, agentId),
    queryFn: () => apiRequest<ExperimentState>(session, `/v1/agents/${agentId}/experiment`),
    enabled: Boolean(slug) && Boolean(agentId),
    staleTime: EXPERIMENT_STALE_MS,
  });
}

function useAfterExperiment(target: AgentTarget) {
  const client = useQueryClient();
  const refresh = useAfterPublish(target);
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: experimentKey(target.slug, target.agentId) }),
      refresh(),
    ]);
}

export function useStartExperiment(
  target: AgentTarget,
): UseMutationResult<StartExperimentOut, Error, StartExperimentIn> {
  const refresh = useAfterExperiment(target);
  return useMutation({
    mutationFn: (payload: StartExperimentIn) =>
      apiRequest<StartExperimentOut>(adminSession(), agentPath(target, "experiment"), {
        method: "POST",
        body: payload,
      }),
    onSuccess: refresh,
  });
}

/**
 * Stop the test. `promote: null` is a real instruction — "keep the control" — not a
 * cancel, so it is the same mutation with the same audit trail rather than a second
 * endpoint that would let the two endings diverge.
 *
 * `experiment_id` is required and the caller sends the id it is DISPLAYING, not the id
 * of whatever is running when the request lands. This screen caches the results read for
 * 30 seconds and refetches on focus, so an operator can quite ordinarily be looking at a
 * test a colleague has already ended — and if the colleague started the next one, the
 * agent's "current" test is no longer the one under the button. Naming the id turns that
 * into a 409/200-no-op about the test on screen instead of a promotion on the new one.
 */
export function useConcludeExperiment(
  target: AgentTarget,
): UseMutationResult<ConcludeExperimentOut, Error, ConcludeExperimentIn> {
  const refresh = useAfterExperiment(target);
  return useMutation({
    mutationFn: (payload: ConcludeExperimentIn) =>
      apiRequest<ConcludeExperimentOut>(
        adminSession(),
        agentPath(target, "experiment/conclude"),
        { method: "POST", body: payload },
      ),
    onSuccess: refresh,
  });
}
