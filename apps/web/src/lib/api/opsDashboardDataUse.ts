"use client";

/**
 * Operator-attested LLM data-use position for the dashboard assist — the admin realm's view
 * of `/v1/ops/dashboard-data-use` (D-477).
 *
 * ══ WHY AN ATTESTATION, NOT A CHECK ═════════════════════════════════════════════════
 *
 * Whether the in-app AI assistant MAY run on a client's chosen provider is a question about
 * that vendor's terms for OUR account, not about a model's merit or a credential being
 * present. Every Google-owned host is egress-blocked from this deployment, so no primary
 * source about any vendor's data-use position can be read from the server — the answer
 * arrives the way the LLM price already does: a person reads it in the vendor's console and
 * puts their name to it, with the account it is about captured so the claim can be re-checked
 * later rather than only re-made (`apps/api/ops/dashboard_data_use_routes.py`).
 *
 * ══ IT IS THREE FACTS, NOT A SIGNATURE ══════════════════════════════════════════════
 *
 * The write carries the vendor project/account the key belongs to, whether that project is on
 * the vendor's PAID tier, and whether anything on it opts submitted content back into the
 * vendor's free-tier data terms. A form that asked only the middle question would pass a
 * project that had opted its logs into training.
 *
 * ══ WHY A POST THAT APPENDS, NOT A PUT ══════════════════════════════════════════════
 *
 * An attestation is effective-dated and append-only: a correction is a LATER attestation,
 * never an overwrite of an earlier one, so what was believed at the time a client's content
 * reached a vendor stays answerable. There is therefore no `If-Match` here.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_DASHBOARD_DATA_USE_PATH = "/v1/ops/dashboard-data-use";
export const OPS_DASHBOARD_DATA_USE_QUERY_KEY = ["admin", "ops", "dashboard-data-use"] as const;

/** One declared LLM leg: its dashboard-assist eligibility, why it is blocked if it is, and the
 *  latest attestation (every attestation field `null` together when nobody has looked). */
export type DashboardDataUse = Schemas["DashboardDataUseOut"];

/** Every declared leg, plus the exact statement the operator is agreeing to. */
export type DashboardDataUseList = Schemas["DashboardDataUseListOut"];

/** The answer to an attestation: the leg as it now stands. */
export type DashboardDataUseWrite = Schemas["DashboardDataUseWriteOut"];

/**
 * The step-up string for attesting ONE provider's data-use position, copied VERBATIM from
 * `apps/api/ops/dashboard_data_use_routes.py::attest_confirmation` — like every other
 * confirmation in this console, it is a property of the request being sent and a mismatch is
 * refused by the server rather than assumed. Bound to the PROVIDER, so a header captured for
 * Google cannot be replayed against OpenAI.
 */
export function attestConfirmation(provider: string): string {
  return `attest_dashboard_data_use:${provider}`;
}

export function useDashboardDataUse(): UseQueryResult<DashboardDataUseList> {
  return useQuery({
    queryKey: OPS_DASHBOARD_DATA_USE_QUERY_KEY,
    queryFn: () =>
      apiRequest<DashboardDataUseList>(adminSession(), OPS_DASHBOARD_DATA_USE_PATH),
    // Slower than the incident screen's platform poll, like the model-prices read next door:
    // an attestation is a deliberate act by a person at a keyboard, not a state that drifts,
    // and a tighter poll would clobber a half-typed form more often than it would tell anyone
    // anything.
    refetchInterval: 60_000,
  });
}

export interface AttestDataUseInput {
  provider: string;
  /** The vendor project/account our key for this provider belongs to. Required — without it
   *  the claim can never be re-checked, only re-made. */
  vendorAccountRef: string;
  paidTierConfirmed: boolean;
  noTrainingOptInConfirmed: boolean;
  /** WHERE the operator looked, in their own words — the evidence recorded in the audit log. */
  sourceNote: string;
}

export function useAttestDashboardDataUse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      provider,
      vendorAccountRef,
      paidTierConfirmed,
      noTrainingOptInConfirmed,
      sourceNote,
    }: AttestDataUseInput) =>
      apiRequest<DashboardDataUseWrite>(
        adminSession(),
        `${OPS_DASHBOARD_DATA_USE_PATH}/${provider}`,
        {
          method: "POST",
          body: {
            vendor_account_ref: vendorAccountRef,
            paid_tier_confirmed: paidTierConfirmed,
            no_training_opt_in_confirmed: noTrainingOptInConfirmed,
            source_note: sourceNote,
          },
          confirmAction: attestConfirmation(provider),
        },
      ),
    // Re-read the whole list: an attestation can flip one leg's eligibility, and a console
    // that spliced one row into a list it already held would show a fresh attestation inside
    // a stale page.
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: OPS_DASHBOARD_DATA_USE_QUERY_KEY }),
  });
}
