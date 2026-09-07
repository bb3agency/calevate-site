"use client";

/**
 * THE RATE CARD, AS THE OPS CONSOLE READS IT — twelve cells, six rungs x two voices.
 *
 * ## Why this is a card and not a price
 *
 * `self_serve_inr_per_min` used to BE the self-serve price, and writing it was writing
 * what every client is charged. Since D-547 it is not: a minute costs what the LOT it is
 * spent from was sold at, and a lot's rates are frozen from the CARD in force when the
 * money arrived (`apps/api/billing/list_rates.py::record_card`). So the object an operator
 * has to see before they commit is the whole card — six pack rungs x two voice tiers —
 * and the act that dates it is one write, not twelve. There is no way to write one cell,
 * here or on the wire, and the panel says so rather than offering a control that has no
 * endpoint behind it.
 *
 * ## Vendor names stay ON THIS SCREEN
 *
 * Clients read "Clear" and "Studio" (`billing/rates.VOICE_TIER_LABELS`, served over the
 * wire). The admin console is the deliberate exception: an operator pasting a Cartesia key
 * or attesting a Cartesia invoice needs to know WHOSE key and WHOSE invoice, so every cell
 * here names the vendor AND the tier it serves. Neither name is invented in the browser —
 * `tier_label` crosses the wire beside the machine tier, exactly as it does on the public
 * card.
 *
 * ## Money, and the percentage
 *
 * Every rupee and every margin is the server's exact decimal STRING and is printed
 * verbatim. `gross_margin_pct` is the SERVER's percentage — this module never divides one
 * rounded rupee figure by another to produce one, because a margin computed in a browser
 * from two 4dp strings is a third answer to a question `billing/rates.rate_margin` has
 * already answered against the cost it was struck at.
 *
 * ## THIN IS A WARNING. IT IS NEVER A REFUSAL.
 *
 * The whole Sarvam column sits under the 20% target by design (17.6% down to 8.42%) and
 * above cost, and the founder signed that card. `card_refusals` refuses BELOW COST and
 * only REPORTS below target — so a screen that rendered "thin" as an error would be
 * refusing the card that is actually on sale. `cellVerdict` therefore has no "stop" tone
 * to give: `below_floor` is the server's refusal, rendered from the server's own sentence,
 * and `below_target` is a number an operator should read and act on, not a blocked save.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { ApiProblem } from "@/lib/api/client";
import { apiRequest } from "@/lib/api/client";
import { adminSession } from "@/lib/api/admin";

export const OPS_RATE_CARD_PATH = "/v1/ops/rate-card";
export const OPS_RATE_CARD_QUERY_KEY = ["admin", "ops", "rate-card"] as const;

/** The machine tier, spelled as the vendor it names — the lot's own vocabulary. */
export type VoiceTier = "sarvam" | "cartesia";

/**
 * One cell: one pack rung on one voice.
 *
 * Every money-shaped field is a decimal STRING. `gross_margin_pct` is `null` where the
 * server could not strike a margin (no cost to divide by) — a real state, and NOT zero.
 */
export interface RateCardCell {
  pack_id: string;
  amount_inr: string;
  voice_tier: VoiceTier;
  /** What a CLIENT calls this voice ("Clear" / "Studio"), from `VOICE_TIER_LABELS`. */
  tier_label: string;
  inr_per_min: string;
  /** What the minute costs us on this leg — the floor `card_refusals` refuses below. */
  cost_floor_inr_per_min: string;
  /** The server's percentage, e.g. `"17.60"`. Never derived here. */
  gross_margin_pct: string | null;
  /** Under the 20% target but above cost: a warning an operator reads, never a refusal. */
  below_target: boolean;
  /** Below cost. The card cannot be recorded at all — the server refuses the write. */
  below_floor: boolean;
}

export interface RateCard {
  /** When the card in force was dated, or `null` if this deployment has never dated one. */
  effective_from: string | null;
  /** The target the thin cells are thin against, as a percentage string, e.g. `"20"`. */
  target_gross_margin_pct: string;
  cells: RateCardCell[];
}

/** The vendor, named — this is the one surface where that is required rather than avoided. */
export const TIER_VENDOR: Record<VoiceTier, string> = {
  sarvam: "Sarvam",
  cartesia: "Cartesia",
};

export function tierVendor(tier: string): string {
  return tier === "sarvam" || tier === "cartesia" ? TIER_VENDOR[tier] : tier;
}

function money(value: unknown): value is string {
  return typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value.trim());
}

/**
 * THE SEAM. A cell that is not fully formed is DROPPED, not defaulted.
 *
 * The card read is being built by another lane, so this module validates every field it
 * renders rather than trusting the generated type: a missing `cost_floor_inr_per_min`
 * rendered as `0` would print a 100% margin on a cell that is actually under water. A
 * partial payload therefore yields fewer cells or `null`, and the panel renders a stated
 * absence — never a number nobody sent.
 */
