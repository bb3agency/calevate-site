"use client";

/**
 * What a voice vendor billed us for one month, read off its invoice — the figure the spend
 * board's voice cost model sets against what our own meter attributed.
 *
 * `GET /v1/ops/tts-prices/plan-fees?month=` and `POST /v1/ops/tts-prices/{provider}/plan-fee`
 * (`apps/api/ops/model_price_routes.py`). A correction is a later attestation for the same
 * month, never an edit. The write needs `X-Confirm-Action: attest_tts_plan_fee:<provider>:<month>`,
 * bound to both so a header captured for one month cannot restate another.
 *
 * The fee is the whole month in rupees, as the exact string typed: never `Number()`d, because
 * the column is NUMERIC(12,2) and the server refuses a third decimal rather than rounding.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export const TTS_PLAN_FEES_PATH = "/v1/ops/tts-prices/plan-fees";

export type TtsPlanFees = Schemas["TtsPlanFeesOut"];
export type TtsPlanFeeSlot = Schemas["TtsPlanFeeSlotOut"];
export type TtsPlanFeeWrite = Schemas["TtsPlanFeeWriteOut"];

export function ttsPlanFeesQueryKey(month: string | null) {
  return ["ops", "tts-plan-fees", month ?? "current"] as const;
}

/** The step-up string, copied verbatim from `tts_plan_fee_confirmation` in the route module. */
export function ttsPlanFeeConfirmation(provider: string, month: string): string {
  return `attest_tts_plan_fee:${provider}:${month}`;
}

/** `null` asks for the server's current IST billing month, the one the spend board opens on. */
export function useTtsPlanFees(month: string | null): UseQueryResult<TtsPlanFees> {
  return useQuery({
    queryKey: ttsPlanFeesQueryKey(month),
    queryFn: () =>
      apiRequest<TtsPlanFees>(
        adminSession(),
        month ? `${TTS_PLAN_FEES_PATH}?${new URLSearchParams({ month })}` : TTS_PLAN_FEES_PATH,
      ),
  });
}

export interface AttestTtsPlanFeeInput {
  provider: string;
  month: string;
  /** Rupees for the whole month, as the exact string the operator typed. */
  planInr: string;
  sourceNote: string;
}

export function useAttestTtsPlanFee() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, month, planInr, sourceNote }: AttestTtsPlanFeeInput) =>
      apiRequest<TtsPlanFeeWrite>(
        adminSession(),
        `/v1/ops/tts-prices/${encodeURIComponent(provider)}/plan-fee`,
        {
          method: "POST",
          body: { month, plan_inr: planInr, source_note: sourceNote },
          confirmAction: ttsPlanFeeConfirmation(provider, month),
        },
      ),
    // Every month's read, because the panel may be showing the current month under the
    // `null` key while the write named it explicitly; and the fleet spend board, which
    // renders the fee (`lib/api/spend.ts`).
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["ops", "tts-plan-fees"] });
      void client.invalidateQueries({ queryKey: ["admin", "fleet-spend"] });
    },
  });
}
