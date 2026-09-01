"use client";

/**
 * Client-realm "needs attention" hook.
 *
 * One query for the whole queue: the API already merges its four sources
 * (blocked leads, failed deliveries, stalled campaigns, rejected knowledge)
 * newest-first, so the screen has no joins or sorting of its own to do.
 *
 * Types are ALIASED from the generated schema now that `/v1/attention` has a
 * real response model, so they cannot drift from `attention_queue` in
 * apps/api/crm/attention.py.
 *
 * Field meanings the generated type does not carry: `title` is the subject (who
 * or what stopped), `detail` is the remedy (what happened and what the owner can
 * do about it), `rule` is the machine name of the rule that fired (e.g. "dnc")
 * when one did, and `href` is a realm-relative link to the screen where the fix
 * lives, e.g. "/leads".
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AttentionItem = Schemas["AttentionItemOut"];

/**
 * The things the platform refuses to do quietly (SURFACES §2b) — derived from the
 * generated item type rather than re-listed, so a fifth kind on the server becomes a
 * type error in `KIND_COPY` instead of an unstyled chip.
 */
export type AttentionKind = AttentionItem["kind"];

/**
 * `counts` is keyed by `AttentionKind`, but the server OMITS kinds with nothing in
 * them, so a lookup is genuinely absent rather than zero — read it as `counts[k] ?? 0`.
 *
 * `counts` and `total` describe the whole set; `items` is the newest `limit` of it. They
 * are counted by their own queries server-side rather than taken from the rows, so
 * `total > items.length` is normal on a busy account and is the shortfall the screen
 * spells out. Never recompute either from `items` — that is the exact bug the API fixed.
 */
export type AttentionQueue = Schemas["AttentionOut"];

/**
 * The queue's cache key, OWNED HERE — never respelled at a call site.
 *
 * Exported because the bell in `app/c/[slug]/layout.tsx` renders a COUNT of things the
 * client is expected to go and fix, while the mutations that fix them live in other
 * modules. Those modules invalidate this key so the badge drops when the work is done
 * rather than up to a minute later, and they reach it through this function for the
 * reason `kb.ts` records about `queryKeys.me`: two spellings of one key that happen to
 * be equal today is exactly how an invalidation silently stops working.
 */
export const attentionKey = (org: string) => ["attention", org] as const;

export function useAttention(session: Session): UseQueryResult<AttentionQueue> {
  return useQuery({
    queryKey: attentionKey(session.orgSlug),
    queryFn: () => apiRequest<AttentionQueue>(session, "/v1/attention"),
    // This is a work queue someone keeps open in a tab; a minute keeps it
    // honest without hammering the four count queries behind it.
    refetchInterval: 60_000,
  });
}
