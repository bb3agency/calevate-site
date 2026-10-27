/**
 * HOW A NUMBER READS ON A PUBLIC OR CLIENT PAGE — the one display rule.
 *
 * At most ONE digit after the decimal point, and none when the value is whole: ₹4.5000
 * reads ₹4.5, ₹6.0000 reads ₹6, ₹4.6296 reads ₹4.6, 12.0% reads 12% (founder, 27 Oct
 * 2026). Rounding is half-up (away from zero on a tie), the server's
 * `Decimal.quantize(ROUND_HALF_UP)`, so a screen and an email never disagree on a figure.
 *
 * Everything here works on the DECIMAL STRING the API sent and never parses it into a
 * float (hard rule 7): `Number("10159.05")` is how a rupee figure gains a stray
 * 0.000000001, and rounding one with `toFixed` rounds the float, not the decimal
 * (`(1.005).toFixed(2)` is "1.00"). The rounding below is digit arithmetic with a carry.
 *
 * THE EXCEPTIONS use `formatINRExact` / `formatRupeeRateExact` and nothing else:
 * - tax documents (invoice, receipt, credit note, GST statement), because a tax invoice must
 *   reconcile to the paisa — qty × unit = amount, line by line;
 * - the admin and ops console, where an operator attests and compares exact figures.
 * A value somebody is typing or editing is shown as they typed it, through neither.
 */

const DECIMAL = /^[-+]?\d+(\.\d+)?$/;

/** Indian digit grouping of an unsigned run of digits: 1234567 → 12,34,567. */
function groupIndian(whole: string): string {
  const head = whole.length > 3 ? whole.slice(0, -3) : "";
  const tail = whole.slice(-3);
  return head ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}` : tail;
}

/** Add one to a run of decimal digits, carrying: "199" → "200", "99" → "100". */
function incrementDigits(digits: string): string {
  const out = digits.split("");
  for (let i = out.length - 1; i >= 0; i -= 1) {
    if (out[i] !== "9") {
      out[i] = String(Number(out[i]) + 1);
      return out.join("");
    }
    out[i] = "0";
  }
  return `1${out.join("")}`;
}

/**
 * A decimal string rounded half-up to `places` digits after the point, trailing zeros
 * and a bare point dropped: ("4.6296", 1) → "4.6", ("4.95", 1) → "5", ("-0.04", 1) → "0".
 * Throws on anything that is not a plain decimal, so a malformed figure fails loudly
 * rather than rendering as NaN.
 */
export function roundDecimalString(value: string, places: number): string {
  const trimmed = value.trim();
  if (!DECIMAL.test(trimmed)) throw new Error(`not a decimal string: ${JSON.stringify(value)}`);
  const negative = trimmed.startsWith("-");
  const [rawWhole, rawFraction = ""] = trimmed.replace(/^[-+]/, "").split(".");
  let whole = rawWhole.replace(/^0+(?=\d)/, "");
  let fraction = rawFraction;
  if (fraction.length > places) {
    const kept = fraction.slice(0, places);
    const roundUp = fraction.charCodeAt(places) >= "5".charCodeAt(0);
    if (roundUp) {
      const bumped = incrementDigits(whole + kept);
      whole = bumped.slice(0, bumped.length - places) || "0";
      fraction = bumped.slice(bumped.length - places);
    } else {
      fraction = kept;
    }
  }
  fraction = fraction.replace(/0+$/, "");
  const magnitude = fraction ? `${whole}.${fraction}` : whole;
  return negative && /[1-9]/.test(magnitude) ? `-${magnitude}` : magnitude;
}

/** What callers may pass: the API's decimal string, or a number this app computed. */
type Displayable = string | number | null | undefined;

/**
 * A number computed in the browser (a duration, a share) as a decimal string. These are
 * never money — money arrives as a string — so a float is what they already are.
 */
function asDecimalString(value: number): string {
  if (!Number.isFinite(value)) throw new Error(`not a finite number: ${value}`);
  return value.toFixed(6);
}

function signAndDigits(value: string | number): { negative: boolean; digits: string } {
  const rounded = roundDecimalString(typeof value === "number" ? asDecimalString(value) : value, 1);
  const negative = rounded.startsWith("-");
  const [whole, fraction] = rounded.replace(/^-/, "").split(".");
  return { negative, digits: fraction ? `${groupIndian(whole)}.${fraction}` : groupIndian(whole) };
}

/** A figure under the display rule, Indian-grouped: "1234.56" → "1,234.6", "12.0" → "12". "—" when absent. */
export function formatDecimal(value: Displayable): string {
  if (value === null || value === undefined || value === "") return "—";
  const { negative, digits } = signAndDigits(value);
  return `${negative ? "-" : ""}${digits}`;
}

/** Rupees under the display rule: "4.5000" → "₹4.5", "6.0000" → "₹6", "-1234.56" → "-₹1,234.6". */
export function formatINR(value: Displayable): string {
  if (value === null || value === undefined || value === "") return "—";
  const { negative, digits } = signAndDigits(value);
  return `${negative ? "-" : ""}₹${digits}`;
}

/** A percentage under the display rule: "12.0" → "12%", "4.25" → "4.3%". */
export function formatPercent(value: Displayable): string {
  const figure = formatDecimal(value);
  return figure === "—" ? figure : `${figure}%`;
}

/**
 * Rupees to the paisa, for TAX DOCUMENTS AND THE ADMIN CONSOLE ONLY (see the header).
 * Exactly two decimals, from the digits: "10159" → "₹10,159.00". Digits past the paisa are
 * cut, not rounded, because the server already rounded every money field it sends
 * (`billing/service.to_paise`).
 */
export function formatINRExact(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const [whole = "0", fraction = ""] = value.replace(/^[-+]/, "").split(".");
  return `${negative ? "-" : ""}₹${groupIndian(whole)}.${`${fraction}00`.slice(0, 2)}`;
}

/**
 * An amount someone is about to PAY: whole rupees plain ("₹50,000"), any paise exact
 * ("₹2,500.15"). Rounding a payable figure to one decimal would print a different sum from
 * the one charged or the one a bank transfer must match.
 */
export function formatPayableINR(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const fraction = value.split(".")[1] ?? "";
  return /^0*$/.test(fraction) ? formatINR(value) : formatINRExact(value);
}

/**
 * A per-minute rate at the precision the server sent it, for TAX DOCUMENTS AND THE ADMIN
 * CONSOLE ONLY: `overage_rate_inr` is NUMERIC(12,4) and ₹7.1250/min printed as ₹7.1 beside
 * "× 20 min = ₹142.50" would make an invoice line fail the check a client performs on it.
 */
export function formatRupeeRateExact(value: string): string {
  return `₹${value}`;
}
