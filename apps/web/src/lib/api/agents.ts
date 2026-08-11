"use client";

/**
 * Client-realm agent hooks — `GET /v1/agents`, `GET /v1/agents/{agent_id}`.
 *
 * READ-ONLY on purpose. D-21 draws the control boundary (see the docstring on
 * apps/api/agents/routes.py): a client can see every agent we run for them, but
 * editing one — an extraction schema especially — regenerates prompt hints and
 * needs a regression run, so it routes through us. There is deliberately no
 * mutation hook here, for the same reason kb.ts has no `approve`: a button that
 * would 403 is worse than no button at all.
 *
 * Types alias the GENERATED schema (client.ts doctrine) so they cannot drift from
 * the API. The list key matches the one `useAgents` in kb.ts already uses, so the
 * agent picker there and this screen share one cache entry rather than fetching
 * the same small list twice; fold that copy into this module when kb.ts is next
 * touched.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type AgentSummary, type Session } from "./client";

export type Agent = AgentSummary;

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
