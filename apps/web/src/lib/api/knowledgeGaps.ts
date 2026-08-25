"use client";

/**
 * Client-realm Knowledge Gaps hooks.
 *
 * A gap is a question the agent could not answer on a real call — surfaced as URGENT
 * because the same question lands on the next caller too. This is the data behind the
 * dashboard-home "Needs attention" card and the per-agent list.
 *
 * Types are ALIASED from the generated schema so they cannot drift from
 * `apps/api/insights/schemas.py`. Every quote field carries REDACTED text — the columns
 * behind them only ever hold redacted text (hard rule 6) — so there is nothing raw here.
 *
 * Dismiss and Teach both mutate one gap and remove it from the OPEN list. They apply an
 * optimistic removal (the card disappears immediately) and then invalidate the queries the
 * change touches — the gaps list, the dashboard urgent count, and the KB queue that a
 * teach seeds a draft into.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KnowledgeGap = Schemas["KnowledgeGapOut"];
export type KnowledgeGapList = Schemas["KnowledgeGapListOut"];
export type GapSignal = KnowledgeGap["signal"];

/** The status set to fetch. "open" is the urgent default; "all" returns every status. */
export type GapScope = "open" | "taught" | "dismissed" | "all";

export interface GapFilters {
  agentId?: string;
  status?: GapScope;
  limit?: number;
}

function gapsKey(session: Session, filters: GapFilters) {
  return [
    "knowledge-gaps",
    session.orgSlug,
    filters.agentId ?? "all-agents",
    filters.status ?? "open",
    filters.limit ?? null,
  ] as const;
}

export function useKnowledgeGaps(
  session: Session,
  filters: GapFilters = {},
): UseQueryResult<KnowledgeGapList> {
  const params = new URLSearchParams();
  if (filters.agentId) params.set("agent_id", filters.agentId);
  if (filters.status) params.set("status", filters.status);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return useQuery({
    queryKey: gapsKey(session, filters),
    queryFn: () =>
      apiRequest<KnowledgeGapList>(session, `/v1/knowledge-gaps${qs ? `?${qs}` : ""}`),
    // A work queue someone keeps open in a tab; a minute keeps it honest without hammering
    // the count query behind it — the cadence `useAttention` uses.
    refetchInterval: 60_000,
  });
}

/** Optimistically drop `gapId` from every cached OPEN gaps list for this org. */
function dropFromOpenLists(
  client: ReturnType<typeof useQueryClient>,
  session: Session,
  gapId: string,
) {
  client
    .getQueriesData<KnowledgeGapList>({ queryKey: ["knowledge-gaps", session.orgSlug] })
    .forEach(([key, list]) => {
      if (!list) return;
      const removed = list.items.find((gap) => gap.id === gapId);
      if (!removed || removed.status !== "open") return;
      client.setQueryData<KnowledgeGapList>(key, {
        ...list,
        items: list.items.filter((gap) => gap.id !== gapId),
        open_count: Math.max(0, list.open_count - 1),
      });
    });
}

function invalidateAfterGapChange(
  client: ReturnType<typeof useQueryClient>,
  session: Session,
) {
  void client.invalidateQueries({ queryKey: ["knowledge-gaps", session.orgSlug] });
  void client.invalidateQueries({ queryKey: ["dashboard", session.orgSlug] });
  // A teach seeds a KB draft into the review queue; a dismiss does not, but invalidating
  // both keeps one code path and the KB refetch is cheap.
  void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] });
}

export function useDismissGap(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ gapId, reason }: { gapId: string; reason?: string }) =>
      apiRequest<KnowledgeGap>(session, `/v1/knowledge-gaps/${gapId}/dismiss`, {
        method: "POST",
        body: { reason: reason ?? null },
      }),
    onMutate: async ({ gapId }) => {
      await client.cancelQueries({ queryKey: ["knowledge-gaps", session.orgSlug] });
      const snapshot = client.getQueriesData<KnowledgeGapList>({
        queryKey: ["knowledge-gaps", session.orgSlug],
      });
      dropFromOpenLists(client, session, gapId);
      return { snapshot };
    },
    onError: (_err, _vars, context) => {
      // Put every list back exactly as it was — a failed dismiss must not leave the card
      // hidden with no way to see the failure.
      context?.snapshot.forEach(([key, list]) => client.setQueryData(key, list));
    },
    onSettled: () => invalidateAfterGapChange(client, session),
  });
}

export interface TeachGap {
  gapId: string;
  answer: string;
  createKbDraft?: boolean;
}

export function useTeachGap(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ gapId, answer, createKbDraft = true }: TeachGap) =>
      apiRequest<KnowledgeGap>(session, `/v1/knowledge-gaps/${gapId}/teach`, {
        method: "POST",
        body: { answer, create_kb_draft: createKbDraft },
      }),
    onMutate: async ({ gapId }) => {
      await client.cancelQueries({ queryKey: ["knowledge-gaps", session.orgSlug] });
      const snapshot = client.getQueriesData<KnowledgeGapList>({
        queryKey: ["knowledge-gaps", session.orgSlug],
      });
      dropFromOpenLists(client, session, gapId);
      return { snapshot };
    },
    onError: (_err, _vars, context) => {
      context?.snapshot.forEach(([key, list]) => client.setQueryData(key, list));
    },
    onSettled: () => invalidateAfterGapChange(client, session),
  });
}
