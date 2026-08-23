"use client";

/**
 * WHAT THE VOICE ENGINE REPORTED ITS OWN PIPELINE COST, BY REGION — `GET /v1/ops/engine-latency`.
 *
 * The read side of OPERATIONS §2 gate 4 and the first thing
 * `runbooks/alarm-index.md::engine_llm_ttft_degraded` tells an operator to open. It landed
 * with no path in the console at all, so both documents pointed at a curl — the exact
 * shape `app/admin/ops/page.tsx` exists to have removed for the load-shed switch, the
 * outbox replay and the audit-chain verification.
 *
 * ## THREE THINGS THIS MODULE REFUSES TO COMPUTE
 *
 * 1. **A percentile.** `apps/api/ops/engine_latency.py` withholds a p95 below 20 timed
 *    turns and a p50 below 5, and publishes `basis` on every group so the withholding is a
 *    FIELD rather than a footnote. A browser that filled either in from `llm_ttft_max_ms`
 *    would be printing the largest sample wearing a percentile's name, which is the one
 *    thing that module's docstring says it will not do.
 * 2. **Whether a group missed the budget.** `budget_breached` is the server's answer, and
 *    it is about the MEDIAN turn rather than the worst one. `null` means the sample cannot
 *    support a median — a third state, and "we do not know" must never render the same as
 *    "within budget".
 * 3. **Gate 4's own verdict.** The gate needs a median from TWO regions to compare, and
 *    `EngineLatencyReport.regions_measured` is the rule that counts them — a Python
 *    `@property`, so it is not on the wire and nothing reads it. Restating it here would be
 *    a second spelling of a rule that already exists, in the place least able to defend it.
 *    The screen prints the per-group `basis` the server DOES send and lets the reader
 *    compare two rows; see the report for what a backend lane would have to publish for the
 *    console to state the verdict itself.
 *
 * ## MILLISECONDS ARE NUMBERS, AND THAT IS NOT A HARD-RULE-7 EXCEPTION
 *
 * Hard rule 7 is about MONEY — a rupee amount is `Decimal` end to end and is never parsed
 * (`lib/llmRates.ts`, `formatINR`). Nothing on this surface is money: these are `float8`
 * timings the engine measured, the API sends them as JSON numbers, and rounding one to the
 * nearest millisecond for display loses nothing a reader could act on. Said out loud
 * because every other numeric formatter in this console is deliberately string-only, and
 * the next reader is entitled to know which rule this is under.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The whole report: every (engine, region) group, plus the target each is judged against. */
export type EngineLatencyReport = Schemas["EngineLatencyReport"];

/** One (engine, region) pair's LLM time-to-first-token distribution. */
export type LatencyGroup = Schemas["LatencyGroup"];

export const ENGINE_LATENCY_PATH = "/v1/ops/engine-latency";

/**
 * The windows offered, and why these four.
 *
 * `DEFAULT_WINDOW_DAYS = 7` and `MAX_WINDOW_DAYS = 90` are the server's own bounds
 * (`apps/api/ops/engine_latency.py`) and the route rejects anything outside them, so the
 * chips can only ask for what the API will answer. One day is here because a gate-4 run is
 * two pilot calls placed minutes apart and a week of fleet traffic would bury them; ninety
 * is the ceiling itself, offered so an operator does not have to discover it by being
 * refused.
 */
export const DEFAULT_WINDOW_DAYS = 7;
export const MAX_WINDOW_DAYS = 90;
export const WINDOW_CHOICES: readonly number[] = [1, 7, 30, MAX_WINDOW_DAYS];

/**
 * NOT org-scoped, and `tests/queryKeys.test.ts` checks that it is not: the `queryFn` mints
 * an `adminSession()`, which belongs to no tenant — this report walks every account and
 * groups the result by geography, so a slug in the key would claim a tenancy the data does
 * not have. The window IS in the key, because two windows are two different answers.
 */
export const engineLatencyKeys = {
  report: (days: number) => ["admin", "ops", "engine-latency", days] as const,
};

/**
 * The report for one window.
 *
 * NO POLL. The server walks every tenant's own RLS session to assemble this
 * (`WALK_BUDGET_S` exists because that cost grows with the client list), and the subject
 * is a distribution over days — nothing on it changes inside a minute. An operator
 * watching a pilot call land refetches by re-picking the window, which is the same
 * judgement `useClientHealth` makes about a seven-day board and the opposite of the one
 * `useHeldTenants` makes about a shared queue.
 *
 * `enabled` exists for ONE caller and one state: the screen has established that this
 * admin session does NOT hold `ops:manage`, so the request can only come back 403. It is
 * spelled at the call site as `!access.refused` rather than `access.allowed` — the query
 * runs while the identity read is unknown, because `app/admin/access.ts`'s rule is that
 * navigation fails open and the API is the enforcement. Same shape and same argument as
 * `useOrganizationLlmDefaults(session, enabled)` and `useArchivedAgents(session, enabled)`.
 */
