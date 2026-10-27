import type { DateRange } from "@/components/arc/calendar";
import { daysBetween, formatDateRange, formatDateShort } from "@/components/arc/ist-dates";
import type { components } from "@/lib/api/schema";

/** A saved view's day range: fixed India days, or the last N days (`crm.schemas.ViewDaysIn`). */
export type ViewDays = components["schemas"]["ViewDaysIn"];

/**
 * The earliest day a range with no start can mean. A view Pip saved as "up to 10 Oct" has no
 * start; the date picker needs one, and nothing on the platform is older than this.
 */
const FLOOR_DAY = "2025-01-01";

/** Does this range end today, so it can be kept as "the last N days"? */
export function endsToday(range: DateRange | null, today: string): boolean {
  return range !== null && range.end === today;
}

/**
 * The range as a view stores it. `rolling` keeps a range that ends today as "the last N
 * days", so a view saved as "this week" still means this week next month.
 */
export function toViewDays(range: DateRange | null, today: string, rolling: boolean): ViewDays | null {
  if (range === null) return null;
  if (rolling && endsToday(range, today)) return { last_days: daysBetween(range.start, range.end) };
  return { from_day: range.start, to_day: range.end };
}

/**
 * The days a stored range covers. The server answers every range with concrete days for
 * today (`crm.saved_views`), rolling or fixed, so the screen applies those and never works
 * out a rolling range itself.
 */
export function fromViewDays(days: ViewDays | null | undefined, today: string): DateRange | null {
  if (!days) return null;
  const start = days.from_day ?? null;
  const end = days.to_day ?? null;
  if (start === null && end === null) return null;
  return { start: start ?? FLOOR_DAY, end: end ?? today };
}

/** "the last 7 days", "today" or "3 Nov – 9 Nov 2026", for a view's description. */
export function describeViewDays(days: ViewDays | null | undefined): string | null {
  if (!days) return null;
  if (days.last_days) return days.last_days === 1 ? "today" : `the last ${days.last_days} days`;
  if (days.from_day && days.to_day) return formatDateRange(days.from_day, days.to_day);
  if (days.from_day) return `from ${formatDateShort(days.from_day)}`;
  if (days.to_day) return `up to ${formatDateShort(days.to_day)}`;
  return null;
}
