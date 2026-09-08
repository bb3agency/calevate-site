"use client";

/**
 * OPERATOR-ATTESTED TTS PRICES — the LLM attestation, one vendor further down the call.
 *
 * `apps/api/ops/model_pricing.py::TtsPriceAttestation` is the store: rupees per 1,000
 * CHARACTERS, effective-dated, append-only, attributed. This module is its console half and
 * it is deliberately the same shape as `opsModelPricing.ts` — one act, two vendors, so a
 * reader who knows one knows the other. It now also sits beside it: it was written in
 * `app/admin/ops/` because `src/lib/api/**` was not that lane's to touch, and with the hand
 * validator collapsed onto `TtsPriceOut` there is nothing page-shaped left in it.
 *
 * ## WHY AN UNATTESTED PRICE BLOCKS A VOICE RATHER THAN LOOKING EMPTY
 *
 * Hard rule 7 is structural here: a BYOK synthesizer leg is billed by the VENDOR, not by
 * the engine, so `CostBreakdown.tts_inr` reports ₹0 for it. Without an attested figure a
 * Cartesia minute would meter as FREE — a margin that looks wonderful and is not real. So
 * `tts_price_is_billable` is the one door, and `offerable_voices` refuses the tier by name
 * until it opens. The panel says exactly that: not "no price yet", but "this voice cannot
 * be sold until you type what your invoice says".
 *
 * Sarvam answers billable WITHOUT an attestation and that is not an exemption: the engine
 * bills us for the Sarvam synthesizer leg and reports what it charged, so that leg has a
 * measured cost on every row and there is no invoice division for a human to do.
 *
 * ## Money
 *
 * `inr_per_1k_chars` is an exact decimal STRING both ways and is never `Number()`d — the
 * plan's marginal rate is a division a human did against an invoice (₹4,312 ÷ 1.25M chars
 * = ₹3.4496 / 1,000), and four decimals of it survive to the DOM.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { adminSession } from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import { OPS_MODEL_PRICES_QUERY_KEY } from "@/lib/api/opsModelPricing";
import type { components } from "@/lib/api/schema";

/** `POST /v1/ops/tts-prices/{provider}` — a new dated row, never an overwrite. */
export const OPS_TTS_PRICES_PATH = "/v1/ops/tts-prices";

/**
 * One voice provider's price and what it gates — `TtsPriceOut`, generated.
 *
 * `provider` is the VENDOR's machine name (`sarvam` / `cartesia`, the spelling
 * `billing/lots.VoiceTier` and `agents/voices.VoiceProvider` share) and `tier_label` is what
 * a client calls that voice. Both are rendered, because this is the admin console: an
 * operator pasting a Cartesia key needs the vendor, and an operator on the phone to a client
 * needs the word the client is reading. `price_billable` is the one door — may a minute on
 * this voice be metered at a cost at all — and `offerable` is the whole rule,
 * `selectable AND credential_installed AND price_billable`.
 *
 * **THE LOCAL INTERFACE AND `asTtsPrice`/`ttsPricesOf` ARE GONE.** They stood in while this
 * shape was being added to `GET /v1/ops/model-prices` by the attestation lane, so that a
 * missing `price_billable` could not default to `true` and tell an operator a voice is
 * sellable when every minute on it meters as free. `ModelPricesOut.tts_prices` is generated
 * and REQUIRED, and every field on the row with it, so the hand validator now re-checks
 * only what the compiler proves — and the weaker spelling of a wire contract is the one
 * that drifts. The panel reads `prices.tts_prices` off the typed payload it already has.
 */
export type TtsPrice = components["schemas"]["TtsPriceOut"];

/** What the attestation answers with: the row it appended, and the voices it just moved. */
export type TtsPriceWrite = components["schemas"]["TtsPriceWriteOut"];

/**
 * The step-up string, copied VERBATIM from the route it is checked by, and bound to the
 * PROVIDER — a header captured for Sarvam cannot reprice Cartesia.
 */
export function attestTtsConfirmation(provider: string): string {
  return `attest_tts_price:${provider}`;
}

export interface AttestTtsInput {
  provider: string;
  /** Rupees per 1,000 characters, as the exact string the operator typed. Never a number. */
  inrPer1kChars: string;
  sourceNote: string;
  effectiveFrom?: string;
}

export function useAttestTtsPrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, inrPer1kChars, sourceNote, effectiveFrom }: AttestTtsInput) =>
      apiRequest<TtsPriceWrite>(adminSession(), `${OPS_TTS_PRICES_PATH}/${provider}`, {
        method: "POST",
        body: {
          inr_per_1k_chars: inrPer1kChars,
          source_note: sourceNote,
          ...(effectiveFrom ? { effective_from: effectiveFrom } : {}),
        },
        confirmAction: attestTtsConfirmation(provider),
      }),
    // The whole list, for `useAttestModelPrice`'s reason: an attestation changes a voice's
    // offerability and the instant the rest of the page was resolved at.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MODEL_PRICES_QUERY_KEY }),
  });
}
