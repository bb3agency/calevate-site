"use client";

/**
 * Operator-attested model prices — the admin realm's view of `/v1/ops/model-prices`
 * (PLATFORM-CONFIG §5).
 *
 * ══ MONEY IS A STRING, NEVER A NUMBER ═══════════════════════════════════════════════
 *
 * Every price on the wire is a decimal STRING (`"0.15"`), and this file never calls
 * `Number()` on one. A JSON float cannot hold a per-token price exactly, and a value that
 * reaches a browser as `0.15000000000000002` is one nobody can reconcile against an
 * invoice (hard rule 7 does not stop at the database). The attestation form takes the
 * operator's typed string and sends it through unchanged; the server validates it against
 * the same `Decimal` bounds the store enforces.
 *
 * ══ WHY A SEPARATE MUTATION SHAPE FROM CONFIG ═══════════════════════════════════════
 *
 * A price is not a `platform_settings` row: it is effective-dated and append-only, so a
 * write is a POST that appends a new attestation, never a conditional PUT over a revision.
 * There is therefore no `If-Match` here — a correction is a later attestation, not an
 * overwrite of an earlier one.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_MODEL_PRICES_PATH = "/v1/ops/model-prices";
export const OPS_MODEL_PRICES_QUERY_KEY = ["admin", "ops", "model-prices"] as const;

/** One catalogue model: its leg, its offerability, its attested price (or null), and the
 *  catalogue's own reference price. Money fields are STRINGS. */
export type ModelPrice = Schemas["ModelPriceOut"];

/** Every catalogue model, plus the instant the attested prices were resolved at. */
export type ModelPrices = Schemas["ModelPricesOut"];

/** The answer to an attestation: the model as it now stands. */
export type ModelPriceWrite = Schemas["ModelPriceWriteOut"];

/**
 * The step-up string for attesting ONE model's price, copied VERBATIM from
 * `apps/api/ops/model_price_routes.py` — like every other confirmation in this console, it
 * is a property of the request being sent and a mismatch is refused by the server rather
 * than assumed. Bound to the model, so a header captured for one model cannot reprice
 * another.
 */
export function attestConfirmation(model: string): string {
  return `attest_model_price:${model}`;
}

export function useModelPrices(): UseQueryResult<ModelPrices> {
  return useQuery({
    queryKey: OPS_MODEL_PRICES_QUERY_KEY,
    queryFn: () => apiRequest<ModelPrices>(adminSession(), OPS_MODEL_PRICES_PATH),
    // Slower than the ops screen's platform poll on purpose: a price is a deliberate act by
    // a person at a keyboard, not a state that drifts, and a tighter poll would clobber a
    // half-typed form more often than it would tell anyone anything.
    refetchInterval: 60_000,
  });
}

export interface AttestPriceInput {
  model: string;
  /** USD per MILLION input tokens, as the exact string the operator typed. Never a number. */
  inputUsdPerMtok: string;
  outputUsdPerMtok: string;
  sourceNote: string;
  /** ISO instant with an offset, or omitted for "from now on". */
  effectiveFrom?: string;
}

export function useAttestModelPrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ model, inputUsdPerMtok, outputUsdPerMtok, sourceNote, effectiveFrom }: AttestPriceInput) =>
      apiRequest<ModelPriceWrite>(adminSession(), `${OPS_MODEL_PRICES_PATH}/${model}`, {
        method: "POST",
        body: {
          input_usd_per_mtok: inputUsdPerMtok,
          output_usd_per_mtok: outputUsdPerMtok,
          source_note: sourceNote,
          ...(effectiveFrom ? { effective_from: effectiveFrom } : {}),
        },
        confirmAction: attestConfirmation(model),
      }),
    // Re-read the whole list: an attestation can change one model's offerability and the
    // `as_of` instant, and a console that spliced one row into a list it already held would
    // show a fresh price inside a stale page.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MODEL_PRICES_QUERY_KEY }),
  });
}
