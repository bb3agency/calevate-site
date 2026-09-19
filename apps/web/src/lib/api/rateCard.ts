/**
 * The public self-serve rate card (D-545) — the ONE way the marketing site knows a price.
 *
 * ## Why this module exists
 *
 * The site used to hold a typed `500` paise in `lib/roi.ts` whose own comment admitted it
 * would drift the day `self_serve_inr_per_min` moved on the server. The founder's pricing
 * decision of 5 Sep 2026 — keep the list rate at ₹5.00 and lead with the effective rate
 * the ₹50,000 pack already delivers — needed the PACK LADDER on the site too, and typing
 * five more numbers beside the first would have been the same defect five times over.
 *
 * So the API publishes the card at `GET /v1/public/rate-card`, unauthenticated, built by
 * the same function as the signed-in `/v1/billing/topups/packs` read and pinned against
 * the margin guard's own arithmetic (`tests/public_rate_card_test.py`). This module reads
 * it and nothing else. **No figure on the public site is typed any more**: every rupee
 * on `/pricing` and every rate in the ROI calculator is a string that arrived in this
 * response, formatted from its digits.
 *
 * ## Two rates per pack, and the NAME of each voice, since D-547 (7 Sep 2026)
 *
 * A pack no longer has "an" effective rate. It has one ₹/min for each of the two voices an
 * agent can speak with, and which one prices a call is a property of the AGENT that took
 * it. So every reader on this site asks for a rate BY VOICE (`packRate`, `cardFromRate`),
 * and the single-rate fields (`from_inr_per_min`, `effective_rate_inr_per_min`,
 * `talk_time_minutes`) are deprecated on the wire for one release and read by nothing here.
 *
 * The card also carries what a CLIENT calls each voice, and that is the second reason this
 * module exists in the shape it does: no client-facing surface names a vendor as a product
 * tier (founder, 7 Sep 2026), the two names are defined once in `billing/rates.py`
 * (`VOICE_TIER_LABELS`), and a copy of them in TypeScript would be a second definition of a
 * name a client reads — the drift that ends with one buyer meeting both. So the label
 * crosses the wire beside the rate and `tierLabel` passes it through untouched. The wire
 * FIELD names say `clear`/`studio`: those are the ledger's vocabulary, and they are not
 * shown to anybody — a screen prints the label the server sent, never the token.
 *
 * ## Server-side, at request time, through the generated client
 *
 * NOT `"use client"`, deliberately. The marketing tree has no `QueryClientProvider`
 * (`app/providers.tsx` is mounted by the two console shells and the auth pages only), so
 * a TanStack hook cannot run there — and it should not: the pages are already rendered
 * per request (`app/layout.tsx` is `force-dynamic` for the CSP nonce), so the page
 * itself awaits this and hands plain data to its sections. The request still goes
 * through `apiRequest`, never a bare `fetch`: same deadline, same problem+json parsing,
 * same seam `tests/transportGuard.test.ts` enforces.
 *
 * ## Honest failure
 *
 * `fetchPublicRateCard` returns `null` when the card cannot be had — a network refusal,
 * a 503 from a maintenance window, a 429, a body that is not the shape the schema says —
 * and every reader renders "could not be loaded" in those words. Nothing falls back to
 * a constant, because a stale or typed price on a pricing page is precisely the claim
 * hard rule 11 exists to stop.
 *
 * ## Money stays a string until it is digits
 *
 * Rates arrive at 4dp (`"4.6296"`), amounts at 2dp (`"50000.00"`). Nothing here calls
 * `Number()` on either: `rateToTenThousandths` reads the DIGITS into an exact integer
 * (ten-thousandths of a rupee — the API's own NUMERIC(12,4) scale), and every derived
 * figure is integer arithmetic from there, the discipline `lib/roi.ts` states for the
 * calculator and `lib/api/wallet.ts` states for the console.
 */

