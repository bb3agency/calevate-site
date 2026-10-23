/**
 * Calendar-date arithmetic for the kit's date controls.
 *
 * A date here is an IST calendar day written "YYYY-MM-DD" (D-709), never an instant: the
 * day a campaign starts, the first day of a calls filter. Arithmetic runs on a `Date` at
 * UTC midnight purely as a day counter, so no viewer's zone can move a day; "today" comes
 * from `istDateStamp`, the day it is in India. Turning a day into an instant for the API
 * is `istDateToInstant` in `components/ui.tsx`, not this module.
 */

import { istDateStamp } from "@/components/ui";

export type ISODate = string;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isISODate(value: string): boolean {
  const match = ISO_DATE.exec(value);
  if (!match) return false;
  const at = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return toISODate(at) === value;
}

function fromISODate(value: ISODate): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function toISODate(at: Date): ISODate {
  const y = at.getUTCFullYear();
  const m = String(at.getUTCMonth() + 1).padStart(2, "0");
  const d = String(at.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Today in India. */
export function todayIST(): ISODate {
  return istDateStamp();
}

export function addDays(value: ISODate, days: number): ISODate {
  const at = fromISODate(value);
  at.setUTCDate(at.getUTCDate() + days);
  return toISODate(at);
}

/** The same day `months` later, held to the last day of a shorter month (31 Jan + 1 → 28/29 Feb). */
export function addMonths(value: ISODate, months: number): ISODate {
  const [y, m, d] = value.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1 + months, 1));
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  first.setUTCDate(Math.min(d, last));
  return toISODate(first);
}

/** 0 for Monday … 6 for Sunday: the week starts on Monday in India. */
export function weekdayIndex(value: ISODate): number {
  return (fromISODate(value).getUTCDay() + 6) % 7;
}

export function startOfMonth(value: ISODate): ISODate {
  return `${value.slice(0, 7)}-01`;
}

export function endOfMonth(value: ISODate): ISODate {
  return addDays(addMonths(startOfMonth(value), 1), -1);
}

/** Six weeks of days, Monday first, covering the month `value` falls in. */
export function monthGrid(value: ISODate): ISODate[][] {
  const first = startOfMonth(value);
  let day = addDays(first, -weekdayIndex(first));
  const weeks: ISODate[][] = [];
  for (let w = 0; w < 6; w += 1) {
    const week: ISODate[] = [];
    for (let i = 0; i < 7; i += 1) {
      week.push(day);
      day = addDays(day, 1);
    }
    weeks.push(week);
  }
  return weeks;
}

export function compareDates(a: ISODate, b: ISODate): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Inclusive day count of a range: 1 Nov to 7 Nov is 7. */
export function daysBetween(start: ISODate, end: ISODate): number {
  return Math.round((fromISODate(end).getTime() - fromISODate(start).getTime()) / 86_400_000) + 1;
}

// `timeZone: "UTC"` because the Date is a UTC-midnight day counter (above): any other
// zone would print a neighbouring day for half the world.
const LONG = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long", year: "numeric" });
const SHORT = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
const DAY_MONTH = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "numeric", month: "short" });
const MONTH_YEAR = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", month: "long", year: "numeric" });
const WEEKDAY_SHORT = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", weekday: "short" });

/** "Monday, 3 November 2026" — a calendar cell's accessible name. */
export function formatDateLong(value: ISODate): string {
  return LONG.format(fromISODate(value));
}

/** "3 Nov 2026" — a picker's face. */
export function formatDateShort(value: ISODate): string {
  return SHORT.format(fromISODate(value));
}

/** "3 Nov – 9 Nov 2026", or across years "28 Dec 2026 – 3 Jan 2027". */
export function formatDateRange(start: ISODate, end: ISODate): string {
  if (start === end) return formatDateShort(start);
  if (start.slice(0, 4) === end.slice(0, 4)) {
    return `${DAY_MONTH.format(fromISODate(start))} – ${formatDateShort(end)}`;
  }
  return `${formatDateShort(start)} – ${formatDateShort(end)}`;
}

/** "November 2026". */
export function formatMonth(value: ISODate): string {
  return MONTH_YEAR.format(fromISODate(value));
}

/** "Mon" … "Sun", Monday first. */
export function weekdayNames(): string[] {
  // 2024-01-01 was a Monday.
  return Array.from({ length: 7 }, (_, i) => WEEKDAY_SHORT.format(fromISODate(addDays("2024-01-01", i))));
}
