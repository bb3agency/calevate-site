"use client";

/**
 * The account's outbound consent posture (D-624) — does a MISSING opt-in stop a dial?
 *
 * `compliance/service.check_dispatch` is permissive about consent by design ("absence is
 * not a refusal"), because most dialable numbers have no `consent_ledger` row: a number
 * typed in by staff, a CSV import, a customer who rang in. This switch is the one account
 * that wants the other answer saying so once, in a place the gate reads on every dial.
 *
 * Two API decisions the screen keeps rather than smooths:
 *
 * - **Reading is `org:read`, writing is `org:manage`.** Everybody who can see a refused
 *   campaign row can find out what `no_consent_record` means; only the owner can move the
 *   line. So the card renders for every session and the switch is gated separately from
 *   the rest of the do-not-call screen, which is `leads:dispatch`.
 * - **It is a PUT of the whole resource**, so the mutation sends the value it wants rather
 *   than a toggle — two tabs open on this card cannot race into an inverted state.
 *
 * `changed` is deliberately NOT in the response: the server records it in the audit row,
 * and a screen that rendered "no change" for the second of two identical clicks would be
 * reporting on the request rather than on the account.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type OutboundConsentPolicy = Schemas["OutboundConsentPolicyOut"];

export const OUTBOUND_CONSENT_POLICY_PATH = "/v1/compliance/call-consent/policy";

export function outboundConsentQueryKey(slug: string): [string, string] {
  return ["outbound-consent-policy", slug];
}

/** No `refetchInterval`: the only thing that moves this is a write from this card. */
export function useOutboundConsentPolicy(
  session: Session,
): UseQueryResult<OutboundConsentPolicy> {
  return useQuery({
    queryKey: outboundConsentQueryKey(session.orgSlug),
    queryFn: () => apiRequest<OutboundConsentPolicy>(session, OUTBOUND_CONSENT_POLICY_PATH),
  });
}

export function useSetOutboundConsentPolicy(session: Session) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (outbound_requires_consent: boolean) =>
      apiRequest<OutboundConsentPolicy>(session, OUTBOUND_CONSENT_POLICY_PATH, {
        method: "PUT",
        body: { outbound_requires_consent },
      }),
    onSuccess: (policy) => {
      // Seeded from the response rather than invalidated-and-refetched: the PUT returns
      // the whole resource, so a round trip would only re-fetch what is already in hand.
      queryClient.setQueryData(outboundConsentQueryKey(session.orgSlug), policy);
    },
  });
}