import { formatPaiseINR } from "@/lib/roi";
import { MONEY_STRING } from "@/lib/money";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * The card: the entry rate, the lowest rate on each voice, what a client calls each voice,
 * and every pack priced on both.
 *
 * The tier labels ride on `CreditPacksOut` itself: the API names each voice quality
 * (`billing/rates.VOICE_TIER_LABELS`) and this module passes the name through, so no
 * browser copy of it can drift from the one the server serves.
 */
export type PublicRateCard = Schemas["CreditPacksOut"];
/** One pack: amount, credits, a ₹/min and a talk time on each of the two voices. */
export type RateCardPack = Schemas["CreditPackOut"];

/**
 * The two rungs a rate can be for, spelled the way the WIRE and the ledger spell them. A
 * client never reads these strings: what they read is the card's `*_tier_label`, which is
 * a name the API chose (`billing/rates.VOICE_TIER_LABELS`) and this module only ever
 * passes through.
 *
 * ⚠ **THEY WERE `"sarvam" | "cartesia"` UNTIL 19 SEP 2026, AND THE ARGUMENT FOR THAT WAS
 * THAT A VENDOR MAY BE REPLACED UNDER A RUNG WITHOUT RENAMING WHAT A CLIENT SEES.** That
 * is true and is exactly what happened on 18 Sep 2026, when Sarvam stopped speaking on
 * this product — which left a money column named after a vendor that no longer served it.
 * Naming the rungs after the rungs keeps the property the old argument wanted and drops
 * the part that aged.
 */
export type VoiceTier = "clear" | "studio";

/**
 * Both voices, in the order the card leads with them (the cheaper first).
 *
 * A TUPLE rather than `readonly VoiceTier[]`, so `.length` is the literal `2` and a
 * renderer can pin its own arity against it at compile time. `components/marketing/
 * rateCard.tsx` does: its voice switch writes out two Tailwind `peer` names because
 * Tailwind scans source text and cannot generate a class it has not read, and a third
 * voice arriving would otherwise be priced in the document with no way to select it.
 */
export const VOICE_TIERS = [
  "clear",
  "studio",
] as const satisfies readonly VoiceTier[];

/**
 * A rung this build cannot price, refused rather than guessed. THE ONE COPY — the client
 * console's lot table imports it from here rather than keeping its own.
 *
 * ⚠ **EVERY PER-RUNG ACCESSOR IN THIS FILE WAS `voice === "clear" ? clear : studio` UNTIL
 * 19 SEP 2026, AND THAT TERNARY IS TOTAL OVER `string`.** The compiler was happy and any
 * rung that was not the value one resolved to the STUDIO figure — the dearer one. With two
 * rungs that is merely fragile; the day a third is added it is a price shown wrong on the
 * PUBLIC pricing page, in the direction that overcharges, with nothing failing to say so.
 * The same defect was fixed on the billing side (`billing/lots.py::OpenLot.rate_for`) and
 * in the console's own lot table on 19 Sep 2026, and this file — the one a stranger reads
 * before they are a client — was missed by that sweep.
 *
 * `never` is the point: a third member of `VoiceTier` makes each call below a TYPE ERROR,
 * so the next rung cannot be added without every accessor being taught about it. The throw
 * is the runtime half, for a value that reached here as a cast or off the wire —
 * `undefined` would be a blank price, and a blank price is read as free.
 */
export function unpricedTier(tier: never): never {
  throw new Error(`no rate for voice tier ${String(tier)}`);
}

/** One pack's ₹/min on one voice, as the 4dp string the API sent. THE ONE DOOR. */
export function packRate(pack: RateCardPack, voice: VoiceTier): string {
  switch (voice) {
    case "clear":
      return pack.clear_inr_per_min;
    case "studio":
      return pack.studio_inr_per_min;
    default:
      return unpricedTier(voice);
  }
}

/** Whole minutes one pack's credits buy on one voice, as the API floored them. */
export function packMinutes(pack: RateCardPack, voice: VoiceTier): number {
  switch (voice) {
    case "clear":
      return pack.clear_minutes;
    case "studio":
      return pack.studio_minutes;
    default:
      return unpricedTier(voice);
  }
}

