"use client";

/**
 * The dashboard-AI allowance, and the one thing a client can buy with it (D-127
 * G-3/G-4/G-5).
 *
 * Three things this module deliberately does NOT do, each because the server already
 * does it and a second implementation in TypeScript is where the two start disagreeing
 * about a client's money:
 *
 * - **it never divides a rupee amount.** "About 500 assists" is `requests_included`,
 *   computed server-side from the ceiling and a reference price the API does not
 *   publish. A browser that did the division would need the price, and a price in a
 *   bundle is a price that is stale the day it changes.
 * - **it never decides the state.** `state` and `extra_unavailable_reason` are the
 *   server's own words for what this month is, in the same order the route refuses in,
 *   so the screen's explanation and the API's refusal cannot drift apart.
 * - **it never mints the amount.** `accept_amount_inr` is echoed back from
 *   `extra_block_inr` exactly as it arrived — the server compares them for EQUALITY and
 *   refuses a mismatch, which is what stops a screen left open across a price change
 *   from debiting a figure nobody was shown.
 *
 * Money crosses the wire as a STRING (hard rule 7). `500.00` sent as a JSON number has
 * already been through a binary double by the time the server sees it, and this one is
 * compared for equality.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AiQuota = Schemas["AiQuotaOut"];

const PATH = "/v1/billing/ai-quota";

export function aiQuotaKey(orgSlug: string) {
  return ["ai-quota", orgSlug] as const;
}

/**
 * `enabled` exists for the CALL DETAIL screen, which needs these figures only once a
 * client has actually met the ceiling — the dialog re-reads this route rather than
 * rendering the amount out of the refusal body (`billing/ai_quota.require_ai_assist`
 * says why: one computation of what a block costs). Defaulting to true keeps the AI-help
 * screen, which is ABOUT the allowance, exactly as it was.
 */
export function useAiQuota(
  session: Session,
  options: { enabled?: boolean } = {},
): UseQueryResult<AiQuota> {
  return useQuery({
    queryKey: aiQuotaKey(session.orgSlug),
    queryFn: () => apiRequest<AiQuota>(session, PATH),
    enabled: options.enabled ?? true,
    // An allowance moves when an assist runs, not on a timer, and this screen is where
    // someone comes to decide whether to spend money — a figure that refreshes under
    // them mid-decision is worse than one that is a minute old.
    staleTime: 60_000,
  });
}

/**
 * Accept the charge. THE only call in this console that debits a wallet.
 *
 * The mutation takes the amount as a string and passes it through untouched: it is the
 * server's own `extra_block_inr`, and the point of the echo is that the browser did not
 * compute it.
 *
 * On success both this query and the usage panel are refreshed, because the debit lands
 * on the SAME wallet the usage screen prints as "Calling credit" — a balance that still
 * showed the pre-debit figure would be this console contradicting itself about money.
 */
export function useBuyAiExtra(session: Session) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (acceptAmountInr: string) =>
      apiRequest<AiQuota>(session, `${PATH}/extra`, {
        method: "POST",
        body: { accept_amount_inr: acceptAmountInr },
      }),
    onSuccess: (quota) => {
      queryClient.setQueryData(aiQuotaKey(session.orgSlug), quota);
      queryClient.invalidateQueries({ queryKey: ["usage", session.orgSlug] });
    },
  });
}
