"use client";

/**
 * Client-realm "needs attention" hook.
 *
 * One query for the whole queue: the API already merges its four sources
 * (blocked leads, failed deliveries, stalled campaigns, rejected knowledge)
 * newest-first, so the screen has no joins or sorting of its own to do.
 *
 * Types are defined locally rather than aliased from the generated schema
 * because the attention endpoint is not yet in the OpenAPI snapshot; the
 * shape mirrors `attention_queue` in apps/api/crm/attention.py. Once the
 * schema is regenerated (`pnpm gen:api`), swap these for schema aliases so
 * they cannot drift.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";

/** The four things the platform refuses to do quietly (SURFACES §2b). */
export type AttentionKind =
  | "lead_blocked"
  | "delivery_failed"
  | "campaign_stalled"
  | "kb_rejected";

export interface AttentionItem {
  kind: AttentionKind;
  id: string;
  /** The subject — who or what stopped. */
  title: string;
  /** The remedy — what happened and what the owner can do about it. */
  detail: string;
  /** Machine name of the rule that fired (e.g. "dnc"), when one did. */
  rule: string | null;
  occurred_at: string;
  /** Realm-relative link to the screen where the fix lives, e.g. "/leads". */
  href: string | null;
}

export interface AttentionQueue {
  total: number;
  counts: Partial<Record<AttentionKind, number>>;
  items: AttentionItem[];
}

export function useAttention(session: Session): UseQueryResult<AttentionQueue> {
  return useQuery({
    queryKey: ["attention", session.orgSlug],
    queryFn: () => apiRequest<AttentionQueue>(session, "/v1/attention"),
    // This is a work queue someone keeps open in a tab; a minute keeps it
    // honest without hammering the four count queries behind it.
    refetchInterval: 60_000,
  });
}
