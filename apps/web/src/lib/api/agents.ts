"use client";

/**
 * Client-realm agent hooks — `GET /v1/agents`, `GET /v1/agents/{agent_id}`.
 *
 * READ-ONLY WITH ONE EXCEPTION, and the exception is the point of D-163. D-21 draws
 * the control boundary (see the docstring on apps/api/agents/routes.py): a client can
 * see every agent we run for them, but editing one — an extraction schema especially —
 * regenerates prompt hints and needs a regression run, so it routes through us. There
 * is deliberately no mutation hook for any of that, for the same reason kb.ts has no
 * `approve`: a button that would 403 is worse than no button at all.
 *
 * `useSetDisclosure` is the exception because the DECISION is not ours to make. The
 * client is the Principal Entity — the calls go out under their identity and their DLT
 * templates — so which notices their agent volunteers is theirs to choose and theirs to
 * answer for. The endpoint is `org:manage`, which the client OWNER holds and which no
 * admin or impersonating session holds against a tenant (D-22), so this control is
 * genuinely theirs alone and every flip is written to the audit log.
 *
 * What it can never change is the agent's ANSWER when a caller asks outright. The
 * server carries that wording (`truthful_answer_rule` on every agent) precisely so a
 * screen cannot paraphrase it into the opposite promise.
 *
 * Types alias the GENERATED schema (client.ts doctrine) so they cannot drift from
 * the API. The list key matches the one `useAgents` in kb.ts already uses, so the
 * agent picker there and this screen share one cache entry rather than fetching
 * the same small list twice; fold that copy into this module when kb.ts is next
 * touched.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type AgentSummary, type Session } from "./client";
import { publishingKeys } from "./publishing";
import type { components } from "./schema";

export type Agent = AgentSummary;

/** Which notices to switch; `null`/omitted leaves one alone. */
export type DisclosureIn = components["schemas"]["DisclosureIn"];
export type DisclosureOut = components["schemas"]["DisclosureOut"];

/** Switch caller continuity — remembering callers AND booking their call-backs. */
export type CallerMemoryIn = components["schemas"]["CallerMemoryIn"];
export type CallerMemoryOut = components["schemas"]["CallerMemoryOut"];

/**
 * One field the agent is configured to capture. Derived from `AgentOut` rather
 * than aliased a second time — it is the same row the CRM already names
 * `LeadColumn`, seen from the other end of the pipeline.
 */
export type AgentExtractionField = Agent["extraction_fields"][number];

/** The whole ordered list a PUT replaces, and the answer a PUT gives back. */
export type ExtractionSchemaIn = components["schemas"]["ExtractionSchemaIn"];
export type ExtractionSchemaOut = components["schemas"]["ExtractionSchemaOut"];

export const agentKeys = {
  all: (org: string) => ["agents", org] as const,
  /** The archive is a DIFFERENT list from a different request — see `useArchivedAgents`. */
  archived: (org: string) => ["agents-archived", org] as const,
  stats: (org: string) => ["agent-stats", org] as const,
  one: (org: string, agentId: string) => ["agent", org, agentId] as const,
  /**
   * EVERY agent detail row this org has cached — the PREFIX of `one`.
   *
   * For the invalidations that cannot name an id because the change was not about one
   * agent: moving the organisation's default model (`lib/api/llmModels.ts`) changes
   * `llm_model_effective` on every agent that is inheriting it, and the mutation has no
   * list of which those are. Spelled here rather than as a bare `["agent", org]` at the
   * call site, because a second copy of a cache key is how two of four callers end up
   * refreshing and two do not.
   */
  allDetails: (org: string) => ["agent", org] as const,
};

/**
 * Agent config changes are a human process on our side measured in days, not the
 * two-minute post-call SLO — so no polling, and a long stale window.
 */
const AGENT_STALE_MS = 5 * 60_000;

export function useAgent(session: Session, agentId: string): UseQueryResult<Agent> {
  return useQuery({
    queryKey: agentKeys.one(session.orgSlug, agentId),
    queryFn: () => apiRequest<Agent>(session, `/v1/agents/${agentId}`),
    enabled: Boolean(agentId),
    staleTime: AGENT_STALE_MS,
  });
}

