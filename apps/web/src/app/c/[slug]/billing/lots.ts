"use client";

/**
 * CREDIT LOTS AND THE TWO VOICE QUALITIES — the hub's one door onto each (D-547).
 *
 * ## THIS WAS A MODULE OF `unknown` READERS, AND MOST OF THEM ARE GONE
 *
 * D-547 landed across five lanes and `schema.d.ts` was regenerated ONCE over all of them,
 * so for one release the payloads below were on the wire while the generated types still
 * described the world before lots. The honest bridge then was a READER that took
 * `unknown`, checked every field it was about to put on a screen and answered `undefined`
 * otherwise — never an `as` onto a generated type, which `tests/wireFixtureGuard.test.ts`
 * exists to stop.
 *
 * The regeneration has happened. `WalletLotsOut`, `CreditPacksOut` and `UsagePanelOut` now
 * declare every one of those fields, REQUIRED, so `readWalletLots`, `readTierLabels` and
 * `readVoiceUsage` were re-checking exactly what the compiler proves — and the weaker of
 * two spellings of one wire contract is the one that eventually gets believed. What is
 * left here is the part a type cannot do: the ACCESSORS that pick a vendor-named field by
 * quality (so no screen writes `sarvam_inr_per_min` by hand), the money comparisons, and
 * `readLotSplits`, whose payload is still an untyped dict on the wire (see it for why).
 *
 * The property the survivors keep: **a screen renders NOTHING rather than a wrong number.**
 * An absent figure rendered as zero would tell somebody with credit that they have none.
 *
 * ## WHY THIS ONE DID NOT MOVE TO `lib/api/`
 *
 * Its three admin-side siblings did, once their validators collapsed: what was left of each
 * was a hook and a wire alias. This module is not that. Beside the lot query it holds
 * `formatWhole`, `packForAmount`, `dearestRate` and the two pack accessors — presentation
 * and buying-decision logic that nine components in this one directory import, and that no
 * other realm has any use for. Moving it would either drag that into `lib/api/`, where
 * nothing else like it lives, or split one module into two and touch all nine importers to
 * buy nothing. It stays, and this paragraph is the reason rather than an omission.
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
import { isMoneyString } from "@/lib/money";
import type { CreditPack, CreditPacks } from "@/lib/api/billing";
import type { UsagePanel } from "@/lib/api/hooks";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

/** A string that actually says something — an empty id is an absent id. */
function isFilledString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

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
 * The two tier names carried by the pack card (`CreditPacksOut.sarvam_tier_label` /
 * `cartesia_tier_label`), or `undefined` when the card has not arrived — or when it
 * arrived without them.
 *
 * It replaced `readTierLabels(unknown)`, which read the two names positionally while the
 * generated type did not carry them, and it takes the typed card instead. **THE EMPTINESS
 * CHECK IS KEPT DELIBERATELY**, though both fields are REQUIRED on the wire and this is
 * therefore unreachable through a well-behaved server. Two reasons, and the second is the
 * binding one:
 *
 *  - the failure it prevents is not a blank, it is the string `"undefined"` rendered into
 *    a sentence a client reads about what they are buying;
 *  - every caller uses this answer to decide whether to print a PER-MINUTE RATE at all, and
 *    the only other name available for a quality is the VENDOR's — the one name a
 *    client-facing surface may not print (founder, 7 Sep 2026). So a card that cannot name
 *    its two qualities prices neither of them, which is what `TopUp` and the hub do.
 */
export function tierLabels(card: CreditPacks | undefined): TierLabels | undefined {
  if (card === undefined) return undefined;
  const sarvam = card.sarvam_tier_label;
  const cartesia = card.cartesia_tier_label;
  if (!isFilledString(sarvam) || !isFilledString(cartesia)) return undefined;
  return { sarvam, cartesia };
}

/** One open lot: what is left of a purchase, and the two rates frozen on it. */
export type WalletLot = Schemas["WalletLotOut"];

/** One quality's runway: the minutes THIS wallet's open lots still buy on it. */
export type TierRunway = Schemas["WalletTierRunwayOut"];

/** The wallet's lot queue, oldest first, and what it buys on each quality. */
export type WalletLots = Schemas["WalletLotsOut"];

/**
 * One lot's ₹/min on one quality — THE ONE DOOR, so no screen picks a vendor-named field
 * by hand. The sibling of `packRate` below, and the reason the flat wire shape does not
 * leak into the table that renders it.
 */
export function lotRate(lot: WalletLot, tier: VoiceTier): string {
  return tier === "sarvam" ? lot.sarvam_inr_per_min : lot.cartesia_inr_per_min;
}

