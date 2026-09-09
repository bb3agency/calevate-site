"use client";

/**
 * THE RATE CARD, AS THE OPS CONSOLE READS IT — twelve cells, six rungs x two voices.
 *
 * It sat in `app/admin/ops/` while this read was another lane's to build; with the hand
 * validators collapsed onto `RateCardOut` it is a query hook, two wire aliases and the copy
 * a margin verdict reads in — the shape of `opsConfig.ts`, `opsModelPricing.ts` and
 * `opsFxRate.ts` beside it.
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

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { ApiProblem } from "@/lib/api/client";
import { apiRequest } from "@/lib/api/client";
import { adminSession } from "@/lib/api/admin";
import { formatISTInput } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

export const OPS_RATE_CARD_PATH = "/v1/ops/rate-card";
export const OPS_RATE_CARD_QUERY_KEY = ["admin", "ops", "rate-card"] as const;

/** The machine tier, spelled as the vendor it names — the lot's own vocabulary. */
export type VoiceTier = "sarvam" | "cartesia";

/**
 * One cell: one pack rung on one voice — `RateCardCellOut`, generated.
 *
 * Every money-shaped field is a decimal STRING. `gross_margin_pct` is `null` where the
 * server could not strike a margin (no cost to divide by) — a real state, and NOT zero.
 *
 * **THE LOCAL INTERFACE AND `asRateCardCell`/`asRateCard` ARE GONE.** They stood in while
 * this read was another lane's to build: every field was checked by hand so a missing
 * `cost_floor_inr_per_min` could not render as `0` and print a 100% margin on a cell that
 * is under water. `RateCardOut` now declares all of them REQUIRED, so the hand validator
 * re-checked only what the compiler proves, and the weaker of two spellings of one wire
 * contract is the one that eventually gets believed. What it CANNOT prove — that this
 * deployment answered at all — is still handled, by the panel's own read state.
 *
 * The one thing lost with the validator is worth naming: `voice_tier` is `string` on the
 * wire, not the two-member union, so nothing narrows it any more. `tierVendor` takes a
 * plain string and passes an unrecognised tier through unchanged, which is the same answer
 * it always gave.
 */
export type RateCardCell = Schemas["RateCardCellOut"];

/** The whole card: when it was dated, the margin target, and its twelve cells. */
export type RateCard = Schemas["RateCardOut"];

/**
 * **THE VOLUME EVERY CARTESIA COST FIGURE ON THE CARD IS STRUCK AT** — `CartesiaVolumeOut`.
 *
 * Aliased here beside `RateCardCell` so the panel names one thing rather than reaching
 * through `RateCard["cartesia_volume"]` at four call sites. Every field is the server's
 * decimal STRING or a stated `null`; nothing on this block is computed in the browser,
 * including the FX conversion, the cost ladder and the per-rung break-even.
 *
 * WHY IT EXISTS AT ALL: Studio is a monthly subscription with an included allotment and an
 * overage, so a per-minute cost is a function of volume. The console used to print the
 * cheapest such minute — reachable only at ~2,315 platform min/mo — under a column headed
 * "COSTS US", with no volume anywhere near it (founder, 9 Sep 2026).
 */
export type CartesiaVolume = Schemas["CartesiaVolumeOut"];

/** The vendor, named — this is the one surface where that is required rather than avoided. */
export const TIER_VENDOR: Record<VoiceTier, string> = {
  sarvam: "Sarvam",
  cartesia: "Cartesia",
};

