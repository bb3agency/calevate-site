"use client";

/**
 * The client's monthly QA report — `GET /v1/quality/reports` (`agents:read`).
 *
 * D-15's report has existed as `make qa-report` since M3 and SURFACES §2 asks for it
 * "rendered in-app, not just PDF". The API serves the numbers the harness computed,
 * stored per run; nothing is recomputed anywhere, including here. Three properties of
 * that payload the screen must honour rather than smooth over:
 *
 * - **An empty list means NO RUN, not a clean run.** There is no zeroed report and there
 *   must never be one: "no defects across 0 scenarios" is the single most misleading
 *   sentence this surface could produce.
 * - **`basis` travels with every measurement.** `too_few` means the count is honest and
 *   the percentage would not be, so the percentage is not shown — the rendering rule is
 *   `Measurement.rendered` on the SERVER's model, and this module reproduces none of it.
 *   `renderMeasurement` below exists only because the browser needs the same sentence;
 *   it is the one place it is spelled, and it is asserted against the API's own
 *   rendering in `tests/quality.test.tsx`.
 * - **`defects` is the headline, not the pass rate.** The pass rate measures our offline
 *   stand-in extractor; the defect count measures the promise we make. The screen leads
 *   with the second one for that reason.
 *
 * Types are the GENERATED ones. They matter more here than on most screens: this
 * document's whole claim is that the number a client reads is the number
 * `scripts/qa_report.summarize()` computed, and a hand-mirrored interface is a second
 * description of that shape which can drift without anything failing. Aliasing
 * `schema.d.ts` means the server model is the only description.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

// `Basis` is not emitted as a named schema — FastAPI inlines the Literal on each field —
// so it is derived from the field that carries it rather than re-declared. Deriving keeps
// the one description on the server side; re-declaring would be a second one.
export type Basis = Schemas["Measurement"]["basis"];
export type Measurement = Schemas["Measurement"];
export type ScenarioClassCount = Schemas["ScenarioClassCount"];
export type FieldLimit = Schemas["FieldLimit"];
export type QaReport = Schemas["QaReport"];

export const QUALITY_REPORTS_PATH = "/v1/quality/reports";

export function useQualityReports(session: Session): UseQueryResult<QaReport[]> {
  return useQuery({
    queryKey: ["quality", "reports", session.orgSlug],
    queryFn: () => apiRequest<QaReport[]>(session, QUALITY_REPORTS_PATH),
    // A monthly document. Polling it would be a load generator with nothing to find.
    staleTime: 5 * 60_000,
  });
}

/**
 * One measurement as a sentence — the browser's copy of `Measurement.rendered`.
 *
 * A percentage is printed ONLY on a `measured` basis. Below the floor the count stands
 * alone, because a percentage over a handful of scenarios moves by more than ten points
 * on one of them and is the number a client would quote back at us. This is the only
 * place in the console that turns a `Measurement` into text.
 */
export function renderMeasurement(measurement: Measurement): string {
  const { passed, total, basis } = measurement;
  if (basis !== "measured") return `${passed} of ${total}`;
  return `${passed} of ${total} (${Math.round((100 * passed) / total)}%)`;
}

/** Why a number is qualified — the client-facing sentence, matching the API's own. */
export const BASIS_NOTE: Record<Basis, string> = {
  measured: "",
  too_few:
    "Too few scenarios for a percentage to mean anything, so the count is shown instead.",
  no_baseline: "No previous report to compare against, so no trend is claimed this month.",
};
