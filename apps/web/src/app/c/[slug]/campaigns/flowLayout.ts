/**
 * Where the call-flow canvas puts its boxes and how each link between them is drawn. Pure:
 * scenarios in, rectangles and SVG paths out, so the routing is tested without a browser.
 *
 * Columns left to right: the call's opening (column 0), then a column per step. Only a move
 * to the VERY NEXT step is a line, a curve inside the gap between the two columns. Every other
 * way out is a chip on the scenario it leaves (`exitsOf`): one to an end point (call back, end
 * of call, hand over), one back into the scenario itself, and one that jumps to any step but
 * the next, forward or back. Those jumps used to be orthogonal lines round padding lanes (React
 * Flow's smooth-step edge); on an eight-step script they ran as parallel strokes under every
 * card from one side of the canvas to the other, which an owner reading the flow cannot follow.
 * A chip says the same thing on the card it belongs to: "Cannot log in → 7.1 Call back".
 *
 * Two kinds of way on. An EXPLICIT link is a branch or an Otherwise the script holds. An
 * IMPLICIT link is the call's own order: a scenario with no Otherwise goes on to the next
 * step once that step's outcome is reached (`call_script.OUTCOMES_LEAD`; ThinnestAI takes the
 * steps as "the conversation script, in order" with no next field, update-agent.md:818-825,
 * snapshot 2026-10-29). It always runs to the very next column; one into a scenario the
 * source already links to is not drawn twice.
 */

import type { Placed } from "./scenarioModel";

export const BOX_W = 232;
export const BOX_H = 112;
export const COL_GAP = 88;
export const ROW_GAP = 18;
/** A step's heading: its name and "Scenario" button, then its outcome field. */
export const HEAD_H = 150;
/** How far outside a card a dragged link still lands on it. */
export const DROP_MARGIN = 16;
/** A step's band reaches `BAND_INSET` past its cards on each side, so the side padding must
 * hold it: with less, the first band and its heading start left of the canvas and are clipped
 * by the scroll box. */
export const BAND_INSET = COL_GAP / 2 - 8;
export const PAD_X = BAND_INSET + 12;
/** The least room between a column's heading and its first card. */
const TOP_GAP = 20;
/** Room right of the last step for its "Add step" button. */
const TAIL_W = 150;
/** The height one way-out chip adds to its card: a 20px chip and the gap above it. */
export const CHIP_LINE = 24;
/** The distance between two arrowheads on one card's left edge. */
const ENTRY_GAP = 14;
/** The space left under the lowest card. */
const FOOT = 56;

/** The opening's key among the links (never a section id: those are uuids or short slugs). */
export const OPENING_KEY = "@opening";

export type Point = { x: number; y: number };
export type Box = Point & { w: number; h: number };

const YES =
  /\b(yes|agrees?|accepts?|interested|okay|ok|sure|confirms?|ready|happy|installed|remembers?|knows?)\b/i;
const NO =
  /\b(no|not|don'?t|doesn'?t|refuses?|declines?|busy|later|can'?t|won'?t|never|wrong|forgot)\b/i;

export const YES_COLOR = "var(--series-1)";
export const NO_COLOR = "var(--series-3)";
const OTHER_COLOR = "var(--series-2)";
/** The call's own order: neutral, so it never reads as a way out somebody chose. */
export const THEN_COLOR = "var(--text-muted)";

/** The arrow's colour by the words of its way out: green yes, orange no, blue otherwise. */
export function toneColor(when: string): string {
  const yes = YES.test(when);
  const no = NO.test(when);
  if (yes && !no) return YES_COLOR;
  if (no && !yes) return NO_COLOR;
  return OTHER_COLOR;
}