export function tierVendor(tier: string): string {
  return tier === "sarvam" || tier === "cartesia" ? TIER_VENDOR[tier] : tier;
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
  // AT-VOLUME FIRST, because it is the worse and truer fact. A rung that clears the
  // structural floor and still sold a minute below what the month cost us is the state the
  // founder found the console hiding on 9 Sep 2026; a badge reading "at or above target"
  // over it would be the same lie in smaller type. Still `thin` and never `stop`: the
  // server records the card, and the remedy is usually volume rather than price.
  if (cell.below_floor_at_volume) {
    return {
      tone: "thin",
      label: "Under water at this volume",
      sentence:
        `This rung sells a ${tierVendor(cell.voice_tier)} minute at ${cell.inr_per_min} ` +
        `against ${cell.cost_inr_per_min_at_volume ?? "an unstated cost"}/min of real cost at ` +
        "the volume the platform actually ran this month. It clears the structural floor " +
        `(${cell.cost_floor_inr_per_min}/min, the next minute at the margin), so the card ` +
        "can still be recorded" +
        (cell.breakeven_call_minutes === null
          ? ", but no volume makes this rung profitable."
          : `. It needs ${cell.breakeven_call_minutes} platform minutes a month to stop ` +
            "losing money.") ,
    };
  }
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
 *
 * ⚠ **THE INTERVAL WENT FROM ONE MINUTE TO FIVE ON 9 SEP 2026, AND THE REASON IS ON THE
 * SERVER.** This read now also measures how many Studio call-minutes the whole platform
 * spoke this month, and `usage_events` is FORCE RLS'd — so the figure can only be had by
 * walking the client book one tenant session at a time (`billing/tts_volume.py`, the shape
 * the fleet spend board already uses). At sixty seconds an ops console left open on a desk
 * was a per-minute fleet walk for a number that moves with phone calls, not with the clock.
 * Five minutes costs an operator nothing — the card itself changes when somebody records
 * one, and that path invalidates this query directly — and takes a fifth of the database
 * time. The real fix if the client book outgrows this is the materialized monthly rollup
 * the walk's own over-budget log line names.
 */
export function useOpsRateCard(): UseQueryResult<RateCard> {
  return useQuery({
    queryKey: OPS_RATE_CARD_QUERY_KEY,
    queryFn: () => apiRequest<RateCard>(adminSession(), OPS_RATE_CARD_PATH),
    refetchInterval: 300_000,
  });
}

/* ══════════════════════════════════════════════════════════════════════════════════════
 * THE CARD AS A WRITE (D-550)
 *
 * The panel above this comment reads a card; everything below records one. The whole
 * surface is three acts — record a future card, withdraw a scheduled one, and read the
 * two numbers an operator needs before either (how soon a card may start, and how many
 * clients it will be announced to).
 *
 * ## The instant is spelled with an OFFSET, and that is load-bearing
 *
 * The step-up header the API checks is `record_rate_card:<effective_from.isoformat()>` —
 * the isoformat of the instant the SERVER parsed out of the body, not of the string this
 * console sent. Those two are equal only for a spelling Python round-trips unchanged.
 * `Date.prototype.toISOString()` is NOT one: it emits `2026-10-14T18:30:00.000Z`, which
 * `fromisoformat` parses and prints back as `2026-10-14T18:30:00+00:00`, so the header
 * would name an instant one character-string away from the one the handler computed and
 * every save would be refused with `step_up_required` — a refusal whose own screen tells
 * the operator to reload, which would never help.
 *
 * So a picked DAY becomes `YYYY-MM-DDT00:00:00+05:30` (`cardInstant`), and the header is
 * built from that exact string. It is midnight IST for `istDateToInstant`'s reason — a
 * calendar day named by a person in India is that day's first instant there, not UTC
 * midnight, which is 05:30 IST the same morning — and it is written rather than derived
 * because India has observed UTC+05:30 with no daylight saving since 1945.
 *
 * A CANCELLATION echoes the server's own `pending[].effective_from` VERBATIM for the
 * same reason: that string came out of `isoformat()`, so sending it back reproduces the
 * instant, and re-deriving it here would be a second spelling of one fact.
 *
 * ## Money never becomes a number
 *
 * Every rate the operator types is sent as the exact string they typed. `RateCardCellIn.
 * inr_per_min` is `number | string` on the wire (Pydantic's `Decimal`), and the API's own
 * validator REFUSES the number arm — "a JSON number is a binary float and cannot hold a
 * rupee amount" — so `CellDraft.inr_per_min` is `string` here and a float cannot be sent
 * from this console at all.
 */

/** A card recorded and not yet in force, as the read publishes it. */
export type PendingCard = Schemas["PendingCardOut"];

/** The answer to a recorded card: the instant, the twelve cells, and the notice promise. */
export type RateCardWrite = Schemas["RateCardWriteOut"];

/** The answer to a withdrawal. `cancelled: false` means it was already withdrawn. */
export type RateCardCancel = Schemas["RateCardCancelOut"];

/**
 * The scheduled cards, from a read that may not carry the field at all.
 *
 * `pending` is REQUIRED on `RateCardOut`, so the compiler proves a current API sends it.
 * This reader exists for the other API — a deployment serving the build from before
 * D-550, whose payload has no `pending` key — because the alternative is `card.pending.
 * map(...)` throwing inside render and taking the whole configuration screen down with
 * it. The parameter is deliberately WIDER than `RateCard` so no cast is needed and a
 * `RateCard` still satisfies it.
 */
export function pendingCards(card: {
  pending?: readonly PendingCard[] | null;
}): readonly PendingCard[] {
  return Array.isArray(card.pending) ? card.pending : [];
}

/**
 * How many clients a new card would be announced to, or `null` where the API did not say.
 *
 * NULL IS A REAL ANSWER AND IS RENDERED AS ONE. A console that showed `0` for "the field
 * was absent" would tell an operator that recording a card emails nobody, which is the
 * one sentence on this screen that must never be guessed (hard rule 11).
 */
export function noticeRecipients(card: { notice_recipients?: number | null }): number | null {
  return typeof card.notice_recipients === "number" ? card.notice_recipients : null;
}

/** The notice period in days, or `null` from an API that does not publish it. */
export function noticeDays(card: { notice_days?: number | null }): number | null {
  return typeof card.notice_days === "number" ? card.notice_days : null;
}

/**
 * The earliest DAY (IST, `YYYY-MM-DD`) whose midnight the server would accept.
 *
 * The API publishes an INSTANT — `now + notice_days` — and this screen picks a DAY that
 * is sent as midnight IST. Midnight of the instant's own IST date is EARLIER than the
 * instant on all but one second of the day, so offering that date would offer a day the
 * server refuses; the floor is therefore the next IST day unless the instant is itself
 * exactly midnight IST. Erring later is the only safe direction: a floor a day too early
 * is a refusal an operator cannot see coming, and a floor a day too late costs a day on a
 * change that is thirty days out.
 *
 * `null` when the API published no instant, which leaves the picker with no `min` — the
 * server is the real gate either way, and inventing a floor would be inventing a rule.
 */
export function earliestPickableDate(instant: string | null | undefined): string | null {
  if (!instant) return null;
  const at = new Date(instant);
  if (Number.isNaN(at.getTime())) return null;
  const istMidnight = formatISTInput(at.toISOString());
  if (istMidnight === "") return null;
  const [day = "", time = ""] = istMidnight.split("T");
  if (time === "00:00") return day;
  const next = new Date(`${day}T00:00:00+05:30`);
  next.setUTCDate(next.getUTCDate() + 1);
  return formatISTInput(next.toISOString()).split("T")[0] ?? null;
}

/**
 * A picked IST day as the instant the API is sent — and the one the step-up header names.
 *
 * NOT `istDateToInstant`, which is otherwise the right helper and is used everywhere else
 * on this console: it ends in `toISOString()`, and this one value has to survive a Python
 * `fromisoformat(...).isoformat()` round trip unchanged, because the server builds the
 * confirmation string from what it parsed. See the section header above.
 */
export function cardInstant(day: string): string | null {
  const typed = day.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(typed)) return null;
  const at = new Date(`${typed}T00:00:00+05:30`);
  return Number.isNaN(at.getTime()) ? null : `${typed}T00:00:00+05:30`;
}

