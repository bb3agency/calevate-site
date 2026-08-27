"use client";

/**
 * The USD→INR rate the platform converts vendor costs at — the admin realm's view of
 * `GET /v1/ops/fx-rate`.
 *
 * ══ THIS MODULE COMPUTES NOTHING ════════════════════════════════════════════════════
 *
 * No arithmetic, no formatting of a rate, no staleness decision. Every one of those is
 * the server's, and the reasons are the ones stated at `aiQuota.ts:1-26`:
 *
 * - **it never decides whether the rate is stale.** `state` and `using_fallback` are the
 *   server's own words, computed against `core/fx.MAX_QUOTE_AGE` — the same constant the
 *   metering path applies. A browser that re-decided it would need the ceiling in the
 *   bundle, and a bundled threshold is wrong the day it changes.
 * - **it never says how old the rate is.** `age_label` arrives as a phrase. A clock in a
 *   browser is the viewer's clock, and the one number on this screen that must not be
 *   computed from a laptop's timezone is the age of the rate that money uses.
 * - **it never touches the rate as a number.** Rates cross the wire as decimal STRINGS
 *   and are rendered as they arrive. `Number("88.4275")` is a binary double, and this is
 *   the multiplier under every client's invoice (hard rule 7).
 *
 * ══ THERE IS NO WRITE HERE ══════════════════════════════════════════════════════════
 *
 * Deliberately, and `apps/api/ops/fx_routes.py` carries the argument: the pulled rate is
 * a machine observation with a source and a publication date, and a console that could
 * overwrite it would produce a number with the authority of a measurement and the
 * provenance of a guess. The operator's control is `USD_INR_RATE` in the config panel —
 * the declared FALLBACK, which is what money converts at whenever the pull has nothing
 * fresh.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export const OPS_FX_RATE_PATH = "/v1/ops/fx-rate";
export const OPS_FX_RATE_QUERY_KEY = ["admin", "ops", "fx-rate"] as const;

/** The rate in force, its age, its source, and the last pulls. All money is a STRING. */
export type FxRate = Schemas["FxRateOut"];

/** One pulled observation, as the history list renders it. */
export type FxObservation = Schemas["FxObservationOut"];

export function useFxRate(): UseQueryResult<FxRate> {
  return useQuery({
    queryKey: OPS_FX_RATE_QUERY_KEY,
    queryFn: () => apiRequest<FxRate>(adminSession(), OPS_FX_RATE_PATH),
    // The pull runs every five minutes and the underlying reference rate publishes once a
    // business day, so a faster poll would re-render the same number. Two minutes means an
    // operator watching this screen during an incident sees a recovered feed without
    // reaching for reload, and nothing more often than that is information.
    refetchInterval: 120_000,
  });
}
