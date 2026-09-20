"use client";

/**
 * The outbound-sender confirmation a client records against one of their own numbers
 * (`apps/api/campaigns/sender_attestation.py`).
 *
 * TRAI direction RG-25/(18)/2023-QoS (E-10291), 18 Jun 2024 forbids a sender from placing
 * promotional, service or transactional voice calls from an ordinary 10-digit number, and
 * names the delegation chain — employees, channel partners, DSAs, BPO partner, outsourced
 * call centre — so the obligation cannot be handed to a vendor
 * (`docs/evidence/primary-legal-findings-2026-09-20.md` §1). Under Model B (D-474) the
 * client holds the carrier account and IS that sender, which is why the only write path is
 * a client-realm one: there is no admin route that confirms on their behalf.
 *
 * Three properties of the API this module keeps rather than smooths over:
 *
 * - **`applicable` is the SERVER's predicate and is never re-derived here.** It is false
 *   for a registered 140 or 160 header, and the POST refuses one
 *   (`sender_attestation_not_applicable`). A screen that decided for itself which numbers
 *   need the confirmation would eventually offer a control whose only outcome is a refusal.
 * - **`attested` is false when the stored row predates the current wording.** The client
 *   agreed to different words, so the answer is "ask again", not "error".
 * - **The withdrawal is a new row, never a deletion** (hard rule 4). `DELETE` is the verb
 *   the route spells; what it records is a change of mind, and no copy built on this may
 *   say the earlier confirmation is gone.
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

export type SenderAttestation = components["schemas"]["SenderAttestationOut"];

/** The refusal when the wording moved while the page was open. The remedy is a reload. */
export const STALE_STATEMENT_CODE = "sender_statement_not_current";

/** The act `rbac.VIEW_AS_WITHHELD_ACTS` withholds from a view-as operator. */
export const SENDER_ATTESTATION_ACT = "compliance.outbound_sender_attestation";

function path(numberId: string): string {
  return `/v1/numbers/${numberId}/sender-attestation`;
}

export function senderAttestationKey(org: string, numberId: string): readonly string[] {
  return ["sender-attestation", org, numberId] as const;
}

/** What this number's confirmation says today, and whether it is even needed. */
export function useSenderAttestation(
  session: Session,
  numberId: string,
): UseQueryResult<SenderAttestation> {
  return useQuery({
    queryKey: senderAttestationKey(session.orgSlug, numberId),
    queryFn: () => apiRequest<SenderAttestation>(session, path(numberId)),
  });
}

/**
 * Both writes, as one hook, because they are one decision in two directions and their
 * cache consequences are identical.
 *
 * The response of each is written into the query's own cache rather than only
 * invalidated: the panel's next paint is the answer to "did that land", and a refetch
 * round trip would show the previous state in between.
 *
 * The launch gate reads this fact too (`number_series_mismatch`), and a client who
 * confirms on this screen and then finds their campaign still refused would reasonably
 * conclude the confirmation did nothing — so every campaign's check is invalidated with
 * it. Broad rather than keyed by campaign: this number may be attached to any of them,
 * and this module cannot know which.
 */
export function useSetSenderAttestation(
  session: Session,
  numberId: string,
): UseMutationResult<SenderAttestation, Error, { withdraw: boolean; statementVersion: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ withdraw, statementVersion }) =>
      withdraw
        ? apiRequest<SenderAttestation>(session, path(numberId), { method: "DELETE" })
        : apiRequest<SenderAttestation>(session, path(numberId), {
            method: "POST",
            body: { statement_version: statementVersion },
          }),
    onSuccess: (state) => {
      client.setQueryData(senderAttestationKey(session.orgSlug, numberId), state);
      void client.invalidateQueries({ queryKey: ["campaign-check", session.orgSlug] });
    },
  });
}