/**
 * The step-up strings, copied VERBATIM from `apps/api/ops/config_routes.py`.
 *
 * Two of them, bound to the INSTANT, because the API binds them that way and says why: a
 * confirmation captured while scheduling a rise for December must not be replayable
 * against one that starts tomorrow week, and withdrawing a card is a different act from
 * recording one. Copied rather than derived, for `configConfirmation`'s reason — this is a
 * property of the request being sent, and a mismatch is REFUSED by the server.
 */
export function recordCardConfirmation(effectiveFrom: string): string {
  return `record_rate_card:${effectiveFrom}`;
}

export function cancelCardConfirmation(effectiveFrom: string): string {
  return `cancel_rate_card:${effectiveFrom}`;
}

/** One cell of a card being drafted. The rate is the operator's exact typed string. */
export interface CellDraft {
  pack_id: string;
  voice_tier: string;
  inr_per_min: string;
}

export interface RecordCardInput {
  /** The instant, offset-spelled, from `cardInstant`. */
  effectiveFrom: string;
  reason: string;
  cells: readonly CellDraft[];
}

export function useRecordRateCard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ effectiveFrom, reason, cells }: RecordCardInput) =>
      apiRequest<RateCardWrite>(adminSession(), OPS_RATE_CARD_PATH, {
        method: "POST",
        body: {
          effective_from: effectiveFrom,
          reason,
          // The typed strings, unchanged. No `Number()` anywhere on this path.
          cells: cells.map((cell) => ({
            pack_id: cell.pack_id,
            voice_tier: cell.voice_tier,
            inr_per_min: cell.inr_per_min,
          })),
        },
        confirmAction: recordCardConfirmation(effectiveFrom),
      }),
    // Re-read rather than splicing the response in. A recorded card changes `pending`,
    // and it can change `earliest_effective_from` and the card in force too (a date that
    // has since arrived), so a console that patched one field would show a fresh card
    // inside a stale page — `useSetConfig`'s argument, one surface along.
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_RATE_CARD_QUERY_KEY }),
  });
}

