"use client";

/**
 * CREDIT LOTS AND THE TWO VOICE QUALITIES — everything this hub reads that the generated
 * schema cannot yet describe, validated once, in one place (D-547).
 *
 * ## Why a module of readers rather than types
 *
 * D-547 lands across five lanes and `schema.d.ts` is regenerated ONCE over all of them, so
 * three of the payloads below are on the wire (or about to be) while the generated types
 * still describe the world before lots. Two ways out exist and only one of them is honest:
 * a `as Something` onto a generated wire type (which `tests/wireFixtureGuard.test.ts`
 * exists to stop, and which asserts a shape nobody checked), or a READER that takes
 * `unknown`, checks every field it is about to put on a screen, and returns `undefined`
 * when the answer is not sound. This is the second, and it is the same discipline
 * `lib/api/rateCard.ts::isRateCard` and `lib/api/voices.ts::readVoiceTierRates` already
 * apply at their own seams.
 *
 * The property every reader here holds: **a screen renders NOTHING rather than a wrong
 * number.** A half-validated lot queue would print a rupee figure a client checks against
 * their bank, and an absent field rendered as zero would tell somebody with credit that
 * they have none. So each reader is all-or-nothing over the whole payload — one bad row
 * drops the set, because a list showing three of four lots is a lie about a wallet.
 *
 * ## The two vocabularies, and which one may reach a human
 *
 * `sarvam` / `cartesia` name the VENDOR. They key the lot columns, the metering and the
 * ledger, and they are what a vendor invoice is reconciled against — so the wire keeps
 * them and so does this module. **No client-facing surface names a vendor as a product
 * tier** (founder, 7 Sep 2026): what a human reads is the tier LABEL ("Clear", "Studio"),
 * defined once in `apps/api/billing/rates.py::VOICE_TIER_LABELS` and CARRIED over the wire
 * beside every figure it names. Nothing here holds a copy of those names, and a payload
 * that arrives without them renders no name at all rather than falling back to the
 * vendor's word.
 *
 * ## Money
 *
 * Every rupee and every rate is an exact decimal STRING and stays one to the DOM (hard
 * rule 7). The one place a figure is turned into a number is `rateToTenThousandths`, the
 * exact integer reader `lib/api/rateCard.ts` already owns — imported rather than
 * re-spelled — and it is used only to COMPARE two amounts the server sent, never to add,
 * divide or re-price anything.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import { rateToTenThousandths } from "@/lib/api/rateCard";
import type { CreditPack, CreditPacks } from "@/lib/api/billing";

/**
 * The wire's name for a voice quality: the VENDOR. Keys money and metering; never rendered.
 * The same union `lib/api/rateCard.ts` and `lib/api/voices.ts` declare, for the same reason
 * — it is the API's vocabulary, not a name anyone reads.
 */
export type VoiceTier = "sarvam" | "cartesia";

/** Both qualities, in the order the card leads with them (the cheaper minute first). */
export const VOICE_TIERS: readonly VoiceTier[] = ["sarvam", "cartesia"];

/** What a CLIENT calls each quality. Only ever read from a response. */
export type TierLabels = Readonly<Record<VoiceTier, string>>;

/**
 * An exact decimal, unsigned, at most four places — `NUMERIC(12,4)` as JSON sends it.
 *
 * ⚠ THE THIRD SPELLING OF ONE RULE IN THIS TREE (`rateCard.ts` and `voices.ts` hold the
 * other two, each with the same note). Hoisting all three into one money module is a
 * HANDOFF, not a shortcut skipped: both of those files belong to other lanes this session
 * and a shared module has to be created by somebody who may edit them.
 */
const MONEY_STRING = /^\d+(\.\d{1,4})?$/;

function isMoney(value: unknown): value is string {
  return typeof value === "string" && MONEY_STRING.test(value);
}

function isFilledString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

/**
 * The two tier names carried by the pack card (`CreditPacksOut.sarvam_tier_label` /
 * `cartesia_tier_label`), or `undefined` when this API build sends neither.
 *
 * Read positionally off the body the hub already has rather than declared on
 * `CreditPacks`, because the generated type does not carry them until the shared
 * regeneration — the bridge `lib/api/rateCard.ts` documents for the public card, at the
 * signed-in end of the same response model.
 */
