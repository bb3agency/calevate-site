/**
 * A typed phone number as E.164: the browser's one mirror of the server's
 * `apps/api/ingest/service.normalize_phone`, which every typed number goes through on the
 * way in (campaign contacts, the owner's own mobile number, the do-not-call list). The
 * server stays the authority and re-normalises; this copy exists so a row is marked, or a
 * number shown back for checking, before anything is sent.
 *
 * It must accept exactly what the server accepts. A narrower mirror marks a number the
 * server would take as "can't be called" and never sends it, and the owner cannot tell
 * why; a wider one shows a number back that the server then refuses.
 */

const E164 = /^\+[1-9]\d{7,14}$/;
const INDIA = "+91";
/** The first digit of every Indian mobile (`calevate_shared.indian_mobile`). */
const MOBILE_LEADING_DIGITS = "6789";

/** `+91` and ten digits opening 6-9: an Indian mobile in the form the server stores. */
export function isIndianMobile(e164: string): boolean {
  const national = e164.startsWith(INDIA) ? e164.slice(INDIA.length) : "";
  return /^\d{10}$/.test(national) && MOBILE_LEADING_DIGITS.includes(national[0]);
}
const DECIMAL = /^\p{Nd}$/u;

function isDecimal(codePoint: number): boolean {
  return codePoint > 0 && DECIMAL.test(String.fromCodePoint(codePoint));
}

/**
 * Every decimal digit in `text`, in any script, as ASCII — the server's
 * `unicodedata.decimal` over `str.isdecimal()` (general category Nd). A Telugu or
 * Devanagari keyboard types its own digits, and a plain `\D` strip dropped them.
 *
 * The value needs no per-script table: Unicode's stability policy guarantees that Nd
 * characters only occur in contiguous runs of ten with values 0 to 9 ascending
 * (unicode.org/policies/stability_policy.html, property value stability), so a maximal
 * run of Nd code points starts at a zero and a digit's value is its distance from that
 * start, modulo ten.
 */
export function asciiDigits(text: string): string {
  let out = "";
  for (const char of text) {
    const codePoint = char.codePointAt(0) ?? 0;
    if (!isDecimal(codePoint)) continue;
    let back = 0;
    while (isDecimal(codePoint - back - 1)) back += 1;
    out += String(back % 10);
  }
  return out;
}

/** E.164 from what was typed, or null when it cannot be read as a phone number. */
export function normalizePhone(raw: string): string | null {
  const text = raw.trim();
  const plusCount = (text.match(/\+/g) ?? []).length;
  if (plusCount > 1 || (plusCount === 1 && !text.startsWith("+"))) return null;
  const digits = asciiDigits(text);
  let candidate: string | null = null;
  if (digits.length === 13 && digits.startsWith("910") && MOBILE_LEADING_DIGITS.includes(digits[3])) {
    // `+91 (0) 98765 43210`: the country code and the trunk prefix, as business cards print it.
    candidate = INDIA + digits.slice(3);
  } else if (text.startsWith("+")) {
    candidate = digits.length >= 10 && digits.length <= 15 ? `+${digits}` : null;
  } else if (digits.length === 10 && MOBILE_LEADING_DIGITS.includes(digits[0])) {
    candidate = INDIA + digits;
  } else if (digits.length === 11 && digits[0] === "0" && MOBILE_LEADING_DIGITS.includes(digits[1])) {
    // The trunk prefix an Indian writes before a mobile; it is not part of the number.
    candidate = INDIA + digits.slice(1);
  } else if (digits.length === 12 && digits.startsWith("91")) {
    candidate = `+${digits}`;
  }
  return candidate !== null && E164.test(candidate) ? candidate : null;
}