export interface CancelCardInput {
  /** The server's own `pending[].effective_from`, echoed back unchanged. */
  effectiveFrom: string;
  reason: string;
}

export function useCancelRateCard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ effectiveFrom, reason }: CancelCardInput) =>
      apiRequest<RateCardCancel>(adminSession(), `${OPS_RATE_CARD_PATH}/cancellations`, {
        method: "POST",
        body: { effective_from: effectiveFrom, reason },
        confirmAction: cancelCardConfirmation(effectiveFrom),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: OPS_RATE_CARD_QUERY_KEY }),
  });
}

/* ── what a rate MOVED by, computed without ever parsing one ────────────────────────── */

/**
 * A decimal STRING as an integer and the scale it was written at. `null` when the string
 * is not a plain decimal — which is what a half-typed box holds most of the time.
 *
 * This is the whole of the arithmetic on this screen, and it exists so that the delta
 * beside a cell can be exact. `Number("4.85")` is the one thing hard rule 7 forbids, and a
 * delta computed that way prints `0.30000000000000004` next to a rupee figure an operator
 * is about to commit. Integers scaled by the decimal places are exact for subtraction,
 * and `BigInt` cannot overflow at any rupee amount this platform will ever hold.
 */
// `BigInt(n)` rather than the `0n` literal form: `tsconfig.json` targets ES2017, where
// TypeScript refuses the literal syntax (TS2737). The RUNTIME value is the same object —
// every browser this console supports has had `BigInt` since 2020 — so this is a syntax
// accommodation and not a different kind of number.
const ZERO = BigInt(0);
const TWO = BigInt(2);
const TEN = BigInt(10);
const PERCENT_SCALE = BigInt(10000);

interface ScaledDecimal {
  units: bigint;
  scale: number;
}

function scaledDecimal(value: string): ScaledDecimal | null {
  const typed = value.trim();
  if (!/^-?\d+(\.\d+)?$/.test(typed)) return null;
  const negative = typed.startsWith("-");
  const [whole = "0", fraction = ""] = typed.replace(/^-/, "").split(".");
  const units = BigInt(`${whole}${fraction}`);
  return { units: negative ? -units : units, scale: fraction.length };
}

/** The two figures at a common scale — the only thing a subtraction needs. */
function aligned(a: ScaledDecimal, b: ScaledDecimal): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  const lift = (value: ScaledDecimal) => value.units * TEN ** BigInt(scale - value.scale);
  return [lift(a), lift(b), scale];
}