/**
 * Switch the AI disclosure or the recording notice on this agent (D-163).
 *
 * Sends only the switch that MOVED. The API treats a missing field as "leave this one
 * alone", so two switches on one screen cannot race each other into a read-modify-write
 * that resurrects the other's old value.
 *
 * The response is the server's own answer about the new posture — including
 * `opening_line`, the composed first utterance, and `engine_synced`, which says whether
 * the change reached the voice platform. Neither is recomputed here: joining the two
 * sentences in TypeScript would be a second implementation of a compliance rule, which
 * is exactly how a screen ends up describing a phone line it is not describing.
 *
 * The awaited invalidation (rather than `void`) is `publishing.ts::useAfterPublish`'s
 * argument: the roster row carries the posture this mutation just changed, so a paint
 * from the stale cache would contradict the switch the client just moved.
 */
export function useSetDisclosure(
  session: Session,
  agentId: string,
): UseMutationResult<DisclosureOut, Error, DisclosureIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: DisclosureIn) =>
      apiRequest<DisclosureOut>(session, `/v1/agents/${agentId}/disclosure`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
      ]),
  });
}

/**
 * Switch caller continuity on or off for one agent (D-513/D-514).
 *
 * `useSetDisclosure`'s reasoning, plus one of its own: this is the client's DURABLE-DATA
 * decision, not only their disclosure posture. Switching it on starts keeping a note about
 * the people who ring them, so the same `org:manage` permission governs it and the same
 * audit row records it.
 *
 * The refusals matter as much as the success and are surfaced verbatim by `ProblemNotice`:
 * an account that has not yet confirmed what its calls collect is refused with the
 * statement to confirm as the remediation, and a business whose kind cannot use this at all
 * is refused permanently. Neither is a validation error the screen should paraphrase.
 *
 * Invalidates the same two agent keys, because the opening line callers hear changes with
 * this switch — the sentence about keeping notes is added and removed with it, and the
 * agent row is where that composed line lives.
 */
export function useSetCallerMemory(
  session: Session,
  agentId: string,
): UseMutationResult<CallerMemoryOut, Error, CallerMemoryIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CallerMemoryIn) =>
      apiRequest<CallerMemoryOut>(session, `/v1/agents/${agentId}/caller-memory`, {
        method: "PATCH",
        body: payload,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
      ]),
  });
}

/**
 * Replace this agent's extraction variables — the whole ordered list at once (D-21 is
 * superseded here: the owner edits their own agents' capture columns self-serve).
 *
 * A whole-list PUT rather than per-field POST/PATCH/DELETE, mirroring the server's one
 * write path: the body is the entire list and each save mints a new schema version the
 * next call uses. `org:manage` is the owner's own permission — the same one the disclosure
 * and lifecycle controls gate on — so this is genuinely the client's to change and no
 * impersonating session holds it against a tenant (D-22).
 *
 * The awaited invalidation (rather than `void`) matches `useSetDisclosure`: the agent row
 * carries `extraction_fields`, so the screen must repaint from the server's stored answer
 * — including any normalisation the validator applied — rather than from the draft that was
 * sent.
 */
export function useSetExtractionSchema(
  session: Session,
  agentId: string,
): UseMutationResult<ExtractionSchemaOut, Error, ExtractionSchemaIn> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExtractionSchemaIn) =>
      apiRequest<ExtractionSchemaOut>(session, `/v1/agents/${agentId}/extraction-schema`, {
        method: "PUT",
        body: payload,
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
        client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
      ]),
  });
}


