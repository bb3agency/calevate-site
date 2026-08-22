/**
 * Comparing two per-minute model prices, EXACTLY, without ever parsing one as a float.
 *
 * ## Why this exists at all
 *
 * Choosing a model is a money decision: `client_surcharge_inr_per_minute` is what that
 * model ADDS to the client's bill per minute (D-455), and the whole point of the picker is
 * that a client can see what swapping one for another does to it. A picker that shows two
 * rates and leaves the reader to subtract them in their head is the trap this module
 * closes — and the obvious way to close it, `Number(a) - Number(b)`, is the exact defect
 * hard rule 7 exists for. `Number("0.4830") - Number("0.2400")` is 0.24300000000000002,
 * which prints as a price nobody was ever charged.
 *
 * Kind-agnostic on purpose: the admin console compares the SUPPLIER cost with the same
 * two functions (`platform_cost_inr_per_minute`, which never appears on a client screen).
 * These take decimal strings and say how they differ; which figure a sentence is about is
 * the caller's label.
 *
 * So every function here works on the DIGIT STRING the server sent. Numbers appear in
 * exactly one place — reading a run of digits as an integer count of the smallest unit
 * present — and that read is exact for every value below 2^53 and REFUSES above it
 * (`Number.isSafeInteger`), which is what makes "we cannot compare these" a state this
 * module can return instead of a wrong figure it can invent.
 *
 * ## Why this is the last money arithmetic in the browser
 *
 * There was a second: a paise-based `addRupees` that summed the usage panel's three
 * charge components into a "Total so far". It is gone — `UsagePanelOut.month_charges_inr`
 * is now the server's own total — and this module is deliberately NOT the place that work
 * would return to. Whole paise is right for a TOTAL and wrong here by exactly the argument
 * `formatRupeeRate` makes against `formatINR`: a rate is NUMERIC(12,4)-shaped, and
 * truncating ₹0.2425 to ₹0.24 loses the digits two adjacent models actually differ by.
 * What survives in the browser is COMPARING two rates the server sent, at whatever scale
 * they arrived with — never adding money, and never pricing anything.
 *
 * ## What is deliberately NOT here
 *
 * No multiplication, no "a five-minute call costs 5 × this". The server publishes ONE
 * number per model and it already carries a call length in its name; a total computed
 * here would be a second pricing model in the browser, and the first thing to disagree
 * with the invoice. If a total is wanted on screen, it is a field on the endpoint.
 */

/** A decimal as the server writes it: a sign, integer digits, fraction digits. */
interface Decimal {
  negative: boolean;
  whole: string;
  fraction: string;
}

/**
 * A money string the API sent, split — or `null` if it is not one.
 *
 * `null` rather than a throw or a zero: every caller here already has an "we cannot say"
 * rendering, and a zero would claim two models cost the same, which is the one answer
 * that is actively wrong in the cheap direction.
 */
function parseDecimal(value: string | null | undefined): Decimal | null {
  if (value === null || value === undefined) return null;
  const match = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(value.trim());
  if (match === null) return null;
  const whole = match[2] ?? "";
  const fraction = match[3] ?? "";
  // "." and "" and "-" all match the pattern above and are not numbers.
  if (whole === "" && fraction === "") return null;
  return { negative: match[1] === "-", whole: whole === "" ? "0" : whole, fraction };
}

/**
 * The value as an integer count of `10^scale`ths — exact, or `null` when it would not be.
 *
 * `Number("0004830")` is 4830 with no rounding anywhere: reading a run of DIGITS is the
 * one thing binary floating point does exactly, up to 2^53. Above that it silently
 * starts lying, so the guard is the difference between this module and the mistake it
 * exists to prevent.
 */
function unitsAt(value: Decimal, scale: number): number | null {
  const digits = `${value.whole}${value.fraction.padEnd(scale, "0")}`;
  const units = Number(digits);
  if (!Number.isSafeInteger(units)) return null;
  return value.negative ? -units : units;
}

/** The digit form of an integer count of `10^scale`ths — the inverse of `unitsAt`. */
function renderUnits(units: number, scale: number): string {
  const negative = units < 0;
  const digits = String(Math.abs(units)).padStart(scale + 1, "0");
  const cut = digits.length - scale;
  const body = scale === 0 ? digits : `${digits.slice(0, cut)}.${digits.slice(cut)}`;
  return `${negative ? "-" : ""}${body}`;
}

/** How the two prices compare, when they can be compared at all. */
export type RateOrder = "cheaper" | "same" | "dearer" | "unknown";

/**
 * Is `rate` cheaper than, the same as, or dearer than `baseline`?
 *
 * String comparison after padding both fractions to the same length — no subtraction, so
 * this answers even for values `difference` below has to refuse. `"unknown"` when either
 * side is missing or unparseable, which is what a screen prints as a blank rather than as
 * "same price": two models being identically priced is a claim, and we do not have it.
 */
export function compareRates(rate: string | null | undefined, baseline: string | null | undefined): RateOrder {
  const a = parseDecimal(rate);
  const b = parseDecimal(baseline);
  if (a === null || b === null) return "unknown";
  if (a.negative !== b.negative) return a.negative ? "cheaper" : "dearer";
  const scale = Math.max(a.fraction.length, b.fraction.length);
  const left = `${a.whole.padStart(Math.max(a.whole.length, b.whole.length), "0")}${a.fraction.padEnd(scale, "0")}`;
  const right = `${b.whole.padStart(Math.max(a.whole.length, b.whole.length), "0")}${b.fraction.padEnd(scale, "0")}`;
  if (left === right) return "same";
  const dearer = left > right;
  // Both negative flips the reading: -0.30 is a smaller number than -0.20.
  return (a.negative ? !dearer : dearer) ? "dearer" : "cheaper";
}

/**
 * `rate - baseline`, as digits, at whichever of the two carries more of them.
 *
 * Returns the ABSOLUTE difference — the direction is `compareRates`' answer and the two
 * are rendered as one sentence ("₹0.06 more per minute"), so a caller never has to decide
 * what a minus sign in front of a price means. `null` when either value is missing,
 * unparseable, or big enough that the integer read would stop being exact.
 */
export function rateDifference(
  rate: string | null | undefined,
  baseline: string | null | undefined,
): string | null {
  const a = parseDecimal(rate);
  const b = parseDecimal(baseline);
  if (a === null || b === null) return null;
  const scale = Math.max(a.fraction.length, b.fraction.length);
  const left = unitsAt(a, scale);
  const right = unitsAt(b, scale);
  if (left === null || right === null) return null;
  return renderUnits(Math.abs(left - right), scale);
}