/** The lowest ₹/min any pack delivers on one voice — the site's "from" figure. */
export function cardFromRate(card: PublicRateCard, voice: VoiceTier): string {
  switch (voice) {
    case "clear":
      return card.from_clear_inr_per_min;
    case "studio":
      return card.from_studio_inr_per_min;
    default:
      return unpricedTier(voice);
  }
}

/**
 * DOES THIS VOICE'S LADDER ACTUALLY FALL? — the guard every sentence that narrates the
 * ladder has to pass before it promises a discount.
 *
 * ⚠ **A CARD IS NOT REQUIRED TO FALL ON BOTH VOICES, AND THE NEXT ONE DOES NOT.** The
 * founder's 14 Sep 2026 decision (`docs/PIPECAT-MIGRATION.md` §12) prices the cheaper
 * voice FLAT — ₹4.00 at every rung from ₹2,000 to ₹50,000 — while the dearer one still
 * falls ₹7.00 → ₹5.50. `credit_packs.py::card_refusals` permits it: invariant 6 refuses a
 * bigger pack that buys a DEARER minute (`>`), so equal rungs are a legal card and always
 * were. The server therefore cannot be relied on to keep the ladder sloping, and every
 * surface that says "down to X on the largest pack" has to ask first.
 *
 * Said in one place because the sentence is written in four (`/pricing`'s band, the rate
 * table's cheapest-rung chip, the ROI calculator's voice captions, and the console's
 * "What calls cost"), and a guard copied four times is three that will be missed. The
 * comparison is `rateToTenThousandths` over two figures the SERVER sent — exact integers
 * at the API's own NUMERIC(12,4) scale, nothing computed, nothing rounded.
 *
 * False for a card with one rung, which is right: a one-rung ladder is not a discount.
 */
export function ladderFalls(card: PublicRateCard, voice: VoiceTier): boolean {
  const cheapest = rateToTenThousandths(cardFromRate(card, voice));
  return card.packs.some(
    (pack) => rateToTenThousandths(packRate(pack, voice)) > cheapest,
  );
}

/**
 * What a CLIENT calls this voice. Read from the response, never held here: two copies of
 * a name is how a client comes to meet both of them (founder, 7 Sep 2026).
 */
export function tierLabel(card: PublicRateCard, voice: VoiceTier): string {
  switch (voice) {
    case "clear":
      return card.clear_tier_label;
    case "studio":
      return card.studio_tier_label;
    default:
      return unpricedTier(voice);
  }
}

/**
 * **THE TIER NO AGENT CAN BE PUT ON RIGHT NOW, AND THE ONE SENTENCE THAT SAYS SO (D-629).**
 *
 * D-629 removed Sarvam from the TEXT-TO-SPEECH leg entirely — it still transcribes every
 * call, it no longer speaks on any — and gave the cheaper rung to Gnani. Hard rule 7 keeps
 * every Gnani voice out of what anyone can select until an operator attests a real INVOICE
 * figure. The rung therefore EXISTS, has a vendor, prices minutes on every credit lot — and
 * cannot be chosen.
 *
 * ⚠ **THIS PARAGRAPH SAID "Gnani publish no price of any kind" UNTIL 19 SEP 2026 AND THAT
 * WAS A NOT-FINDING WRITTEN DOWN AS A VENDOR FACT** (D-631, the failure hard rule 11
 * exists for). Their console publishes ₹27.00 / 10,000 characters
 * (`app.gnani.ai/voice/pricing`, read by the founder 19 Sep 2026 and relayed;
 * VENDOR-PUBLISHED). The notice below does not change, because it never rested on that
 * claim: what it tells a client is that we have not established what a minute COSTS, and a
 * catalogue rate is not an invoice. The provenance half of the old paragraph also survives
 * — the one figure already in the wild was a RESELLER's for their own platform
 * (`docs/PIPECAT-MIGRATION.md` §7), refusing it was right, and a number that later turns
 * out to match is still not a source.
 *
 * A public page that goes on leading with its rate, and a client screen that goes on saying
 * a new agent starts on it, would both be advertising a voice nobody can be put on. This is
 * what they say instead, in ONE place: three surfaces render it (`/pricing`'s rate table,
 * the ROI calculator's voice options, the client's "What calls cost"), and three typed
 * copies is how a client meets three versions of one fact.
 *
 * **IT IS A PRODUCT FACT, NOT A DEPLOYMENT ONE, WHICH IS WHY IT MAY BE TYPED HERE AT ALL.**
 * Whether a particular deployment has a credential installed is the SERVER's answer, per
 * voice and per audience (`agents/voice_offer.unofferable_reason`, rendered verbatim by
 * `components/voicePicker.tsx`) and is never composed in the browser. "Nobody has priced
 * this vendor" is true of the product everywhere, and the public rate-card route carries no
 * availability field to ask. When the price is attested, this constant and its three call
 * sites are deleted together — that is the whole change, and it is why the notice is one
 * export rather than three sentences.
 */
