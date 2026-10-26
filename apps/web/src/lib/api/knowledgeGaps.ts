"use client";

/**
 * Client-realm Knowledge Gaps hooks.
 *
 * A gap is a question the agent could not answer on a real call — surfaced as URGENT
 * because the same question lands on the next caller too. This is the data behind the
 * dashboard-home "What needs you" count and the link it carries. Gaps are answered and
 * dismissed in the Questions to answer list (`teachQuestions.ts`, D-893), which closes every
 * agent's gap on the topic at once.
 *
 * Types are ALIASED from the generated schema so they cannot drift from
 * `apps/api/insights/schemas.py`. Every quote field carries REDACTED text — the columns
 * behind them only ever hold redacted text (hard rule 6) — so there is nothing raw here.
 */

import { livePoll } from "@/lib/live/liveStatus";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

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
    refetchInterval: livePoll(60_000),
  });
}