export function readTierLabels(payload: unknown): TierLabels | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const body = payload as Record<string, unknown>;
  const sarvam = body.sarvam_tier_label;
  const cartesia = body.cartesia_tier_label;
  if (!isFilledString(sarvam) || !isFilledString(cartesia)) return undefined;
  return { sarvam, cartesia };
}

/** One open lot: what is left of a purchase, and the two rates frozen on it. */
export type WalletLot = {
  lot_id: string;
  opened_at: string;
  credits_remaining: string;
  /** ₹/min per quality, frozen when the lot opened. Both always present. */
  rates: Readonly<Record<VoiceTier, string>>;
};

/** One quality's runway: the minutes THIS wallet's open lots still buy on it. */
export type TierRunway = {
  provider: VoiceTier;
  label: string;
  /** Whole minutes as the server floored them, or `null` when it cannot say. */
  minutes_left: string | null;
};

/** The wallet's lot queue, oldest first, and what it buys on each quality. */
export type WalletLots = {
  tiers: readonly TierRunway[];
  lots: readonly WalletLot[];
  /** What the wallet owes, "0.00" when it owes nothing. Never negative on the wire. */
  overdraft_inr: string;
};

export const WALLET_LOTS_PATH = "/v1/billing/wallet/lots";

/**
 * The lot queue, validated, or `undefined`.
 *
 * ⚠ **`GET /v1/billing/wallet/lots` IS NOT ON THE WIRE YET** — it is the billing lane's to
 * build and its exact shape is reported as a handoff rather than guessed at silently. Until
 * it answers, every panel below renders nothing at all: no runway pair, no lot list, and
 * emphatically not `minutes_left` from the wallet read, which divides one balance by one
 * LIST rate and is precisely the figure lots exist to stop being true.
 */
export function readWalletLots(payload: unknown): WalletLots | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const body = payload as Record<string, unknown>;

  if (!Array.isArray(body.tiers) || body.tiers.length !== VOICE_TIERS.length) return undefined;
  const tiers: TierRunway[] = [];
  for (const tier of VOICE_TIERS) {
    const row = body.tiers.find(
      (entry: unknown) =>
        typeof entry === "object" &&
        entry !== null &&
        (entry as Record<string, unknown>).provider === tier,
    ) as Record<string, unknown> | undefined;
    if (row === undefined) return undefined;
    if (!isFilledString(row.label)) return undefined;
    const minutes = row.minutes_left;
    if (minutes !== null && !isMoney(minutes)) return undefined;
    tiers.push({ provider: tier, label: row.label, minutes_left: minutes });
  }

  if (!Array.isArray(body.lots)) return undefined;
  const lots: WalletLot[] = [];
  for (const entry of body.lots) {
    if (typeof entry !== "object" || entry === null) return undefined;
    const row = entry as Record<string, unknown>;
    if (!isFilledString(row.lot_id) || !isFilledString(row.opened_at)) return undefined;
    if (!isMoney(row.credits_remaining)) return undefined;
    if (!isMoney(row.sarvam_inr_per_min) || !isMoney(row.cartesia_inr_per_min)) return undefined;
    lots.push({
      lot_id: row.lot_id,
      opened_at: row.opened_at,
      credits_remaining: row.credits_remaining,
      rates: { sarvam: row.sarvam_inr_per_min, cartesia: row.cartesia_inr_per_min },
    });
  }

  if (!isMoney(body.overdraft_inr)) return undefined;
  return { tiers, lots, overdraft_inr: body.overdraft_inr };
}

/**
 * The lot queue for this wallet.
 *
 * `retry: false`: on an API build that does not serve this route yet the answer is a 404
 * and three silent retries buy nothing but latency. A failure is not an error state on any
 * screen here — the panels simply do not render, which is the honest rendering of "we
 * cannot say what this wallet's lots are".
 */
