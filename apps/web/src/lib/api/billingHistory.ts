"use client";

/**
 * A client's money over time (D-660): the monthly statement list and the daily spend series.
 *
 * - `GET /v1/billing/statements?limit=&before=` — one row per IST month since the account
 *   opened, newest first. `month` is the key: the full statement is
 *   `useClientInvoice(session, month)` in `./invoice`.
 * - `GET /v1/billing/spend/daily?days=` or `?from=&to=` — what left the prepaid wallet each
 *   IST day, with explicit zero days.
 *
 * Both are `billing:read` (owners, not staff), like the invoice and spend reads — check the
 * permission before calling so a staff screen meets a sentence rather than a 403.
 *
 * Every rupee is an exact decimal STRING (hard rule 7's frontend shadow). The server
 * publishes the totals beside the parts, and each column of `days` sums EXACTLY to the
 * total of the same name, so a chart never adds rupee strings: it reads `spent_inr` for the
 * window's figure and plots `days[].spent_inr`. For plotting, convert per point with
 * `Number()` only into the chart's geometry, never into a figure a reader sees.
 */

import { useInfiniteQuery, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type StatementList = Schemas["StatementListOut"];
export type StatementSummary = Schemas["StatementSummaryOut"];
export type SpendSeries = Schemas["SpendSeriesOut"];
export type SpendDay = Schemas["SpendDayOut"];
export type AgentDailySpend = Schemas["AgentDailySpendOut"];

/** The window lengths the server accepts for `days`. */
export type SpendWindowDays = 7 | 30 | 90;

/** Either a preset length ending today (IST), or an inclusive IST date range (max 92 days). */
export type SpendWindow = { days: SpendWindowDays } | { from: string; to: string };

/** The server's ceilings, mirrored for the controls that choose a window or a page size. */
export const MAX_SPEND_SERIES_DAYS = 92;
export const MAX_STATEMENTS_PER_PAGE = 12;

export const billingHistoryKeys = {
  statements: (org: string, limit: number) => ["billing-statements", org, limit] as const,
  spendSeries: (org: string, window: SpendWindow) =>
    ["billing-spend-series", org, "days" in window ? `d${window.days}` : `${window.from}..${window.to}`] as const,
};

export function spendSeriesPath(window: SpendWindow): string {
  const query =
    "days" in window
      ? `days=${window.days}`
      : `from=${encodeURIComponent(window.from)}&to=${encodeURIComponent(window.to)}`;
  return `/v1/billing/spend/daily?${query}`;
}

export function statementsPath(limit: number, before?: string | null): string {
  const cursor = before ? `&before=${encodeURIComponent(before)}` : "";
  return `/v1/billing/statements?limit=${limit}${cursor}`;
}

/**
 * The monthly statements, newest first, a page at a time.
 *
 * `data.pages` holds each `StatementList`; `fetchNextPage()` follows `next_before` and
 * `hasNextPage` is false once the page reaching the account's opening month has arrived.
 * Each row builds a whole statement on the server, so keep `limit` small (default 6, at
 * most `MAX_STATEMENTS_PER_PAGE`).
 */
export function useStatements(
  session: Session,
  options: { limit?: number; enabled?: boolean } = {},
) {
  const limit = Math.min(options.limit ?? 6, MAX_STATEMENTS_PER_PAGE);
  return useInfiniteQuery({
    queryKey: billingHistoryKeys.statements(session.orgSlug, limit),
    queryFn: ({ pageParam }) =>
      apiRequest<StatementList>(session, statementsPath(limit, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last: StatementList) => last.next_before,
    enabled: options.enabled ?? true,
  });
}

/** Daily wallet spend over a window. Defaults to the last 30 days. */
export function useSpendSeries(
  session: Session,
  window: SpendWindow = { days: 30 },
  options: { enabled?: boolean } = {},
): UseQueryResult<SpendSeries> {
  return useQuery({
    queryKey: billingHistoryKeys.spendSeries(session.orgSlug, window),
    queryFn: () => apiRequest<SpendSeries>(session, spendSeriesPath(window)),
    enabled: options.enabled ?? true,
  });
}
