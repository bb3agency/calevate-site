import type { CostPerResult, ReplySpeed, WeekSpeed } from "@/lib/api/proof";

export function weekSpeed(start: string, over: Partial<WeekSpeed> = {}): WeekSpeed {
  return {
    week_start: start,
    language: "all",
    calls: 0,
    answered: 0,
    answered_share: null,
    average_call_s: null,
    calls_measured: 0,
    reply_typical_ms: null,
    reply_slow_ms: null,
    ...over,
  };
}

/** `GET /v1/analytics/reply-speed?weeks=4` (D-944): three quiet weeks, then this week in
 *  Telugu and Hindi, the slow figure withheld (fewer than ten timed calls). */
export const REPLY_SPEED_FIXTURE: ReplySpeed = {
  typical_target_ms: 1600,
  slow_target_ms: 2200,
  p90_min_calls: 10,
  current_week_partial: true,
  weeks: [
    weekSpeed("2026-10-05"),
    weekSpeed("2026-10-12"),
    weekSpeed("2026-10-19"),
    weekSpeed("2026-10-26", {
      calls: 12,
      answered: 9,
      answered_share: 0.75,
      average_call_s: 84,
      calls_measured: 9,
      reply_typical_ms: 1420,
    }),
    weekSpeed("2026-10-26", { language: "te-IN", calls: 8, answered: 6, answered_share: 0.75, reply_typical_ms: 1300 }),
    weekSpeed("2026-10-26", { language: "hi-IN", calls: 4, answered: 3, answered_share: 0.75, reply_typical_ms: 1700 }),
  ],
};

/** `GET /v1/analytics/cost-per-result` (D-944): a week with leads, a month without. */
export const COST_PER_RESULT_ROUTE = "/v1/analytics/cost-per-result";

export const COST_PER_RESULT: CostPerResult = {
  billing_step_seconds: 30,
  windows: [
    {
      days: 7,
      from_date: "2026-10-24",
      to_date: "2026-10-30",
      spent_inr: "120.00",
      answered_calls: 12,
      leads_captured: 4,
      booked_results: 2,
      per_answered_call_inr: "10.00",
      per_lead_inr: "30.00",
      per_booked_result_inr: "60.00",
    },
    {
      days: 30,
      from_date: "2026-10-01",
      to_date: "2026-10-30",
      spent_inr: "400.00",
      answered_calls: 40,
      leads_captured: 0,
      booked_results: 0,
      per_answered_call_inr: "10.00",
      per_lead_inr: null,
      per_booked_result_inr: null,
    },
  ],
};