export function useWalletLots(session: Session): UseQueryResult<unknown> {
  return useQuery({
    queryKey: ["wallet", session.orgSlug, "lots"],
    queryFn: () => apiRequest<unknown>(session, WALLET_LOTS_PATH),
    retry: false,
  });
}

/** One quality's share of a month: minutes spoken and the rupees they took off the wallet. */
export type VoiceUsageRow = {
  provider: VoiceTier;
  label: string;
  minutes: string;
  charges_inr: string;
};

/**
 * The per-quality month from `GET /v1/usage` (`UsagePanelOut.sarvam_minutes` and its five
 * siblings, `apps/api/crm/schemas.py`), or `undefined` on a build that sends none of them.
 *
 * The charges are the rupees the LOT SPLITS actually took off the wallet, so this panel and
 * the ledger cannot disagree about a month — and nothing is summed here: the month's total
 * is `month_charges_inr`, the server's own (D-458).
 */
export function readVoiceUsage(payload: unknown): readonly VoiceUsageRow[] | undefined {
  if (typeof payload !== "object" || payload === null) return undefined;
  const body = payload as Record<string, unknown>;
  const rows: VoiceUsageRow[] = [];
  for (const provider of VOICE_TIERS) {
    const label = body[`${provider}_label`];
    const minutes = body[`${provider}_minutes`];
    const charges = body[`${provider}_charges_inr`];
    if (!isFilledString(label) || !isMoney(minutes) || !isMoney(charges)) return undefined;
    rows.push({ provider, label, minutes, charges_inr: charges });
  }
  return rows;
}

/**
 * One part of a wallet debit, drawn from one lot at that lot's rate (plan §2.3 invariant 5,
 * ADDENDUM 2 §2.1).
 *
 * `kind` is an explicit discriminator and not a nullable field, for the reason the addendum
 * gives: an `ai_assist` split buys rupees of assistance, not minutes of talk, so it carries
 * NO `minutes`, NO rate and NO quality — absent keys rather than nulls somebody has to
 * interpret. A reader totting up talk time filters `kind === "call"`.
 */
export type LotSplit =
  | {
      kind: "call";
      lot_id: string;
      credits: string;
      minutes: string;
      inr_per_min: string;
      voice_tier: VoiceTier;
    }
  | { kind: "ai_assist"; lot_id: string; credits: string };

/**
 * The lot splits a wallet entry drew, or `undefined` when the row carries none we trust.
 *
 * ⚠ **`WalletEntryOut.lots` IS NOT ON THE WIRE YET** — reported as a handoff. The splits
 * exist today in the ledger row's `meta.lots`; publishing them on the client's own wallet
 * entry is the billing lane's to do, and until it does, a `usage` row simply does not
 * expand. An entry that is not a wallet debit legitimately has no splits, so `null` and an
 * absent key are both "nothing to expand" rather than a failure.
 */
export function readLotSplits(entry: unknown): readonly LotSplit[] | undefined {
  if (typeof entry !== "object" || entry === null) return undefined;
  const raw = (entry as Record<string, unknown>).lots;
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  const splits: LotSplit[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) return undefined;
    const row = item as Record<string, unknown>;
    if (!isFilledString(row.lot_id) || !isMoney(row.credits)) return undefined;
    if (row.kind === "ai_assist") {
      splits.push({ kind: "ai_assist", lot_id: row.lot_id, credits: row.credits });
      continue;
    }
    if (row.kind !== "call") return undefined;
    if (!isMoney(row.minutes) || !isMoney(row.inr_per_min)) return undefined;
    if (typeof row.voice_tier !== "string") return undefined;
    if (!VOICE_TIERS.includes(row.voice_tier as VoiceTier)) return undefined;
    splits.push({
      kind: "call",
      lot_id: row.lot_id,
      credits: row.credits,
      minutes: row.minutes,
      inr_per_min: row.inr_per_min,
      voice_tier: row.voice_tier as VoiceTier,
    });
  }
  return splits;
}

/** One pack's ₹/min on one quality — the ONE door, so no screen picks a field by hand. */
export function packRate(pack: CreditPack, tier: VoiceTier): string {
  return tier === "sarvam" ? pack.sarvam_inr_per_min : pack.cartesia_inr_per_min;
}