export function useEngineLatency(
  days: number,
  enabled = true,
): UseQueryResult<EngineLatencyReport> {
  return useQuery({
    queryKey: engineLatencyKeys.report(days),
    queryFn: () =>
      apiRequest<EngineLatencyReport>(adminSession(), `${ENGINE_LATENCY_PATH}?days=${days}`),
    enabled,
  });
}

/**
 * What a region CODE means, in words — read through `lookup`, never indexed directly.
 *
 * The codes are the vendor's (`bolna-findings/mirror/pages/concepts/call-latencies.md:38`
 * documents `in` for India and `us` for United States) and the adapter stores whatever
 * short identifier arrives, lower-cased, refusing anything that is not one
 * (`apps/api/engine/bolna.py::_REGION_CODE_RE`). So the set is OPEN: a vendor that starts
 * stamping `ap-south-1` produces a row this table cannot name, and the screen prints the
 * bare code rather than dropping the row or guessing at a country. `lib/agentState.ts`
 * argues the same fallback direction for the same class of bare wire string.
 */
export const REGION_NAMES: Record<string, string> = {
  in: "India",
  us: "United States",
};

/**
 * WHY THE ENGINE DID NOT SAY WHERE IT RAN — the `region: null` row, which is not an error.
 *
 * `parse_latency_data` keeps the field only when it looks like a region code and records a
 * warning otherwise, so a null here means the vendor sent nothing usable. The module calls
 * that "itself a finding": an unattributable measurement cannot answer the geography
 * question at all, which is the question this whole endpoint was built for.
 */
export const UNREPORTED_REGION_LABEL = "Region not reported";

/**
 * The region column's text: the country when we can name it, else the bare code.
 *
 * `lookup` rather than `REGION_NAMES[region]`, because the key is a wire string and the
 * table is an object literal — the prototype-chain read `lib/lookup.ts` exists to make
 * unrepeatable, and `tests/wireLookupGuard.test.ts` fails on the direct spelling.
 */
export function regionLabel(region: string | null): string {
  if (region === null) return UNREPORTED_REGION_LABEL;
  const named = lookup(REGION_NAMES, region);
  return named === undefined ? region : `${named} (${region})`;
}

/**
 * A timing, in whole milliseconds, or `—` when the server withheld it.
 *
 * `—` and never a zero: an absent percentile is the server declining to make a claim the
 * sample cannot support, and `0 ms` would be the fastest number on the screen sitting
 * where the honest answer is "not enough turns". `undefined` and `null` both reach here —
 * the generated type makes these properties optional AND nullable, because the API omits
 * them rather than sending nulls on a group that has no median.
 */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${Math.round(value).toLocaleString("en-IN")} ms`;
}

/** What a group's median says about the budget — the server's verdict, in three states. */
export type BudgetVerdict = "within" | "over" | "unknown";

/**
 * `budget_breached`, read as the three states it actually has.
 *
 * A function rather than a ternary at the call site so `undefined` is handled in ONE
 * place: the field is optional on the generated type (the API omits it on a group with no
 * median), and `!group.budget_breached` would report such a group as comfortably within a
 * budget nothing measured it against.
 */
export function budgetVerdict(group: LatencyGroup): BudgetVerdict {
  if (group.budget_breached === true) return "over";
  if (group.budget_breached === false) return "within";
  return "unknown";
}

/**
 * Why a group carries no percentiles — the server's `basis`, in the operator's words, or
 * `null` where there is nothing to explain.
 *
 * Keyed by the generated union, so a third basis added to `SummaryBasis` fails `tsc` here
 * rather than rendering an empty cell (`lib/lookup.ts` argues why the exhaustiveness is
 * worth keeping the table an object literal).
 *
 * **`measured: null` IS THE ENTRY, NOT A MISSING ONE.** A row whose figures are all
 * present needs no sentence saying so — printing "enough turns to state a median" beside
 * every healthy row is a column of noise that hides the rows that DO need reading. Making
 * that a `null` in the table rather than a `basis !== "measured"` test at the call site
 * keeps one rule in one place: the table decides which states have something to say, and
 * the screen renders whatever it is handed.
 */
export const BASIS_COPY: Record<LatencyGroup["basis"], string | null> = {
  measured: null,
  // NO THRESHOLD NUMBER IN THIS SENTENCE. `P50_MIN_TURNS` and `P95_MIN_TURNS` live in
  // `apps/api/ops/engine_latency.py` and are NOT on the wire, so a browser that printed
  // "fewer than five" would be a second copy of a constant nobody would re-derive when it
  // moved — D-105's defect, on the screen that decides whether a gate is closed. The
  // sentence says what the reader can act on instead, which is the same either way: place
  // more calls, or widen the window. Publishing the two thresholds on the report would let
  // this state them; see the lane report.
  insufficient_samples:
    "Too few timed turns to state a median — the worst turn beside it is a single observation, not an estimate.",
};