/** An integer scaled by `scale` back to the decimal string it stands for. */
function unscale(units: bigint, scale: number): string {
  const negative = units < ZERO;
  const digits = (negative ? -units : units).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale === 0 ? "" : `.${digits.slice(digits.length - scale)}`;
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

/** Which way a rate moved, by how much, and by what percentage of the old rate. */
export interface RateDelta {
  direction: "up" | "down" | "same";
  /** The absolute difference, exact, at the finer of the two scales ("0.5000"). */
  amount: string;
  /** The move as a percentage of the old rate, to two decimals. `null` from a zero base. */
  percent: string | null;
}

/**
 * What one cell moved by, from the two decimal strings — never from two numbers.
 *
 * `null` when either side is not a decimal (an empty or half-typed box), which the panel
 * renders as no delta rather than as "unchanged": those are different statements, and the
 * second one would be a claim about a value nobody has finished typing.
 *
 * The PERCENTAGE is the one figure here that cannot be exact, and it is rounded half-up at
 * two decimals inside integer arithmetic rather than by a float division. It is a reading
 * aid beside an exact rupee delta, and it is never sent anywhere: what the API receives is
 * the typed rate alone.
 */
export function rateDelta(from: string, to: string): RateDelta | null {
  const before = scaledDecimal(from);
  const after = scaledDecimal(to);
  if (!before || !after) return null;
  const [a, b, scale] = aligned(before, after);
  const diff = b - a;
  if (diff === ZERO) return { direction: "same", amount: unscale(ZERO, scale), percent: "0.00" };
  const magnitude = diff < ZERO ? -diff : diff;
  const base = a < ZERO ? -a : a;
  // Half-up on the last kept digit, done on integers: `(2·num + den) / (2·den)`.
  const percent =
    base === ZERO ? null : unscale((magnitude * PERCENT_SCALE * TWO + base) / (base * TWO), 2);
  return { direction: diff > ZERO ? "up" : "down", amount: unscale(magnitude, scale), percent };
}

/**
 * The rate in force for one cell of a card, or `null` when that card has no such cell.
 *
 * Absent rather than zero, for the reason the whole panel is built on: a missing cell must
 * read as "we have nothing to compare against", never as "it used to be free".
 */
export function rateOf(
  card: { cells: readonly RateCardCell[] },
  packId: string,
  voiceTier: string,
): string | null {
  const found = card.cells.find(
    (cell) => cell.pack_id === packId && cell.voice_tier === voiceTier,
  );
  return found ? found.inr_per_min : null;
}

/* ── the four refusals, each with an operator-actionable sentence ────────────────────── */

/**
 * WHAT THE SERVER SAID NO TO, and what the operator does about it.
 *
 * Four codes, four different acts. They are separated rather than funnelled into one red
 * box because the remedy differs every time: a card that starts too soon needs a later
 * DATE (and the earliest one is a fact this screen already holds), a card below cost needs
 * a higher RATE in a named cell, a malformed card is a bug in this console, and a date
 * already scheduled needs the existing card withdrawn first — which is a button on this
 * same panel.
 *
 * The server's own `detail` is always rendered alongside: it names the pack, the voice and
 * both numbers, and a paraphrase would be the version people argue with. `remediation` is
 * the API's own next step and is printed when it sent one.
 */
export interface CardRefusal {
  code: string;
  title: string;
  /** This console's sentence — what to do, in the operator's own terms. */
  advice: string;
  /** The server's `detail`, split where it carries several causes. */
  sentences: string[];
}

const REFUSAL_TITLES: Record<string, string> = {
  rate_card_too_soon: "This card starts too soon — nothing was saved",
  rate_card_below_floor: "The rate card was refused — nothing was saved",
  rate_card_malformed: "This is not a whole card — nothing was saved",
  rate_card_already_scheduled: "A card already starts on that date — nothing was saved",
  rate_card_not_scheduled: "There is no card to withdraw",
  rate_card_already_in_force: "That card has already taken effect",
};

/**
 * The refusal a rate-card write hit, or `null` for anything else — a 500, a timeout, a
 * step-up skew — which `WriteFailure` already renders and which this must not swallow.
 */
export function cardRefusal(error: unknown, earliestDay: string | null): CardRefusal | null {
  if (!(error instanceof ApiProblem)) return null;
  const title = lookup(REFUSAL_TITLES, error.code);
  if (title === undefined) return null;
  return { code: error.code, title, advice: refusalAdvice(error, earliestDay), sentences: detailOf(error) };
}

function refusalAdvice(error: ApiProblem, earliestDay: string | null): string {
  if (error.code === "rate_card_too_soon") {
    return earliestDay === null
      ? "Clients are given notice before their rates move, so a card has to start far enough ahead. Pick a later date — the read above publishes the earliest one this deployment accepts."
      : `Clients are given notice before their rates move. The earliest date this deployment will accept is ${earliestDay} — pick that or later and save again.`;
  }
  if (error.code === "rate_card_below_floor") {
    return "Raise the rates named below. A minute may not be sold for less than it costs us, and a bigger pack may never buy a dearer minute than a smaller one.";
  }
  if (error.code === "rate_card_malformed") {
    return "This is a fault in the console, not in what you typed: a card is sent whole, every pack on both voices. Reload the page and try once; if it happens again, say so in the deploy channel rather than working around it.";
  }
  if (error.code === "rate_card_already_scheduled") {
    return "Withdraw the card already scheduled for that date first — it has not taken effect, so nothing has been priced at it — then record this one. Or pick a different date.";
  }
  if (error.code === "rate_card_already_in_force") {
    return "A card can only be withdrawn before its date. Record a new card with the rates you want instead.";
  }
  return "The card scheduled for that date is no longer there — reload the page to see what is actually scheduled.";
}

/** The server's `detail`, split on the joiner `_record_card` uses for several causes. */
function detailOf(error: ApiProblem): string[] {
  const colon = error.message.indexOf(": ");
  const body = colon >= 0 ? error.message.slice(colon + 2) : error.message;
  const sentences = body
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  return sentences.length > 0 ? sentences : [error.message];
}
