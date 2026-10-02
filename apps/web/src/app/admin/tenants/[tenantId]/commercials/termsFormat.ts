import { formatINR, formatRupeeRate } from "@/components/ui";
import type { PlanRow } from "@/lib/api/commercials";

/**
 * Fees go through `formatINR`, which formats the DIGITS of the API's string and never
 * parses them. A RATE does not: `overage_rate` is NUMERIC(12,4) published unrounded so
 * `qty x unit = amount` holds, and rounding ₹7.1250 to ₹7.12 on screen would break the
 * invoice's arithmetic in our favour (BUILD-LOG §52).
 */
export function money(value: string | null): string | null {
  return value === null ? null : formatINR(value);
}

export function rate(value: string | null): string | null {
  return value === null ? null : formatRupeeRate(value);
}

/**
 * The plan's SECOND overage rate, from whichever of the two wire names carries it.
 *
 * Step 1 of a two-step deprecation (hard rule 8, D-558): the server emits BOTH
 * `overage_rate_second_inr` and the deprecated `overage_rate_value_inr` with the identical
 * figure for one release, and this bundle can be talking to an API a release behind. `??`
 * and not `||`: `null` is a real reading ("no separate second rate") and must not fall
 * through to the other field. Step 2 deletes this function and reads the new field.
 */
export function secondOverageRate(row: PlanRow | null): string | null {
  if (row === null) return null;
  return row.overage_rate_second_inr ?? row.overage_rate_value_inr;
}
