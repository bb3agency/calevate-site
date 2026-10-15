import type { QaSample } from "@/lib/api/qaSamples";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * "3 Aug 2026" for a draw week's IST Monday. The API sends a bare `YYYY-MM-DD`; reading it
 * through `Date` would place it at UTC midnight and could print the Sunday before.
 */
export function weekLabel(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "1 call" / "3 calls". */
export function calls(count: number): string {
  return `${count} ${count === 1 ? "call" : "calls"}`;
}

/** "Inbound" / "Outbound", for a row's direction. */
export function directionLabel(direction: string): string {
  return direction.charAt(0).toUpperCase() + direction.slice(1);
}

/** The review screen's address, carrying the queue's filters so its back link and its
 *  "Next call to review" stay inside the same filtered queue. */
export function reviewHref(row: Pick<QaSample, "id">, search: string): string {
  return `/admin/qa-sampling/${row.id}${search ? `?${search}` : ""}`;
}