export const UNPRICED_TIER: VoiceTier = "clear";

/** The sentence itself. Rendered verbatim; never reworded at a call site. */
export const UNPRICED_TIER_NOTICE =
  "Not available to choose yet: the vendor that speaks this voice changed and we have not " +
  "established what one minute of it costs, so we will not put an agent on it. Its rate is " +
  "still fixed on credit you buy today, and it costs you nothing to move an agent onto it " +
  "once it opens.";

export const PUBLIC_RATE_CARD_PATH = "/v1/public/rate-card";

/**
 * Nobody. The route reads nothing about its caller and the site holds no session, so
 * this sends no bearer, no org header and no grant — `apiRequest` omits each header
 * whose value is absent rather than sending an empty one.
 */
const NOBODY: Session = { orgSlug: "" };

/**
 * `"4.6296"` → `46296`, `"5.00"` → `50000`: an exact integer count of ten-thousandths
 * of a rupee, read from the digits. Throws on anything that is not a money string of
 * ours — a caller that has validated the card (`isRateCard`) never sees the throw, and a
 * caller that has not should, loudly, rather than compute with `NaN`.
 */
export function rateToTenThousandths(value: string): number {
  if (!MONEY_STRING.test(value))
    throw new Error(`not a money string: ${JSON.stringify(value)}`);
  const [whole, fraction = ""] = value.split(".");
  return Number(whole) * 10_000 + Number(fraction.padEnd(4, "0"));
}

/**
 * A rate as the calculator's input unit — PAISE per minute, carried to a hundredth of a
 * paisa so a pack's 4dp effective rate is priced exactly rather than rounded to the
 * paisa first (`lib/roi.ts::computeRoi` rounds once, at the end of the line).
 */
export function ratePaisePerMin(rate: string): number {
  return rateToTenThousandths(rate) / 100;
}

/**
 * A rate for a sentence: `"4.6296"` → `"₹4.63"`. Half-up to the paisa, in integer
 * arithmetic, then formatted from the digits by the calculator's own formatter.
 */
export function formatRateINR(rate: string): string {
  const tenThousandths = rateToTenThousandths(rate);
  return formatPaiseINR(Math.floor((tenThousandths + 50) / 100));
}

/**
 * An amount for a sentence: `"50000.00"` → `"₹50,000"`, `"2500.50"` → `"₹2,500.50"`.
 * Whole rupees drop the `.00` — a pack is "the ₹50,000 pack", not "the ₹50,000.00 pack".
 */
export function formatAmountINR(amount: string): string {
  const paise = Math.floor((rateToTenThousandths(amount) + 50) / 100);
  const formatted = formatPaiseINR(paise);
  return paise % 100 === 0 ? formatted.slice(0, -3) : formatted;
}

/**
 * The pack that delivers this voice's "from" rate, or the last pack if none matches.
 *
 * PER VOICE since D-547, and it has to be: the two columns fall at different speeds
 * (Studio 7.00 → 5.50 against a FLAT Clear 4.00), so "the cheapest pack" is a question
 * with two answers and the old single-rate form silently answered the Sarvam one for both.
 * It matched on `effective_rate_inr_per_min`, a field that is now deprecated and holds the
 * Sarvam figure for unmigrated readers — which is exactly how a caller asking about the
 * dearer voice would have been handed the cheaper voice's pack and never noticed.
 */
