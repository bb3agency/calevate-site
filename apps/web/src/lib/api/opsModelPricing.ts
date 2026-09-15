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

/* ── ENCODERS: the price that decides whether an upload is embedded at all (D-608) ──
 *
 * The same panel, the same act and the same money rule as everything above — with ONE
 * FIELD REMOVED. An embedding request returns a vector, so the vendor bills no output
 * tokens and there is nothing for an operator to type in a second box. That absence is
 * carried in the TYPES (`AttestEmbeddingPriceInput` has no output field) rather than in a
 * comment, because a nullable field on a form is a field somebody eventually fills in.
 *
 * ITS OWN PATH, because an encoder identifier contains a SLASH (`models/gemini-embedding-2`
 * — the string Google's OpenAI-compatibility surface lists, the string the wire takes and
 * the string the ledger records). It is interpolated RAW, never `encodeURIComponent`d: the
 * server's route takes a `:path` parameter precisely so that no `%2F` — which proxies
 * normalise or refuse — ever appears in the URL.
 */

export const OPS_EMBEDDING_PRICES_PATH = "/v1/ops/embedding-prices";

/** One encoder: what it is for, how wide its vectors are, and its attested INPUT price. */
export type EmbeddingPrice = Schemas["EmbeddingPriceOut"];

/** The answer to an encoder attestation: the row as it now stands. */
export type EmbeddingPriceWrite = Schemas["EmbeddingPriceWriteOut"];

/**
 * The step-up string for attesting ONE encoder's price, copied VERBATIM from
 * `apps/api/ops/model_price_routes.py::embedding_attest_confirmation`. Its own prefix, so
 * a header captured while pricing a chat model cannot be replayed against the encoder that
 * decides how every published knowledge pack is built.
 */
export function embeddingAttestConfirmation(model: string): string {
  return `attest_embedding_price:${model}`;
}

export interface AttestEmbeddingPriceInput {
  model: string;
  /** USD per MILLION **INPUT** tokens, as the exact string the operator typed. */
  inputUsdPerMtok: string;
  sourceNote: string;
  /** ISO instant with an offset, or omitted for "from now on". */
  effectiveFrom?: string;
}

export function useAttestEmbeddingPrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ model, inputUsdPerMtok, sourceNote, effectiveFrom }: AttestEmbeddingPriceInput) =>
      apiRequest<EmbeddingPriceWrite>(adminSession(), `${OPS_EMBEDDING_PRICES_PATH}/${model}`, {
        method: "POST",
        body: {
          input_usd_per_mtok: inputUsdPerMtok,
          source_note: sourceNote,
          ...(effectiveFrom ? { effective_from: effectiveFrom } : {}),
        },
        confirmAction: embeddingAttestConfirmation(model),
      }),
    // The whole list, for the chat attestation's reason: an encoder price changes that
    // row's `usable` and the response's `as_of`, and a spliced row would sit in a stale page.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_MODEL_PRICES_QUERY_KEY }),
  });
}
