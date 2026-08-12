"use client";

/**
 * Client-realm knowledge hooks.
 *
 * Only the submitting half lives in the client realm — approval and publish are admin
 * actions (D-22), which is why there is no `approve` mutation here and why the screen
 * says a submission is "in review" rather than showing a button that would 403.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];
export type KbSubmitResult = Schemas["SubmitOut"];

export function useKbSources(session: Session): UseQueryResult<KbSource[]> {
  return useQuery({
    queryKey: ["kb", session.orgSlug],
    queryFn: () => apiRequest<KbSource[]>(session, "/v1/kb/sources"),
    // Slower than the call surfaces: an approval is a human on our side, measured in
    // hours, not the two-minute post-call SLO.
    refetchInterval: 120_000,
  });
}

export function useKbChunks(session: Session, sourceId: string | null) {
  return useQuery({
    queryKey: ["kb-preview", session.orgSlug, sourceId],
    queryFn: () => apiRequest<KbChunk[]>(session, `/v1/kb/sources/${sourceId}/preview`),
    enabled: Boolean(sourceId),
  });
}

export function useSubmitKnowledge(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, name, body }: { agentId: string; name: string; body: string }) =>
      apiRequest<KbSubmitResult>(session, "/v1/kb/sources", {
        method: "POST",
        body: { agent_id: agentId, name, body, kind: "text" },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] }),
  });
}

export function useAgents(session: Session) {
  return useQuery({
    queryKey: ["agents", session.orgSlug],
    queryFn: () => apiRequest<Schemas["AgentOut"][]>(session, "/v1/agents"),
    staleTime: 5 * 60_000,
  });
}