/* ═══════════════════════════════════════════════════════════════════════════════════
 * THE LIFE OF AN AGENT (D-440) — create, describe, activate, deactivate, archive, restore
 * ═══════════════════════════════════════════════════════════════════════════════════
 *
 * These are client-realm WRITES on `org:manage`, and D-21's boundary still holds: nothing
 * here edits what an agent SAYS or what it CAPTURES. What it adds is the object's own
 * life — a business owner minting an agent, naming it, putting it on the phone, taking it
 * off, and retiring it — which was previously not expressible at all: `admin/service`
 * minted exactly one agent per tenant, `publish_agent` moved it to `live`, and nothing in
 * the tree could move it back.
 *
 * **`org:manage`, NOT `agents:write`**, and the distinction decides every `useWriteAccess`
 * call on these screens. `agents:write` is admin-only and NEITHER client role holds it —
 * gating these controls on it would disable them for the owner they were built for.
 * `org:manage` is the owner's own permission, held by no admin or impersonating session
 * against a tenant (D-22), which is what makes an agent's roster genuinely the client's.
 * The API argues it in `agents/routes.py`: the calls go out under the client's DLT
 * Principal Entity, and whether their receptionist is on the line at 6pm on a Sunday is
 * not a support ticket.
 *
 * The server's state machine is `apps/api/agents/lifecycle.py::AGENT_TRANSITIONS` and is
 * NOT re-implemented here. Two of its rules shape the screens and are worth naming:
 *
 * - **A restore lands in `paused`, never `live`.** The engine may have been reconfigured
 *   or drifted while the agent sat retired, and only a publish with its read-back can
 *   establish what it is holding. So a restored agent is INACTIVE and the owner activates
 *   it deliberately, which runs that proof.
 * - **Activate is a PUBLISH, not a column write.** "Active" is a claim about the voice
 *   platform, and D-64 made `publish_agent` prove it before any column says `live`. That
 *   is why activating a brand-new agent is refused (`agent_has_no_script`) until somebody
 *   has written what it says — a refusal the screen renders rather than pre-empts.
 */

export type AgentStatus = Agent["status"];
export type AgentDirection = Agent["direction"];
export type AgentCreateIn = components["schemas"]["AgentCreateIn"];
/**
 * The languages an agent may be created or moved to — a CLOSED union since D-440.
 *
 * Read off the update body rather than off `AgentOut`, deliberately: `AgentOut
 * .language_primary` is a bare `str` (a row written before a language was retired must
 * still serialize), while this is what the server will ACCEPT. A copy table typed
 * `Record<AgentLanguage, string>` is then exhaustive — a fourth language on the server is
 * a type error here rather than a blank option nobody notices.
 */
export type AgentLanguage = NonNullable<AgentUpdateIn["language_primary"]>;
export type AgentUpdateIn = components["schemas"]["AgentUpdateIn"];
/**
 * The agents realm's lifecycle result — `AgentLifecycleOut` on the wire.
 *
 * NOT `LifecycleOut`, which is the ADMIN realm's tenant lifecycle (commercials.ts). The
 * server renamed its model precisely so the two stop colliding: two same-named models in
 * one FastAPI app make the generator qualify BOTH by their Python module, so the admin
 * console's type silently became `apps__api__admin__routes__LifecycleOut` and broke from a
 * change in a module it does not import. Both aliases here read the plain names again.
 */
export type LifecycleResult = components["schemas"]["AgentLifecycleOut"];
export type AgentStats = components["schemas"]["AgentStatsOut"];

/** The archive is its own query because the roster deliberately excludes it — see below. */
export const ARCHIVED_QUERY = "/v1/agents?status=archived";

/**
 * THE WORKING ROSTER — everything EXCEPT the archive.
 *
 * That exclusion is the SERVER's default and it is the one surprising thing about this
 * endpoint, so it is written down where the hook is rather than left to be discovered: the
 * archive is history and grows without limit while the working roster does not, so a
 * default of "everything" would let retired agents push live ones past the 200-row bound
 * with nothing on screen to say so.
 */
export function useAgents(session: Session): UseQueryResult<Agent[]> {
  return useQuery({
    queryKey: agentKeys.all(session.orgSlug),
    queryFn: () => apiRequest<Agent[]>(session, "/v1/agents"),
    staleTime: AGENT_STALE_MS,
  });
}

/**
 * THE ARCHIVE — a second request, made only by the screen that shows it.
 *
 * A separate query rather than a client-side filter of one bigger list, because the server
 * will not serve one bigger list (above). `enabled` lets the roster ask for it lazily; the
 * detail screen never needs it.
 */
export function useArchivedAgents(
  session: Session,
  enabled = true,
): UseQueryResult<Agent[]> {
  return useQuery({
    queryKey: agentKeys.archived(session.orgSlug),
    queryFn: () => apiRequest<Agent[]>(session, ARCHIVED_QUERY),
    enabled,
    staleTime: AGENT_STALE_MS,
  });
}

