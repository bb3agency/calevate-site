"use client";

/**
 * Each agent's own call outcomes (D-836): how a call can end for this business, and how far
 * each moves the lead. Read with `/v1/call-outcomes`; one agent's list is replaced with
 * `PUT /v1/agents/{id}/call-outcomes`. The AI draft is queued by the server, once per agent.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type CallOutcomes = Schemas["CallOutcomesOut"];
export type CallOutcomesAgent = Schemas["CallOutcomesAgentOut"];
export type CallOutcome = Schemas["CallOutcomeOut"];
export type CallOutcomeIn = Schemas["CallOutcomeIn"];
export type LeadMove = CallOutcome["lead_status"];

export const callOutcomesKeys = {
  client: (org: string) => ["call-outcomes", org] as const,
};

/** While an agent's draft is being written the screen asks again on this interval. */
const DRAFT_POLL_MS = 4000;

function drafting(data: CallOutcomes | undefined): boolean {
  return Boolean(data?.agents.some((a) => a.draft === "queued" || a.draft === "running"));
}

export function useCallOutcomes(session: Session): UseQueryResult<CallOutcomes> {
  return useQuery({
    queryKey: callOutcomesKeys.client(session.orgSlug),
    queryFn: () => apiRequest<CallOutcomes>(session, "/v1/call-outcomes"),
    refetchInterval: (query) => (drafting(query.state.data) ? DRAFT_POLL_MS : false),
  });
}

export function useSaveCallOutcomes(
  session: Session,
): UseMutationResult<CallOutcomesAgent, Error, { agentId: string; outcomes: CallOutcomeIn[] }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, outcomes }) =>
      apiRequest<CallOutcomesAgent>(
        session,
        `/v1/agents/${encodeURIComponent(agentId)}/call-outcomes`,
        { method: "PUT", body: { outcomes } },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: callOutcomesKeys.client(session.orgSlug) }),
  });
}
