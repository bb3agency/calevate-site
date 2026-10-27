"use client";

/**
 * How long callers waited for the agent's first sound, across every client —
 * `GET /v1/ops/reply-times` (D-770). The figures are the voice platform's own per-call reply
 * times, which end at the first sound, so a filler line ends them and they are not the time to
 * the answer (D-901, `apps/api/ops/reply_times.py`); every percentile, count and the target
 * arrive as server fields, so nothing here computes a statistic. Milliseconds are JSON
 * numbers, not money, so rounding them for display is fine (hard rule 7 is about rupees).
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ReplyTimeReport = Schemas["ReplyTimeReport"];
export type ReplyTimeFigures = Schemas["ReplyTimeFigures"];
export type ClientReplyTimes = Schemas["ClientReplyTimes"];
export type AgentReplyTimes = Schemas["AgentReplyTimes"];
export type TierReplyTimes = Schemas["TierReplyTimes"];
export type DayReplyTimes = Schemas["DayReplyTimes"];
export type SlowCall = Schemas["SlowCall"];
export type SettingReplyTimes = Schemas["SettingReplyTimes"];
export type SettingKey = SettingReplyTimes["setting"];
export type EmptyReason = NonNullable<ReplyTimeReport["empty_reason"]>;
export type VoiceTierKey = TierReplyTimes["tier"];

export const REPLY_TIMES_PATH = "/v1/ops/reply-times";

/** The server's own bounds (`DEFAULT_WINDOW_DAYS`, `MAX_WINDOW_DAYS`); the route refuses others. */
export const DEFAULT_WINDOW_DAYS = 7;
export const MAX_WINDOW_DAYS = 90;
export const WINDOW_CHOICES: readonly number[] = [1, 7, 30, MAX_WINDOW_DAYS];

/** Not org-scoped: the report belongs to no tenant. The window is in the key. */
export const replyTimeKeys = {
  report: (days: number) => ["admin", "ops", "reply-times", days] as const,
};

/**
 * One window's report. No poll: the server reads every client's calls for it, and a
 * distribution over days does not move inside a minute. `enabled` is `!access.refused`.
 */
export function useReplyTimes(days: number, enabled = true): UseQueryResult<ReplyTimeReport> {
  return useQuery({
    queryKey: replyTimeKeys.report(days),
    queryFn: () =>
      apiRequest<ReplyTimeReport>(adminSession(), `${REPLY_TIMES_PATH}?days=${days}`),
    enabled,
  });
}

/** What every wait on the screen measures, said once where a reader meets the figures. */
export const FIRST_SOUND_NOTE =
  "Each wait runs from the caller stopping to the agent's first sound. A filler line such as " +
  "“one moment” is a first sound, so a slow answer covered by one counts only up to the filler.";

/** Whole milliseconds, or `—` when the server withheld or the platform did not report it. */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${Math.round(value).toLocaleString("en-IN")} ms`;
}

/** Keyed by the generated union, so a new rung fails `tsc` here. */
export const TIER_LABELS: Record<VoiceTierKey, string> = {
  clear: "Clear",
  studio: "Studio",
  not_metered: "Not billed yet",
};

/**
 * The call-handling settings the report splits by (D-896), keyed by the generated union so a
 * new setting fails `tsc` here. Each call carries the settings its agent was published with.
 */
export const SETTING_LABELS: Record<SettingKey, string> = {
  turn_detection: "Turn detection",
  known_facts: "Facts known by heart",
  known_facts_size: "Size of facts known by heart",
  filler_delay_ms: "Filler after (ms)",
  early_answers: "Early answers",
  turn_silence_ms: "End-of-turn pause (ms)",
};

/** The server's closed-set values in words; anything else (a number) is shown as sent. */
const SETTING_VALUE_LABELS: Record<string, string> = {
  not_recorded: "Not recorded",
  on: "On",
  off: "Off",
  timer: "Silence",
  ear: "Ear",
  smart: "Smart",
  none: "None",
  under_2000: "Under 2,000 characters",
  "2000_to_4000": "2,000 to 4,000 characters",
  "4000_plus": "4,000 characters or more",
};

export function settingValueLabel(value: string): string {
  return lookup(SETTING_VALUE_LABELS, value) ?? value;
}

/** Why a window has no figures, in words an operator can act on. */
export const EMPTY_COPY: Record<EmptyReason, { message: string; hint: string }> = {
  no_calls: {
    message: "No calls connected and finished in this window",
    hint: "Widen the window, or check the alerts screen if calls were expected.",
  },
  not_reported: {
    message: "Calls finished in this window, but the voice platform sent no reply times for any of them",
    hint: "It measures only connected calls and can send its figures a little after a call ends. If this persists, the platform is not reporting call quality.",
  },
};

/** "7 days", and "1 day" rather than "1 days". */
export function windowLabel(days: number): string {
  return `${days.toLocaleString("en-IN")} ${days === 1 ? "day" : "days"}`;
}

/** A calendar day the server already bucketed in IST, printed without shifting it again. */
export function formatDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

