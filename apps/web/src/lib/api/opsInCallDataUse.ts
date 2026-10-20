"use client";

/**
 * The operator's data-use attestation for RAW CALLER SPEECH on our own model — the admin
 * realm's view of `/v1/ops/in-call-data-use` (D-839). Its own statement and step-up, separate
 * from the dashboard attestation (`opsDashboardDataUse.ts`): own-model readiness reads this
 * one (`apps/api/ops/in_call_data_use_routes.py`).
 */

import { livePoll } from "@/lib/live/liveStatus";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { AttestDataUseInput } from "./opsDashboardDataUse";
import { hostedVoiceKeys } from "./opsHostedVoices";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_IN_CALL_DATA_USE_PATH = "/v1/ops/in-call-data-use";
export const OPS_IN_CALL_DATA_USE_QUERY_KEY = ["admin", "ops", "in-call-data-use"] as const;

export type InCallDataUse = Schemas["InCallDataUseOut"];
export type InCallDataUseList = Schemas["InCallDataUseListOut"];
type InCallDataUseWrite = Schemas["InCallDataUseWriteOut"];

/** `apps/api/ops/in_call_data_use_routes.py::attest_confirmation`, verbatim. */
export function inCallAttestConfirmation(provider: string): string {
  return `attest_in_call_data_use:${provider}`;
}

export function useInCallDataUse(): UseQueryResult<InCallDataUseList> {
  return useQuery({
    queryKey: OPS_IN_CALL_DATA_USE_QUERY_KEY,
    queryFn: () => apiRequest<InCallDataUseList>(adminSession(), OPS_IN_CALL_DATA_USE_PATH),
    refetchInterval: livePoll(60_000),
  });
}

export function useAttestInCallDataUse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      provider,
      vendorAccountRef,
      paidTierConfirmed,
      noTrainingOptInConfirmed,
      sourceNote,
    }: AttestDataUseInput) =>
      apiRequest<InCallDataUseWrite>(adminSession(), `${OPS_IN_CALL_DATA_USE_PATH}/${provider}`, {
        method: "POST",
        body: {
          vendor_account_ref: vendorAccountRef,
          paid_tier_confirmed: paidTierConfirmed,
          no_training_opt_in_confirmed: noTrainingOptInConfirmed,
          source_note: sourceNote,
        },
        confirmAction: inCallAttestConfirmation(provider),
      }),
    // The own-model card's checklist reads this attestation, so it re-reads too.
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: OPS_IN_CALL_DATA_USE_QUERY_KEY });
      void client.invalidateQueries({ queryKey: hostedVoiceKeys.ownModel });
    },
  });
}
