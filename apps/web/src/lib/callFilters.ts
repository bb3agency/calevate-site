/**
 * THE CALL LOG'S FILTERS, as the API takes them (REDESIGN-2): `outcome`, `direction`,
 * and a half-open window `[since, until)` of instants that MUST carry a time zone (the API
 * refuses a zone-less value with `call_filter_time_without_zone`).
 *
 * Every window is computed on India-time calendar days, written with an explicit +05:30,
 * so "Today" is the owner's today wherever the browser's clock thinks it is. Pure and
 * React-free, so the arithmetic is tested without a render.
 */

/** In the order an owner works them, what needs a person first (`lib/callReview`). */
export const OUTCOMES = [
  { value: "needs_you", label: "Needs you" },
  { value: "call_back_booked", label: "Call back booked" },
  { value: "answered", label: "Answered" },
  { value: "transferred", label: "Transferred" },
  { value: "hung_up_early", label: "Hung up early" },
  { value: "missed", label: "Missed" },
] as const;
export type CallOutcome = (typeof OUTCOMES)[number]["value"];

export const DIRECTIONS = [
  { value: "inbound", label: "Incoming" },
  { value: "outbound", label: "Outgoing" },
] as const;
export type CallDirection = (typeof DIRECTIONS)[number]["value"];

export const RANGES = [
  { value: "all", label: "Any time" },
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "custom", label: "Custom" },
] as const;
export type CallRange = (typeof RANGES)[number]["value"];

const IST = "+05:30";
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** `2026-10-10` plus `days` (may be negative), as another `YYYY-MM-DD`. */
export function shiftDay(day: string, days: number): string {
  const m = DAY.exec(day);
  if (!m) return day;
  const at = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + days));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())}`;
}

const startOf = (day: string) => `${day}T00:00:00${IST}`;

/**
 * The `[since, until)` window for a range, given India's today. "7 days" is today and the
 * six before it; a custom range includes both of its days. A custom range with a missing
 * or backwards end returns only what is valid (an open end), never an inverted window.
 */
export function callWindow(
  range: CallRange,
  todayIst: string,
  from?: string,
  to?: string,
): { since?: string; until?: string } {
  if (range === "today") return { since: startOf(todayIst) };
  if (range === "7d") return { since: startOf(shiftDay(todayIst, -6)) };
  if (range === "30d") return { since: startOf(shiftDay(todayIst, -29)) };
  if (range === "custom") {
    const since = from && DAY.test(from) ? startOf(from) : undefined;
    const until = to && DAY.test(to) && (!from || to >= from) ? startOf(shiftDay(to, 1)) : undefined;
    return { since, until };
  }
  return {};
}
