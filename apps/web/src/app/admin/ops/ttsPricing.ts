"use client";

/**
 * OPERATOR-ATTESTED TTS PRICES — the LLM attestation, one vendor further down the call.
 *
 * `apps/api/ops/model_pricing.py::TtsPriceAttestation` is the store: rupees per 1,000
 * CHARACTERS, effective-dated, append-only, attributed. This module is its console half and
 * it is deliberately the same shape as `lib/api/opsModelPricing.ts` — one act, two vendors,
 * so a reader who knows one knows the other.
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

/** `POST /v1/ops/tts-prices/{provider}` — a new dated row, never an overwrite. */
export const OPS_TTS_PRICES_PATH = "/v1/ops/tts-prices";

/**
 * One voice provider's price and what it gates.
 *
 * `provider` is the VENDOR's machine name (`sarvam` / `cartesia`, the spelling
 * `billing/lots.VoiceTier` and `agents/voices.VoiceProvider` share) and `tier_label` is what
 * a client calls that voice. Both are rendered, because this is the admin console: an
 * operator pasting a Cartesia key needs the vendor, and an operator on the phone to a client
 * needs the word the client is reading.
 */
export interface TtsPrice {
  provider: string;
  tier_label: string;
  /** The synthesizer model this leg speaks with — `bulbul:v3`, `sonic-3.5`. */
  tts_model: string;
  credential_installed: boolean;
  price_attested: boolean;
  /** The one door: may a minute on this voice be metered at a cost at all? */
  price_billable: boolean;
  /** `selectable AND credential_installed AND price_billable`, the whole rule. */
  offerable: boolean;
  /** Why this leg needs no attestation, when it needs none. Null when it does need one. */
  billable_without_attestation_reason: string | null;
  inr_per_1k_chars: string | null;
  effective_from: string | null;
  attested_at: string | null;
  attested_by: string | null;
  source_note: string | null;
}

function str(value: unknown): value is string {
  return typeof value === "string";
}

/**
 * THE SEAM. A row that is not fully formed is dropped rather than defaulted.
 *
 * This shape is being added to `GET /v1/ops/model-prices` by the lane building the Cartesia
 * attestation, so nothing here trusts the generated type: a missing `price_billable`
 * defaulted to `true` would tell an operator a voice is sellable when every minute on it
 * meters as free. An absent or partial list renders as a stated absence in the panel.
 */
export function asTtsPrice(raw: unknown): TtsPrice | null {
  if (typeof raw !== "object" || raw === null) return null;
  const row = raw as Record<string, unknown>;
  if (!str(row.provider) || row.provider === "") return null;
  if (!str(row.tier_label) || !str(row.tts_model)) return null;
  for (const flag of ["credential_installed", "price_attested", "price_billable", "offerable"]) {
    if (typeof row[flag] !== "boolean") return null;
  }
  const optional = (value: unknown): string | null => (str(value) && value !== "" ? value : null);
  return {
    provider: row.provider,
    tier_label: row.tier_label,
    tts_model: row.tts_model,
    credential_installed: row.credential_installed as boolean,
    price_attested: row.price_attested as boolean,
    price_billable: row.price_billable as boolean,
    offerable: row.offerable as boolean,
    billable_without_attestation_reason: optional(row.billable_without_attestation_reason),
    inr_per_1k_chars: optional(row.inr_per_1k_chars),
    effective_from: optional(row.effective_from),
    attested_at: optional(row.attested_at),
    attested_by: optional(row.attested_by),
    source_note: optional(row.source_note),
  };
}

/** The `tts_prices` list off the model-prices payload, or `null` when this API has none. */
export function ttsPricesOf(payload: unknown): TtsPrice[] | null {
  if (typeof payload !== "object" || payload === null) return null;
  const list = (payload as Record<string, unknown>).tts_prices;
  if (!Array.isArray(list) || list.length === 0) return null;
  const rows = list.map(asTtsPrice);
  return rows.some((row) => row === null) ? null : (rows as TtsPrice[]);
}

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
      apiRequest<unknown>(adminSession(), `${OPS_TTS_PRICES_PATH}/${provider}`, {
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
