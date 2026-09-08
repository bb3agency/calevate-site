/**
 * WHAT A MONEY STRING LOOKS LIKE ON THIS WIRE — the one spelling, for the whole app.
 *
 * Hard rule 7 says money is NUMERIC and never a float, and its frontend shadow is that a
 * rupee figure arrives as an exact decimal STRING and stays one all the way to the DOM.
 * That makes "is this actually one of our money strings?" a question several seams have to
 * ask about UNTRUSTED input — a public body nobody authenticated, a ledger row a screen is
 * about to print, an amount an operator typed — and each of them had grown its own regex.
 *
 * There were FOUR copies of the unsigned rule (`lib/api/rateCard.ts`, `lib/api/voices.ts`,
 * `app/c/[slug]/billing/lots.ts`, `app/admin/tenants/[tenantId]/credits/lots.ts`) and three
 * of the signed one, each with a comment noting the others and calling the hoist a handoff.
 * Two spellings of one rule is a defect even while both agree (CLAUDE.md, "one way per
 * problem"); four is a drift waiting for whoever widens one of them. This module is the
 * hoist, and there is deliberately no fifth: a new seam imports from here.
 *
 * Most of those copies went away with the hand validators they served, when the D-547
 * schema regeneration made their fields generated and required. Three callers are left —
 * `lib/api/rateCard.ts` (the public card, an unauthenticated body nobody validated),
 * `app/c/[slug]/billing/lots.ts` (the lot splits, an untyped dict on the wire) and
 * `app/admin/spend/ttsCost.ts` — and every one of them is a place where the compiler
 * genuinely cannot answer the question, which is the only place either predicate belongs.
 *
 * ## The two rules are genuinely different, so both live here rather than one being bent
 *
 * A RATE or a purchase AMOUNT is unsigned and carries at most four decimal places, because
 * that is `NUMERIC(12,4)` — the scale the API's rate card, its pack ladder and every lot's
 * frozen ₹/min are stored and serialised at. Nothing sells at a negative price, so a
 * leading `-` on one of those is a payload to refuse rather than to render.
 *
 * A LEDGER figure is signed and its scale is not this module's business: a wallet delta is
 * `-1234.56`, a correction is positive, and a credits balance is whichever the arithmetic
 * made it. Refusing a minus sign there would drop exactly the rows an operator most needs
 * to see, so the two predicates stay apart and each seam names the one it means.
 *
 * Neither predicate parses anything. Turning digits into a number is `lib/api/rateCard.ts::
 * rateToTenThousandths`, which reads them into an exact integer count of ten-thousandths of
 * a rupee; `Number()` on a money string is the defect both of them exist to keep away from
 * a wallet.
 */

/**
 * A rate or an amount: digits, optionally a point and one to four more digits.
 * `NUMERIC(12,4)` as JSON sends it, unsigned.
 */
export const MONEY_STRING = /^\d+(\.\d{1,4})?$/;

/** Is this untrusted value a rate or amount as this API spells one? */
export function isMoneyString(value: unknown): value is string {
  return typeof value === "string" && MONEY_STRING.test(value);
}

/**
 * A LEDGER figure: the same digits, optionally signed, at any scale.
 *
 * Trimmed before matching because these arrive from bodies this app did not build, and a
 * stray space is a formatting artefact rather than a claim about the money.
 */
const SIGNED_MONEY_STRING = /^-?\d+(\.\d+)?$/;

/** Is this untrusted value a signed ledger figure as this API spells one? */
export function isSignedMoneyString(value: unknown): value is string {
  return typeof value === "string" && SIGNED_MONEY_STRING.test(value.trim());
}
