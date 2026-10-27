"use client";

/**
 * How long callers waited for an answer, across every client — `GET /v1/ops/reply-times`
 * (D-770). The figures are the voice platform's own per-call times to the first word of the
 * actual answer, with the first sound of any kind beside them, and the per-turn split of the
 * wait by turn detection (D-902, `apps/api/ops/reply_times.py`); every percentile, count and
 * the target arrive as server fields, so nothing here computes a statistic. Milliseconds are
 * JSON numbers, not money, so rounding them for display is fine (hard rule 7 is about rupees).
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
export type TurnSplit = Schemas["TurnSplit"];
export type AgentTurnSplit = Schemas["AgentTurnSplit"];
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

/** What the waits on the screen measure, said once where a reader meets the figures. */
export const ANSWER_NOTE =
  "A wait for an answer runs from the caller stopping to the first word of the actual answer. " +
  "A filler line such as “one moment” does not end it; the first sound, which it does end, is " +
  "shown beside it. Calls from before 27 Oct 2026 have no answer time.";

/** The steps of a turn's wait (`TurnSplit`), in the order they happen, with their gloss. */
export const SPLIT_STEPS: readonly {
  key: keyof Pick<
    TurnSplit,
    | "wait_before_decision_ms"
    | "recogniser_ms"
    | "ear_check_ms"
    | "model_asked_ms"
    | "model_first_sentence_ms"
    | "voice_ms"
  >;
  label: string;
  gloss: string;
}[] = [
  {
    key: "wait_before_decision_ms",
    label: "Wait before decision",
    gloss: "Caller stopped to the turn being decided: the recogniser, the final words and the Ear check together.",
  },
  { key: "recogniser_ms", label: "Recogniser", gloss: "Caller stopped to their final words arriving." },
  {
    key: "ear_check_ms",
    label: "Ear check",
    gloss: "Final words arriving to Ear's verdict that the turn was over. Blank off Ear.",
  },
  {
    key: "model_asked_ms",
    label: "Model asked",
    gloss: "When the model was asked, from the caller stopping. Below zero with early answers: asked before the turn was decided.",
  },
  {
    key: "model_first_sentence_ms",
    label: "Model's first sentence",
    gloss: "The model being asked to the first words of the answer leaving it. A filler does not count.",
  },
  {
    key: "voice_ms",
    label: "Voice",
    gloss: "The answer's first words leaving the model to being heard, including any wait behind a filler still speaking.",
  },
];

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
    message: "Calls finished in this window, but the voice platform sent no reply times for any of them",    hint: "It measures only connected calls and can send its figures a little after a call ends. If this persists, the platform is not reporting call quality.",
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

