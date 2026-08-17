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
import type { components } from "./schema";

export type Agent = AgentSummary;

/** Which notices to switch; `null`/omitted leaves one alone. */
export type DisclosureIn = components["schemas"]["DisclosureIn"];
export type DisclosureOut = components["schemas"]["DisclosureOut"];

/**
 * One field the agent is configured to capture. Derived from `AgentOut` rather
 * than aliased a second time — it is the same row the CRM already names
 * `LeadColumn`, seen from the other end of the pipeline.
 */
export type AgentExtractionField = Agent["extraction_fields"][number];

export const agentKeys = {
  all: (org: string) => ["agents", org] as const,
  one: (org: string, agentId: string) => ["agent", org, agentId] as const,
};

/**
 * Agent config changes are a human process on our side measured in days, not the
 * two-minute post-call SLO — so no polling, and a long stale window.
 */
const AGENT_STALE_MS = 5 * 60_000;

export function useAgents(session: Session): UseQueryResult<Agent[]> {
  return useQuery({
    queryKey: agentKeys.all(session.orgSlug),
    queryFn: () => apiRequest<Agent[]>(session, "/v1/agents"),
    staleTime: AGENT_STALE_MS,
  });
}

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