export function asRateCardCell(raw: unknown): RateCardCell | null {
  if (typeof raw !== "object" || raw === null) return null;
  const cell = raw as Record<string, unknown>;
  const tier = cell.voice_tier;
  if (tier !== "sarvam" && tier !== "cartesia") return null;
  if (typeof cell.pack_id !== "string" || cell.pack_id === "") return null;
  if (typeof cell.tier_label !== "string" || cell.tier_label === "") return null;
  if (!money(cell.amount_inr) || !money(cell.inr_per_min)) return null;
  if (!money(cell.cost_floor_inr_per_min)) return null;
  if (typeof cell.below_target !== "boolean" || typeof cell.below_floor !== "boolean") return null;
  const pct = cell.gross_margin_pct;
  if (pct !== null && !money(pct)) return null;
  return {
    pack_id: cell.pack_id,
    amount_inr: cell.amount_inr,
    voice_tier: tier,
    tier_label: cell.tier_label,
    inr_per_min: cell.inr_per_min,
    cost_floor_inr_per_min: cell.cost_floor_inr_per_min,
    gross_margin_pct: pct,
    below_target: cell.below_target,
    below_floor: cell.below_floor,
  };
}

export function asRateCard(raw: unknown): RateCard | null {
  if (typeof raw !== "object" || raw === null) return null;
  const card = raw as Record<string, unknown>;
  if (!Array.isArray(card.cells) || card.cells.length === 0) return null;
  if (!money(card.target_gross_margin_pct)) return null;
  const cells = card.cells.map(asRateCardCell);
  // ALL OR NOTHING. A card missing a rung is not a smaller card — it is a card whose
  // twelve cells this build could not read, and half a price table is the one thing an
  // operator must not commit against.
  if (cells.some((cell) => cell === null)) return null;
  const effective = card.effective_from;
  return {
    effective_from: typeof effective === "string" && effective !== "" ? effective : null,
    target_gross_margin_pct: card.target_gross_margin_pct,
    cells: cells as RateCardCell[],
  };
}

/** The rungs, in the order the card ladders, each with its two voices. */
export interface RateCardRung {
  pack_id: string;
  amount_inr: string;
  cells: RateCardCell[];
}

export function rungs(card: RateCard): RateCardRung[] {
  const order: string[] = [];
  const byPack = new Map<string, RateCardRung>();
  for (const cell of card.cells) {
    const held = byPack.get(cell.pack_id);
    if (held) held.cells.push(cell);
    else {
      order.push(cell.pack_id);
      byPack.set(cell.pack_id, { pack_id: cell.pack_id, amount_inr: cell.amount_inr, cells: [cell] });
    }
  }
  return order.map((pack) => byPack.get(pack) as RateCardRung);
}

/**
 * What one cell's margin MEANS — two tones, and deliberately no third.
 *
 * `stop` is not reachable from here even for `below_floor`, and that is the point: below
 * cost is a server REFUSAL with the server's own sentence attached (`cardRefusalSentences`),
 * not a colour on a cell. What this returns is what an operator reads about a card that is
 * on sale.
 */
export interface CellVerdict {
  tone: "ok" | "thin";
  label: string;
  sentence: string;
}

export function cellVerdict(cell: RateCardCell, targetPct: string): CellVerdict {
  if (cell.below_target) {
    return {
      tone: "thin",
      label: "Thin margin",
      sentence:
        `This rung earns ${cell.gross_margin_pct ?? "an unstated"}% on the ` +
        `${tierVendor(cell.voice_tier)} voice, under the ${targetPct}% we aim for and above what ` +
        `the minute costs us (${cell.cost_floor_inr_per_min}/min). It is sold at this rate ` +
        "deliberately — read it, do not treat it as a fault.",
    };
  }
  return {
    tone: "ok",
    label: "At or above target",
    sentence:
      `${cell.gross_margin_pct ?? "—"}% on the ${tierVendor(cell.voice_tier)} voice, at or above ` +
      `the ${targetPct}% target.`,
  };
}

/**
 * The card was REFUSED — the server's own sentences, one per broken cell.
 *
 * `ops/config_routes._record_card` raises `rate_card_below_floor` with every refusal joined
 * by `"; "`, for two causes an operator acts on differently: a rate below its voice's cost
 * floor, and a card whose column stops falling as the packs get bigger (invariant 6). They
 * are rendered as the API's sentences, split back apart, because those name the pack, the
 * voice and the two numbers — a generic "the write failed" would send an operator to the
 * logs for a message the response already carried.
 */
export const RATE_CARD_REFUSAL_CODE = "rate_card_below_floor";

export function cardRefusalSentences(error: unknown): string[] | null {
  if (!(error instanceof ApiProblem) || error.code !== RATE_CARD_REFUSAL_CODE) return null;
  const colon = error.message.indexOf(": ");
  const body = colon >= 0 ? error.message.slice(colon + 2) : error.message;
  const sentences = body
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  return sentences.length > 0 ? sentences : [error.message];
}

/**
 * The card in force, read from the ops realm.
 *
 * Not polled tightly: a rate card moves when a person decides it does, and a poll that
 * clobbers a half-read table buys nothing. The panel re-reads after a config write, which
 * is the only act that dates a new one.
 */
export function useOpsRateCard(): UseQueryResult<unknown> {
  return useQuery({
    queryKey: OPS_RATE_CARD_QUERY_KEY,
    queryFn: () => apiRequest<unknown>(adminSession(), OPS_RATE_CARD_PATH),
    refetchInterval: 60_000,
  });
}