/** A curve from a dot on the right of one box to the left edge of a box in the next column. */
export function curve(a: Point, b: Point): string {
  const bend = Math.max(48, Math.abs(b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + bend} ${a.y}, ${b.x - bend} ${b.y}, ${b.x} ${b.y}`;
}

/** Points along a cubic, for the hit tests (a cubic stays inside its control points' hull). */
function curvePoints(a: Point, b: Point): Point[] {
  const bend = Math.max(48, Math.abs(b.x - a.x) / 2);
  const c1 = { x: a.x + bend, y: a.y };
  const c2 = { x: b.x - bend, y: b.y };
  const out: Point[] = [];
  for (let i = 0; i <= 32; i++) {
    const t = i / 32;
    const u = 1 - t;
    out.push({
      x: u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x,
      y: u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y,
    });
  }
  return out;
}

export type LinkKind = "next";

export interface Routed {
  key: string;
  from: string;
  to: string;
  kind: LinkKind;
  d: string;
  /** Where the arrowhead's tip sits; every link enters its card from the left. */
  end: Point;
  color: string;
  /** `branch` and `otherwise` are the script's own ways out, `then` the implicit way on to
   * the next step, `opening` the opening's links. */
  via: LinkVia;
  /** Points along the drawn line, for the tests. */
  samples: Point[];
}

export type LinkVia = "branch" | "otherwise" | "then" | "opening";

/**
 * A way out of a scenario that is NOT drawn as a line: one to an end point, one back into the
 * scenario itself, or one to a scenario in any column but the next.
 */
export interface Exit {
  /** The same key the link has when it is drawn: `<id>-<branch index>` or `<id>-otherwise`. */
  key: string;
  target: string;
  /** The branch's own words; "" for an Otherwise. */
  when: string;
  via: "branch" | "otherwise";
}

export interface FlowLayout {
  colX: (column: number) => number;
  cardTop: number;
  /** The scenarios' boxes: what a dragged link can land on. */
  boxes: Map<string, Box>;
  /** Each scenario's ways out shown on its card rather than drawn. */
  exits: Map<string, Exit[]>;
  opening: Box | null;
  links: Routed[];
  width: number;
  height: number;
}

export interface OpeningInput {
  /** The end a caller who cannot talk now reaches (`CALL_BACK` or `END`): a chip on the
   * opening, so it adds one chip line to the first row. */
  notNow: string;
}

interface Edge {
  key: string;
  from: string;
  to: string;
  color: string;
  via: LinkVia;
}

/** A branch whose words only say "otherwise": the scenario's Otherwise in branch form. */
const OTHERWISE_WORDS = /^\s*(otherwise|else|anything else)\b/i;

/**
 * The ways out of a scenario that go on its card: every one to an end point in `ends`, every
 * one to a scenario outside the next column (`stepOf` gives a scenario's step), and a branch
 * back into itself. An Otherwise into itself is not one: "Otherwise stays on this step" is the
 * card's own Then line (`thenOf`), so a self-branch that only says "otherwise" is not repeated
 * as a chip beside it.
 */
export function exitsOf(
  item: Placed,
  ends: readonly string[],
  stepOf: (id: string) => number | undefined = () => undefined,
): Exit[] {
  const s = item.section;
  const jumps = (target: string) => {
    const step = stepOf(target);
    return step !== undefined && target !== s.id && step !== item.step + 1;
  };
  const out: Exit[] = s.branches.flatMap((b, j) => {
    const self = b.target === s.id;
    if (self && s.otherwise === s.id && OTHERWISE_WORDS.test(b.when)) return [];
    return ends.includes(b.target) || self || jumps(b.target)
      ? [{ key: `${s.id}-${j}`, target: b.target, when: b.when, via: "branch" as const }]
      : [];
  });
  if (s.otherwise && (ends.includes(s.otherwise) || jumps(s.otherwise)))
    out.push({ key: `${s.id}-otherwise`, target: s.otherwise, when: "", via: "otherwise" });
  return out;
}

/**
 * Lays the flow out. `ends` are the end-point targets, which are never boxes or lines;
 * `opening` adds the opening column, linked to every step-1 scenario.
 */
export function layoutFlow(
  items: Placed[],
  ends: readonly string[],
  opening: OpeningInput | null,
): FlowLayout {
  const steps = Math.max(0, ...items.map((p) => p.step));
  const first = opening ? 0 : 1;
  const colX = (column: number) => PAD_X + (column - first) * (BOX_W + COL_GAP);
  const stepOf = new Map(items.map((p) => [p.section.id, p.step]));
  const exits = new Map(
    items.map((p) => [p.section.id, exitsOf(p, ends, (id) => stepOf.get(id))]),
  );

  const edges: Edge[] = [];
  if (opening)
    for (const p of items.filter((q) => q.step === 1))
      edges.push({
        key: `${OPENING_KEY}-${p.section.id}`,
        from: OPENING_KEY,
        to: p.section.id,
        color: YES_COLOR,
        via: "opening",
      });
  // Only a move to a scenario in the next column is a line; everything else is a chip.
  const nextOf = (p: Placed, target: string) => stepOf.get(target) === p.step + 1;
  for (const p of items)
    p.section.branches.forEach((b, j) => {
      if (!nextOf(p, b.target)) return;
      edges.push({
        key: `${p.section.id}-${j}`,
        from: p.section.id,
        to: b.target,
        color: toneColor(b.when),
        via: "branch",
      });
    });
  for (const p of items) {
    if (p.section.otherwise) {
      if (nextOf(p, p.section.otherwise))
        edges.push({
          key: `${p.section.id}-otherwise`,
          from: p.section.id,
          to: p.section.otherwise,
          color: OTHER_COLOR,
          via: "otherwise",
        });
      continue;
    }
    const explicit = new Set(p.section.branches.map((b) => b.target));
    for (const q of items)
      if (q.step === p.step + 1 && !explicit.has(q.section.id))
        edges.push({
          key: `${p.section.id}~then~${q.section.id}`,
          from: p.section.id,
          to: q.section.id,
          color: THEN_COLOR,
          via: "then",
        });
  }

  const cardTop = HEAD_H + TOP_GAP;
  // Rows line up across columns, so a row is as tall as its card with the most chips.
  const tallest = Math.max(1, ...items.map((p) => p.row));
  const chipLines = Array.from({ length: tallest + 1 }, () => 0);
  for (const p of items)
    chipLines[p.row] = Math.max(chipLines[p.row], exits.get(p.section.id)?.length ?? 0);
  if (opening) chipLines[1] = Math.max(chipLines[1], 1);
  const rowH = (row: number) => BOX_H + (chipLines[row] ?? 0) * CHIP_LINE;
  const rowY = (row: number) => {
    let y = cardTop;
    for (let r = 1; r < row; r++) y += rowH(r) + ROW_GAP;
    return y;
  };

  const boxes = new Map<string, Box>();
  for (const p of items)
    boxes.set(p.section.id, { x: colX(p.step), y: rowY(p.row), w: BOX_W, h: rowH(p.row) });
  const openBox: Box | null = opening ? { x: colX(0), y: cardTop, w: BOX_W, h: rowH(1) } : null;
  const boxOf = (id: string) => (id === OPENING_KEY ? openBox : boxes.get(id)) ?? null;

  // Each link into a card has its own place on the card's left edge, in the order its source
  // sits from top to bottom, so two arrowheads never share a point. Links leave and enter at
  // the middle of a chipless card, so a row grown by chips keeps its lines level with the dot.
  const mid = (box: Box) => box.y + BOX_H / 2;
  const entry = new Map<string, number>();
  const into = new Map<string, Edge[]>();
  for (const e of edges) into.set(e.to, [...(into.get(e.to) ?? []), e]);
  for (const [to, list] of into) {
    const box = boxOf(to);
    if (!box) continue;
    const spread = Math.min(ENTRY_GAP, (BOX_H - 16) / Math.max(1, list.length - 1));
    [...list]
      .sort((p, q) => (boxOf(p.from)?.y ?? 0) - (boxOf(q.from)?.y ?? 0))
      .forEach((e, i) => entry.set(e.key, mid(box) + (i - (list.length - 1) / 2) * spread));
  }

  const links: Routed[] = [];
  for (const e of edges) {
    const from = boxOf(e.from);
    const to = boxOf(e.to);
    if (!from || !to) continue;
    const a = { x: from.x + from.w, y: mid(from) };
    const b = { x: to.x, y: entry.get(e.key) ?? mid(to) };
    links.push({
      key: e.key,
      from: e.from,
      to: e.to,
      kind: "next",
      color: e.color,
      via: e.via,
      d: curve(a, b),
      end: b,
      samples: curvePoints(a, b),
    });
  }

  const width = colX(steps + 1) + TAIL_W + PAD_X;
  const height = rowY(tallest) + rowH(tallest) + FOOT;

  return { colX, cardTop, boxes, exits, opening: openBox, links, width, height };
}

export type Then =
  | { kind: "otherwise"; target: string }
  | { kind: "stay" }
  | { kind: "step"; step: number }
  | { kind: "end" };

/**
 * Where a scenario goes once none of its ways out applies: its Otherwise when it has one
 * (`stay` when that is the scenario itself), else the next step, else the end of the call.
 * The canvas's label and its implicit link.
 */
export function thenOf(item: Placed, steps: number): Then {
  const otherwise = item.section.otherwise;
  if (otherwise === item.section.id) return { kind: "stay" };
  if (otherwise) return { kind: "otherwise", target: otherwise };
  return item.step < steps ? { kind: "step", step: item.step + 1 } : { kind: "end" };
}

/** The arrowhead at a link's end, pointing into the card's left edge. */
export function arrowHead(end: Point): string {
  return `M ${end.x - 8} ${end.y - 5} L ${end.x} ${end.y} L ${end.x - 8} ${end.y + 5} z`;
}
