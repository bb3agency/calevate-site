"use client";

/**
 * The client's own spending limit (D-34 R-11, SURFACES §2b).
 *
 * Two things this module deliberately does NOT do:
 *
 * - it does not compute the effective limit in the browser. The server publishes
 *   `effective_cap_*` alongside the plan's and the client's, because the number that
 *   actually stops a call is decided by the same SQL the compliance gate reads
 *   (`LEAST(hard_cap_*, client_cap_*)`), and a second implementation in TypeScript
 *   would eventually disagree with it on a screen.
 * - it does not decide whether a value is allowed. A limit looser than the plan's is
 *   refused server-side with `client_cap_exceeds_plan_cap`, and that refusal arrives as
 *   problem+json with its own message — the form renders the server's answer rather
 *   than pre-empting it with a rule of its own.
 *
 * Money crosses the wire as a STRING (hard rule 7). `2500.10` sent as a JSON number has
 * already been through a binary float by the time the server sees it.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Caps = Schemas["CapsOut"];

const PATH = "/v1/billing/caps";

export function capsKey(orgSlug: string) {
  return ["billing-caps", orgSlug] as const;
}

export function useCaps(session: Session): UseQueryResult<Caps> {
  return useQuery({
    queryKey: capsKey(session.orgSlug),
    queryFn: () => apiRequest<Caps>(session, PATH),
    // A limit changes when someone changes it, not on a timer.
    staleTime: 60_000,
  });
}

/**
 * PUT states the WHOLE client-side pair: `null` clears that side. A partial verb would
 * need a third state ("leave this one alone") that JSON makes easy to send by accident.
 *
 * The usage panel is invalidated as well as the caps query, because capping yourself
 * below this month's spend stops outbound calling immediately — the `capped` banner on
 * that screen has to move in the same breath, not on its next poll.
 */
export function useSetCaps(session: Session) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { capMinutes: number | null; capSpendInr: string | null }) =>
      apiRequest<Caps>(session, PATH, {
        method: "PUT",
        body: { cap_minutes: input.capMinutes, cap_spend_inr: input.capSpendInr },
      }),
    onSuccess: (caps) => {
      queryClient.setQueryData(capsKey(session.orgSlug), caps);
      queryClient.invalidateQueries({ queryKey: ["usage", session.orgSlug] });
    },
  });
}