/**
 * What each agent has actually DONE — call counts, outcomes and when it was last used.
 *
 * A separate route from the roster on the server's own reasoning: the roster is opened on
 * every navigation and reads a handful of small rows, while this aggregates `calls`, the
 * biggest table a tenant owns. It is therefore a SEPARATE query here too rather than being
 * awaited alongside — the roster paints as soon as it can, and the activity numbers fill
 * in when they arrive.
 *
 * It INCLUDES archived agents, which is the opposite default to the roster and is not an
 * inconsistency: the roster answers "what can I work with", this answers "what happened".
 */
export function useAgentStats(session: Session): UseQueryResult<AgentStats[]> {
  return useQuery({
    queryKey: agentKeys.stats(session.orgSlug),
    queryFn: () => apiRequest<AgentStats[]>(session, "/v1/agents/stats"),
    staleTime: AGENT_STALE_MS,
  });
}

/**
 * Every read this section paints from, invalidated together after any write.
 *
 * ONE list rather than a per-hook set, for `publishing.ts::usePublishingRefresh`'s reason:
 * a lifecycle move changes the roster row, the archive, the detail row AND the publishing
 * state (an activate republishes), and two lists of cache keys for one set of screens is
 * where the drift starts — the second one always forgets a key.
 *
 * Awaited rather than `void`ed, so a button stops saying "Switching on…" only once the
 * screen behind it can paint the new state. A `void` here shows the old status for one
 * frame, which on this screen is the sentence "no caller hears it at all".
 */
function useAgentRefresh(session: Session, agentId?: string): () => Promise<unknown> {
  const client = useQueryClient();
  return () => {
    const invalidations = [
      client.invalidateQueries({ queryKey: agentKeys.all(session.orgSlug) }),
      // The archive moves in BOTH directions — archiving adds to it, restoring removes —
      // so it is refreshed on every move rather than only on the two that name it.
      client.invalidateQueries({ queryKey: agentKeys.archived(session.orgSlug) }),
    ];
    if (agentId !== undefined) {
      invalidations.push(
        client.invalidateQueries({ queryKey: agentKeys.one(session.orgSlug, agentId) }),
        // `publishingKeys`, never the literal `["agent-pending", …]`: that module owns the
        // spelling, and a second copy of a cache key is how two of four callers end up
        // refreshing and two do not (see the note at the foot of `kb.ts`).
        client.invalidateQueries({
          queryKey: publishingKeys.pending(session.orgSlug, agentId),
        }),
      );
    }
    return Promise.all(invalidations);
  };
}

export function useCreateAgent(session: Session): UseMutationResult<Agent, Error, AgentCreateIn> {
  const refresh = useAgentRefresh(session);
  return useMutation({
    mutationFn: (draft: AgentCreateIn) =>
      apiRequest<Agent>(session, "/v1/agents", { method: "POST", body: draft }),
    onSuccess: refresh,
  });
}

export function useUpdateAgent(
  session: Session,
  agentId: string,
): UseMutationResult<Agent, Error, AgentUpdateIn> {
  const refresh = useAgentRefresh(session, agentId);
  return useMutation({
    mutationFn: (patch: AgentUpdateIn) =>
      apiRequest<Agent>(session, `/v1/agents/${agentId}`, { method: "PATCH", body: patch }),
    onSuccess: refresh,
  });
}

/**
 * The four moves, as one hook, because they differ only in the verb in the path — and
 * because a screen that offers three of them at once needs ONE in-flight state and ONE
 * error channel, not three that can each be showing a different answer.
 */
export type LifecycleMove = "activate" | "deactivate" | "archive" | "restore";

export function useAgentLifecycle(
  session: Session,
  agentId: string,
): UseMutationResult<LifecycleResult, Error, LifecycleMove> {
  const refresh = useAgentRefresh(session, agentId);
  return useMutation({
    mutationFn: (move: LifecycleMove) =>
      apiRequest<LifecycleResult>(session, `/v1/agents/${agentId}/${move}`, { method: "POST" }),
    onSuccess: refresh,
  });
}
