/**
 * "2026-10" → "October 2026": a billing month as an owner says it.
 *
 * The API names a billing month as `YYYY-MM` in IST. The instant is BUILT in UTC and READ
 * back in UTC, so the two cancel and the month is the one the string names wherever the
 * browser is — `new Date("2026-10")` would be midnight UTC and, west of UTC, read as
 * September. Anything that is not a `YYYY-MM` comes back unchanged rather than as
 * "Invalid Date".
 */
export function formatBillingMonth(month: string): string {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(month);
  if (match === null) return month;
  const at = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  return at.toLocaleDateString("en-IN", { timeZone: "UTC", month: "long", year: "numeric" });
}