/**
 * The runway row for one quality, or `undefined` — the join between the wire's vendor
 * vocabulary and the NAME a client may read.
 *
 * `WalletTierRunwayOut.provider` is a bare `string` on the wire, not the two-member union,
 * so this is the one place a server-sent provider is matched against a quality we know how
 * to price. A quality the server did not send simply has no row, and a screen prints no
 * name for it rather than falling back to the vendor's word.
 */
export function tierRunway(lots: WalletLots, tier: VoiceTier): TierRunway | undefined {
  return lots.tiers.find((row) => row.provider === tier);
}

export const WALLET_LOTS_PATH = "/v1/billing/wallet/lots";

/**
 * The lot queue for this wallet.
 *
 * **`readWalletLots(unknown)` IS GONE.** It stood in while `GET /v1/billing/wallet/lots`
 * was the billing lane's to build: it checked every rate and every label by hand so that a
 * build whose API could not answer rendered no lot list, no runway pair and no rate at all.
 * The route is on the wire and `WalletLotsOut` declares all of it, so the read is typed and
 * the panels take it directly. What has NOT changed is the honest failure below.
 *
 * `retry: false`: a failure is not an error state on any screen here — the panels simply do
 * not render, which is the honest rendering of "we cannot say what this wallet's lots are".
 * Emphatically never `wallet.minutes_left` instead, which divides one balance by one LIST
 * rate and is the arithmetic lots exist to retire.
 */
export function useWalletLots(session: Session): UseQueryResult<WalletLots> {
  return useQuery({
    queryKey: ["wallet", session.orgSlug, "lots"],
    queryFn: () => apiRequest<WalletLots>(session, WALLET_LOTS_PATH),
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
 * The per-quality month, off the typed usage read.
 *
 * The charges are the rupees the LOT SPLITS actually took off the wallet, so this panel and
 * the ledger cannot disagree about a month — and nothing is summed here: the month's total
 * is `month_charges_inr`, the server's own (D-458).
 *
 * **`readVoiceUsage(unknown)` IS GONE.** The six fields it read positionally
 * (`sarvam_minutes` and its five siblings) are generated and REQUIRED on `UsagePanelOut`,
 * so what is left is the projection into the rows the panel iterates — the vendor-keyed
 * fields picked by quality in ONE place, never in the JSX.
 */
export function voiceUsage(usage: UsagePanel | undefined): readonly VoiceUsageRow[] | undefined {
  if (usage === undefined) return undefined;
  return [
    {
      provider: "sarvam",
      label: usage.sarvam_label,
      minutes: usage.sarvam_minutes,
      charges_inr: usage.sarvam_charges_inr,
    },
    {
      provider: "cartesia",
      label: usage.cartesia_label,
      minutes: usage.cartesia_minutes,
      charges_inr: usage.cartesia_charges_inr,
    },
  ];
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
 * **THE ONE READER IN THIS MODULE THAT SURVIVES THE REGENERATION, AND IT HAS TO.**
 * `WalletEntryOut.lots` is on the wire now — and its generated type is
 * `{ [key: string]: string }[]`, an untyped dict, because the row is a JSON blob the ledger
 * carries rather than a modelled object. So the compiler knows only that every value is a
 * string; it cannot tell a `call` split from an `ai_assist` one, cannot see that a `call`
 * split carries `minutes` and a rate while an `ai_assist` split carries neither, and cannot
 * say that a rate is an exact decimal rather than any old text. Those are exactly the
 * distinctions a client's screen prints, so they are checked here, at the seam, and a row
 * that fails is dropped WHOLE — a debit expanded into half its parts is a lie about where
 * the money went.
 *
 * An entry that is not a wallet debit legitimately has no splits, so an empty list is
 * "nothing to expand" rather than a failure.
 */
export function readLotSplits(entry: unknown): readonly LotSplit[] | undefined {
  if (typeof entry !== "object" || entry === null) return undefined;
  const raw = (entry as Record<string, unknown>).lots;
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  const splits: LotSplit[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) return undefined;
    const row = item as Record<string, unknown>;
    if (!isFilledString(row.lot_id) || !isMoneyString(row.credits)) return undefined;
    if (row.kind === "ai_assist") {
      splits.push({ kind: "ai_assist", lot_id: row.lot_id, credits: row.credits });
      continue;
    }
    if (row.kind !== "call") return undefined;
    if (!isMoneyString(row.minutes) || !isMoneyString(row.inr_per_min)) return undefined;
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
  if (!isMoneyString(amountInr)) return undefined;
  const wanted = rateToTenThousandths(amountInr);
  let smallest: CreditPack | undefined;
  let best: CreditPack | undefined;
  for (const pack of packs) {
    if (!isMoneyString(pack.amount_inr)) continue;
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
    if (!isMoneyString(rate)) continue;
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
  return isMoneyString(from) ? from : undefined;
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
