"use client";

/**
 * EVERY ALARM THIS PLATFORM HAS RAISED — `GET /v1/ops/alerts`, the read side of D-591.
 *
 * The founder's inbox was the alert console, and it could not answer the only question
 * anybody asks of one: *is anything actually broken right now*. An inbox sorts by arrival,
 * so a `page` from 03:12 sits under forty `record` rows from 03:14. Their instruction was
 * "failures in admin panel only, high priority things only through mail"; the mail half is
 * `apps/api/core/alarm_severity.py`, and this is the panel half.
 *
 * ## WHAT THIS MODULE REFUSES TO COMPUTE, and it is the same doctrine as `engineLatency.ts`
 *
 * 1. **Whether an episode is OPEN.** `cleared_at` is the server's field and `null` is the
 *    answer; a browser deciding "last seen more than an hour ago, so it must be over"
 *    would be a second implementation of `ALERT_CLEAR_AFTER_S` that drifts the first time
 *    somebody tunes it — and would paint an open incident as finished.
 * 2. **Whether an episode was MAILED.** `emailed` is what the transport said, not what
 *    the severity implies. A `page` whose SMTP failed twice is `severity: "page"` with
 *    `emailed: false`, and it is the single most important row on the screen. Deriving the
 *    column from the severity would paint exactly that row green.
 * 3. **The open counts.** `open_by_severity` and `open_unmailed_pages` are computed over
 *    the WHOLE table server-side, not over the page that happened to load — "is anything
 *    broken" may not have an answer that depends on the row limit.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** The window, the rows, and the counts that answer the question. */
export type AlertReport = Schemas["AlertReport"];

/** One episode of one alarm: its code, when it started, how often, whether it mailed. */
export type AlertEpisode = Schemas["AlertEpisode"];

/** `page` | `attention` | `record` — `apps/api/core/alarm_severity.py`. */
export type AlertSeverity = AlertEpisode["severity"];

export const ALERTS_PATH = "/v1/ops/alerts";

/**
 * The server's own bounds (`apps/api/ops/alerts_service.py`), so a chip can only ask for
 * what the route will answer. One day is "tonight"; ninety is the ceiling itself, offered
 * rather than left to be discovered by a 422.
 */
export const DEFAULT_WINDOW_DAYS = 7;
export const MAX_WINDOW_DAYS = 90;
export const WINDOW_CHOICES: readonly number[] = [1, 7, 30, MAX_WINDOW_DAYS];

/**
 * NOT org-scoped, and `tests/queryKeys.test.ts` checks that it is not: `platform_alerts`
 * carries no `tenant_id` at all, so a slug in the key would claim a tenancy the data does
 * not have. The window and the severity filter ARE in it, because each is a different
 * answer.
 */
export const alertKeys = {
  report: (days: number) => ["admin", "ops", "alerts", days] as const,
};

/**
 * The report for one window.
 *
 * **IT POLLS, unlike `useEngineLatency`, and the difference is the subject.** That report
 * is a distribution over days that cannot change inside a minute; this one is "what is
 * happening now", opened by somebody who has just been paged and is watching for the next
 * occurrence — the same judgement `useClientHealth` makes the other way round. Sixty
 * seconds: the alerting path's own recording cadence is fifteen minutes
 * (`ALERT_REPEAT_INTERVAL_S`), so a faster poll would only re-fetch the same rows, and a
 * slower one would leave a fresh alarm off the screen for longer than a person will wait
 * before reloading by hand.
 *
 * `enabled` is spelled `!access.refused` at the call site, never `access.allowed` — see
 * `app/admin/access.ts`: navigation fails open and the API is the enforcement, so the read
 * runs while the identity answer is unknown and is withheld only on a definite refusal.
 */
export const ALERTS_POLL_MS = 60_000;

export function useAlerts(days: number, enabled = true): UseQueryResult<AlertReport> {
  return useQuery({
    queryKey: alertKeys.report(days),
    queryFn: () => apiRequest<AlertReport>(adminSession(), `${ALERTS_PATH}?days=${days}`),
    enabled,
    refetchInterval: enabled ? ALERTS_POLL_MS : false,
  });
}

/**
 * What each severity MEANS to the person reading the screen, in the operator's words.
 *
 * Deliberately phrased as where it went and what it asks of them, not as how bad it
 * sounds: a label nobody can act on differently is decoration. These mirror
 * `apps/api/core/alarm_severity.py`'s own three paragraphs and `runbooks/alarm-index.md`'s
 * table, and they are the only place the console says them.
 */
export const SEVERITY_LABELS: Record<string, string> = {
  page: "Emailed",
  attention: "Needs a look",
  record: "Noted",
};

export const SEVERITY_MEANINGS: Record<string, string> = {
  page: "Loud enough to email. Money, a legal deadline, data at risk, or something down.",
  attention: "A real failure, bounded to one call, one client or one sweep. Look today.",
  record: "Expected, or somebody else's noise. Kept so you can see how often it happens.",
};

/**
 * The pill's colours. Read through `lookup` and never indexed directly — `severity` is a
 * wire string and the table is an object literal, which is the prototype-chain read
 * `lib/lookup.ts` exists to make unrepeatable (`tests/wireLookupGuard.test.ts`).
 */
export const SEVERITY_STYLES: Record<string, string> = {
  page: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200",
  attention: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  record: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
};

export function severityLabel(severity: string): string {
  return lookup(SEVERITY_LABELS, severity) ?? severity;
}

export function severityStyle(severity: string): string {
  return (
    lookup(SEVERITY_STYLES, severity) ??
    "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
  );
}

/**
 * The order the screen asks its question in: loudest first, so the eye lands on `page`.
 *
 * The SERVER already returns the rows in this order (open first, then severity, then
 * recency); this exists for the COUNT tiles, which are keyed by severity and would
 * otherwise render in whatever order the object happened to be built in — and alphabetical
 * would put "attention" above "page", which is the inbox's own failure on a screen.
 */
export const SEVERITY_ORDER: readonly AlertSeverity[] = ["page", "attention", "record"];

/**
 * How many episodes of each severity are open, in `SEVERITY_ORDER`, including the zeroes.
 *
 * ZEROES ARE KEPT ON PURPOSE. `open_by_severity` omits a severity with no open episodes,
 * and a tile that disappears when the number reaches zero is a tile a reader cannot learn
 * the position of — "nothing is broken" has to be something you can SEE, not the absence
 * of something you would have seen.
 */
export function openCounts(report: AlertReport): { severity: AlertSeverity; total: number }[] {
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    total: lookup(report.open_by_severity, severity) ?? 0,
  }));
}