export function cheapestPack(
  card: PublicRateCard,
  voice: VoiceTier,
): RateCardPack | undefined {
  const from = cardFromRate(card, voice);
  return (
    card.packs.find((pack) => packRate(pack, voice) === from) ??
    card.packs.at(-1)
  );
}

/**
 * Is this body the card the schema promises? Checked at the seam because the site
 * renders it with no session and no screen to catch a surprise on: a body that is
 * missing a field or carries a rate that is not a money string is treated exactly like
 * an unreachable API — "could not be loaded" — rather than printed.
 */
export function isRateCard(body: unknown): body is PublicRateCard {
  if (typeof body !== "object" || body === null) return false;
  const card = body as Record<string, unknown>;
  if (
    typeof card.list_rate_inr_per_min !== "string" ||
    !MONEY_STRING.test(card.list_rate_inr_per_min)
  )
    return false;
  if (
    typeof card.from_inr_per_min !== "string" ||
    !MONEY_STRING.test(card.from_inr_per_min)
  )
    return false;
  // The two "from" rates and the two tier names, which are what the pages LEAD with: a
  // missing one is a heading with `undefined` in it, and a blank label is a voice with no
  // name beside its price. Checked before the rows because a card that cannot introduce
  // its columns cannot honestly print them.
  for (const field of [
    "from_clear_inr_per_min",
    "from_studio_inr_per_min",
  ] as const) {
    if (
      typeof card[field] !== "string" ||
      !MONEY_STRING.test(card[field] as string)
    )
      return false;
  }
  for (const field of ["clear_tier_label", "studio_tier_label"] as const) {
    const label = card[field];
    if (typeof label !== "string" || label.trim() === "") return false;
  }
  if (!Array.isArray(card.packs) || card.packs.length === 0) return false;
  return card.packs.every((pack: unknown) => {
    if (typeof pack !== "object" || pack === null) return false;
    const row = pack as Record<string, unknown>;
    const money = (value: unknown): boolean =>
      typeof value === "string" && MONEY_STRING.test(value);
    const wholeMinutes = (value: unknown): boolean =>
      typeof value === "number" && Number.isInteger(value);
    return (
      typeof row.pack_id === "string" &&
      money(row.amount_inr) &&
      // BOTH rates and BOTH talk times, because both are rendered. The deprecated
      // `bonus_pct` / `effective_rate_inr_per_min` / `talk_time_minutes` are NOT checked
      // any more: nothing on this site reads them, they leave the wire next release
      // (plan §10), and a guard that refuses a card for a field nobody renders would take
      // the pricing page down on the release that removes them.
      money(row.clear_inr_per_min) &&
      money(row.studio_inr_per_min) &&
      wholeMinutes(row.clear_minutes) &&
      wholeMinutes(row.studio_minutes) &&
      typeof row.best_value === "boolean"
    );
  });
}

/**
 * The card, or `null` when it cannot honestly be shown.
 *
 * Every failure is logged as one line an operator can act on — the status when there was
 * one, the error's name when there was not — and nothing else: the request carries no
 * caller and the response carries no person, so there is nothing hard rule 6 could ask
 * this to redact.
 */
export async function fetchPublicRateCard(): Promise<PublicRateCard | null> {
  let body: unknown;
  try {
    body = await apiRequest<unknown>(NOBODY, PUBLIC_RATE_CARD_PATH);
  } catch (error) {
    const status = (error as { status?: number }).status;
    const name = error instanceof Error ? error.name : typeof error;
    console.error("public_rate_card_unavailable", {
      status: status ?? null,
      error: name,
    });
    return null;
  }
  if (!isRateCard(body)) {
    console.error("public_rate_card_malformed", {
      path: PUBLIC_RATE_CARD_PATH,
    });
    return null;
  }
  return body;
}
