/**
 * OPERATOR-ATTESTED PER-MINUTE RATES for an engine that reports no call cost (D-678).
 *
 *   GET  /v1/ops/engine-minute-prices                       `platform:config`
 *   POST /v1/ops/engine-minute-prices/{engine}/{rate_key}   step-up confirmed
 *
 * ThinnestAI returns no cost for a call, so a minute on it is metered only at a rate an
 * operator typed here (hard rule 7): the posted rate, before the wallet top-up fee, which the
 * meter adds (`topup_fee_percent`; `inr_per_min_with_fee` is the figure metered). `platform` is the base
 * minute; `standard` / `premium` / `studio` are the voice bands it bills separately. Until a
 * key is attested its minutes are not sold and its voices show as unavailable.
 *
 * `inr_per_min` is an exact decimal STRING both ways and is never turned into a number.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { OPS_RATE_CARD_QUERY_KEY } from "./opsRateCard";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type EngineMinutePrice = components["schemas"]["EngineMinutePriceOut"];
export type EngineMinutePrices = components["schemas"]["EngineMinutePricesOut"];

export const ENGINE_MINUTE_PRICES_PATH = "/v1/ops/engine-minute-prices";
const QUERY_KEY = ["ops", "engine-minute-prices"] as const;

/** The step-up string, copied verbatim from the route that checks it. */
export function attestEngineMinuteConfirmation(engine: string, rateKey: string): string {
  return `attest_engine_minute_price:${engine}:${rateKey}`;
}

export function useEngineMinutePrices() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiRequest<EngineMinutePrices>(adminSession(), ENGINE_MINUTE_PRICES_PATH),
  });
}

export interface AttestEngineMinuteInput {
  engine: string;
  rateKey: string;
  /** Rupees per billed minute, exactly as typed. Never a number. */
  inrPerMin: string;
  sourceNote: string;
}

export function useAttestEngineMinutePrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ engine, rateKey, inrPerMin, sourceNote }: AttestEngineMinuteInput) =>
      apiRequest<EngineMinutePrice>(
        adminSession(),
        `${ENGINE_MINUTE_PRICES_PATH}/${engine}/${rateKey}`,
        {
          method: "POST",
          body: { inr_per_min: inrPerMin, source_note: sourceNote },
          confirmAction: attestEngineMinuteConfirmation(engine, rateKey),
        },
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: QUERY_KEY });
      // An attested band changes which of the platform's voices can be used.
      void client.invalidateQueries({ queryKey: ["engine-catalogue"] });
    },
  });
}

/**
 * THE COST INPUTS BESIDE THE MINUTE (D-840): the wallet top-up fee and the payment gateway's
 * fee on a client's top-up, typed in PERCENT, and the monthly rent of a number rented in the
 * voice platform's console, in rupees. Each recording is a new dated row.
 *
 *   POST /v1/ops/cost-attestations/{subject}   step-up `attest_cost:<subject>`
 */
export type CostAttestation = components["schemas"]["CostAttestationOut"];

export const COST_ATTESTATIONS_PATH = "/v1/ops/cost-attestations";

/** The step-up string, copied verbatim from the route that checks it. */
export function attestCostConfirmation(subject: string): string {
  return `attest_cost:${subject}`;
}

export interface AttestCostInput {
  subject: string;
  /** A fee in percent ("2.36") or a rent in rupees ("349.00"), exactly as typed. */
  value: string;
  sourceNote: string;
}

export function useAttestCost() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ subject, value, sourceNote }: AttestCostInput) =>
      apiRequest<CostAttestation>(adminSession(), `${COST_ATTESTATIONS_PATH}/${subject}`, {
        method: "POST",
        body: { value, source_note: sourceNote },
        confirmAction: attestCostConfirmation(subject),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: QUERY_KEY });
      // The gateway fee moves every cost floor on the rate card.
      void client.invalidateQueries({ queryKey: OPS_RATE_CARD_QUERY_KEY });
    },
  });
}