/** Whole minutes a pack's credits buy on one quality, as the server floored them. */
export function packMinutes(pack: CreditPack, tier: VoiceTier): number {
  return tier === "sarvam" ? pack.sarvam_minutes : pack.cartesia_minutes;
}

/**
 * WHICH PACK'S RATES A FREE-ENTRY AMOUNT BUYS AT (plan §0 Q3): the largest pack whose
 * price is at or below the amount typed, and the SMALLEST pack's for anything under the
 * first rung — the rule `billing/service.py::lot_rates_for_amount` implements, read there
 * rather than inferred from the plan's prose, which states the floor only by example.
 *
 * The server prices the top-up and remains the authority; this exists so the rates are on
 * screen BEFORE the button, because a purchase's terms are frozen the moment it lands and
 * a client who learns them afterwards cannot un-buy them. The comparison is exact-integer
 * over the digits the catalogue sent (`rateToTenThousandths` reads ten-thousandths of a
 * rupee, the API's own NUMERIC scale); nothing is added, multiplied or rounded, and no
 * rupee amount goes through a float.
 *
 * `undefined` only when the amount is not a money string or the catalogue is empty.
 */
export function packForAmount(
  packs: readonly CreditPack[],
  amountInr: string,
): CreditPack | undefined {
  if (!isMoney(amountInr)) return undefined;
  const wanted = rateToTenThousandths(amountInr);
  let smallest: CreditPack | undefined;
  let best: CreditPack | undefined;
  for (const pack of packs) {
    if (!isMoney(pack.amount_inr)) continue;
    const price = rateToTenThousandths(pack.amount_inr);
    if (smallest === undefined || price < rateToTenThousandths(smallest.amount_inr)) {
      smallest = pack;
    }
    if (price > wanted) continue;
    if (best === undefined || price > rateToTenThousandths(best.amount_inr)) best = pack;
  }
  return best ?? smallest;
}

/**
 * The DEAREST ₹/min any pack quotes on a quality — the entry rung of the ladder.
 *
 * Its partner, the cheapest, is a field the server publishes (`from_sarvam_inr_per_min`);
 * this end is not, and the explainer needs both to say "between X and Y". A comparison
 * between two figures the catalogue sent, computing no price of its own.
 */
export function dearestRate(card: CreditPacks, tier: VoiceTier): string | undefined {
  let dearest: string | undefined;
  for (const pack of card.packs) {
    const rate = packRate(pack, tier);
    if (!isMoney(rate)) continue;
    if (dearest === undefined || rateToTenThousandths(rate) > rateToTenThousandths(dearest)) {
      dearest = rate;
    }
  }
  return dearest;
}

/** The cheapest ₹/min the card delivers on a quality — the server's own "from" figure. */
export function cheapestRate(card: CreditPacks, tier: VoiceTier): string | undefined {
  const from =
    tier === "sarvam" ? card.from_sarvam_inr_per_min : card.from_cartesia_inr_per_min;
  return isMoney(from) ? from : undefined;
}

/**
 * A WHOLE COUNT read off an exact decimal string, grouped the Indian way: `"3200.0000"` →
 * `"3,200"`.
 *
 * Credits (1 credit = ₹1) and the per-quality runway both arrive as `NUMERIC` strings and
 * are both whole things to a client — nobody has 3,200.4 credits of calling or 1,080.85
 * minutes to plan around. Only the INTEGER PART is parsed, which is a safe `parseInt` on
 * digits; the whole decimal never goes through `Number` (hard rule 7), and the fraction is
 * dropped rather than rounded because rounding a runway UP quotes talk time the wallet
 * cannot cover.
 */
export function formatWhole(value: string): string {
  const [whole = "0"] = value.replace(/^[-+]/, "").split(".");
  const count = parseInt(whole, 10);
  if (Number.isNaN(count)) return value;
  return `${value.startsWith("-") ? "-" : ""}${count.toLocaleString("en-IN")}`;
}
