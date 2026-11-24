/**
 * Where the call-flow canvas puts its boxes and how each link between them is drawn. Pure:
 * scenarios in, rectangles and SVG paths out, so the routing is tested without a browser.
 *
 * Columns left to right: the call's opening (column 0), then a column per step, then the end
 * points. A link to the very next column is a curve inside the gap between the two columns,
 * as before. Any other link is ORTHOGONAL with rounded corners, the "smooth step" edge of
 * React Flow (`getSmoothStepPath`, reactflow.dev/api-reference/utils/get-smooth-step-path)
 * that n8n also uses for a connection whose target sits left of its source: n8n takes it out
 * of the source, round a padding lane clear of the node and back into the target's input
 * (`getEdgeRenderData.ts`, EDGE_PADDING_BOTTOM 130 / EDGE_PADDING_X 40, n8n-io/n8n master,
 * read 24 Nov 2026). A curve drawn instead from one card's right edge to an earlier card's
 * left edge has both control points on the same row when the rows match, so it runs straight
 * through every card in between, hidden behind them, and comes in from the canvas's left
 * edge with no visible source; one that skips a column runs behind the middle card and
 * surfaces beside that card's own dot, reading as a link the middle card does not have.
 *
 * The lanes:
 *  - a link that goes BACK (to the same or an earlier step) rises in the gap right of its
 *    source column into the return lane above the cards, runs left and drops in the gap left
 *    of its target into the target's left edge;
 *  - a link that SKIPS a step leaves in the gap right of its source, runs along the gap
 *    between two rows (rows line up across columns, so that gap holds no card) and rises or
 *    drops in the gap left of its target.
 * Each vertical run takes its own lane in its gap and each horizontal run its own lane in its
 * channel, so two links never draw on top of each other.
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
export const END_W = 150;
export const END_H = 40;
/** Room between the opening and the end its "not now" arrow points to. */
export const NOT_NOW_GAP = 44;
/** The distance between two links running side by side in one gap. */
export const LANE = 7;
/** The distance between two arrowheads on one card's left edge. */
const ENTRY_GAP = 14;
/** The radius of an orthogonal link's corners. */
const CORNER = 6;
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

/** An orthogonal polyline as a path whose corners are rounded (never past half a segment). */
function rounded(points: Point[]): string {
  const pts = points.filter(
    (p, i) => i === 0 || p.x !== points[i - 1].x || p.y !== points[i - 1].y,
  );
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [p, c, n] = [pts[i - 1], pts[i], pts[i + 1]];
    const r = Math.min(
      CORNER,
      Math.hypot(c.x - p.x, c.y - p.y) / 2,
      Math.hypot(n.x - c.x, n.y - c.y) / 2,
    );
    const into = toward(c, p, r);
    const out = toward(c, n, r);
    d += ` L ${into.x} ${into.y} Q ${c.x} ${c.y} ${out.x} ${out.y}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

function toward(from: Point, to: Point, r: number): Point {
  const len = Math.hypot(to.x - from.x, to.y - from.y) || 1;
  return { x: from.x + ((to.x - from.x) / len) * r, y: from.y + ((to.y - from.y) / len) * r };
}

/** Every 4 px along an orthogonal polyline, for the hit tests. */
function along(points: Point[]): Point[] {
  const out: Point[] = [points[0]];
  for (let i = 1; i < points.length; i++) {
    const [p, c] = [points[i - 1], points[i]];
    const steps = Math.max(1, Math.ceil(Math.hypot(c.x - p.x, c.y - p.y) / 4));
    for (let s = 1; s <= steps; s++)
      out.push({ x: p.x + ((c.x - p.x) * s) / steps, y: p.y + ((c.y - p.y) * s) / steps });
  }
  return out;
}

export type LinkKind = "next" | "skip" | "back" | "not-now";

export interface Routed {
  key: string;
  from: string;
  to: string;
  kind: LinkKind;
  d: string;
  /** Where the arrowhead's tip sits, and which way it points. */
  end: Point;
  dir: "right" | "down";
  color: string;
  /** Points along the drawn line, for the tests. */
  samples: Point[];
}

export interface FlowLayout {
  colX: (column: number) => number;
  cardTop: number;
  /** Scenarios and the end points of the step columns: what a dragged link can land on. */
  boxes: Map<string, Box>;
  usedEnds: string[];
  opening: Box | null;
  /** Where the opening's "not now" goes, drawn under the opening. */
  notNow: { target: string; box: Box } | null;
  links: Routed[];
  width: number;
  height: number;
}

export interface OpeningInput {
  /** The end a caller who cannot talk now reaches (`CALL_BACK` or `END`). */
  notNow: string;
}

interface Edge {
  key: string;
  from: string;
  to: string;
  color: string;
  fromCol: number;
  toCol: number;
  fromRow: number;
  toRow: number;
}

/**
 * Lays the flow out. `ends` are the end-point targets in the order they are drawn;
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
  const usedEnds = ends.filter((t) =>
    items.some((p) => p.section.branches.some((b) => b.target === t)),
  );
  const endCol = steps + 1;
  const where = new Map<string, { col: number; row: number }>();
  for (const p of items) where.set(p.section.id, { col: p.step, row: p.row });
  usedEnds.forEach((t, i) => where.set(t, { col: endCol, row: i + 1 }));

  const edges: Edge[] = [];
  if (opening)
    for (const p of items.filter((q) => q.step === 1))
      edges.push({
        key: `${OPENING_KEY}-${p.section.id}`,
        from: OPENING_KEY,
        to: p.section.id,
        color: YES_COLOR,
        fromCol: 0,
        toCol: 1,
        fromRow: 1,
        toRow: p.row,
      });
  for (const p of items)
    p.section.branches.forEach((b, j) => {
      const to = where.get(b.target);
      if (!to) return;
      edges.push({
        key: `${p.section.id}-${j}`,
        from: p.section.id,
        to: b.target,
        color: toneColor(b.when),
        fromCol: p.step,
        toCol: to.col,
        fromRow: p.row,
        toRow: to.row,
      });
    });
  const kindOf = (e: Edge): LinkKind =>
    e.toCol === e.fromCol + 1 ? "next" : e.toCol > e.fromCol ? "skip" : "back";

  // Lanes. A back link has its own height in the return lane; a skip link its own height in
  // the gap below row `min(fromRow, toRow)`; each vertical run its own place in its gap.
  const back = edges.filter((e) => kindOf(e) === "back");
  const skip = edges.filter((e) => kindOf(e) === "skip");
  const channel = (e: Edge) => Math.min(e.fromRow, e.toRow);
  const inChannel = new Map<number, Edge[]>();
  for (const e of skip) inChannel.set(channel(e), [...(inChannel.get(channel(e)) ?? []), e]);
  const widest = Math.max(1, ...[...inChannel.values()].map((l) => l.length));
  const rowGap = Math.max(ROW_GAP, (widest + 1) * LANE);
  const cardTop = HEAD_H + Math.max(TOP_GAP, 12 + back.length * LANE);
  const rowY = (row: number) => cardTop + (row - 1) * (BOX_H + rowGap);

  const boxes = new Map<string, Box>();
  for (const p of items)
    boxes.set(p.section.id, { x: colX(p.step), y: rowY(p.row), w: BOX_W, h: BOX_H });
  usedEnds.forEach((t, i) =>
    boxes.set(t, { x: colX(endCol), y: cardTop + i * (END_H + ROW_GAP), w: END_W, h: END_H }),
  );
  const openBox: Box | null = opening
    ? { x: colX(0), y: cardTop, w: BOX_W, h: BOX_H }
    : null;
  const notNow =
    opening && openBox
      ? {
          target: opening.notNow,
          box: {
            x: openBox.x + (BOX_W - END_W) / 2,
            y: openBox.y + BOX_H + NOT_NOW_GAP,
            w: END_W,
            h: END_H,
          },
        }
      : null;
  const boxOf = (id: string) => (id === OPENING_KEY ? openBox : boxes.get(id)) ?? null;

  // The vertical lanes of each gap, `gap` g lying between column g and column g + 1.
  const gapRuns = new Map<number, string[]>();
  const run = (gap: number, id: string) => gapRuns.set(gap, [...(gapRuns.get(gap) ?? []), id]);
  for (const e of [...back, ...skip]) {
    run(e.fromCol, `${e.key}:out`);
    run(e.toCol - 1, `${e.key}:in`);
  }
  const laneX = (gap: number, id: string) => {
    const list = gapRuns.get(gap) ?? [id];
    const i = list.indexOf(id);
    return colX(gap) + BOX_W + COL_GAP / 2 + (i - (list.length - 1) / 2) * LANE;
  };

  // Each link into a card has its own place on the card's left edge, in the order they arrive
  // from top to bottom (a back link comes down from above), so two arrowheads never share a
  // point and a line's colour is never hidden under another's.
  const arrival = (e: Edge) =>
    kindOf(e) === "back" ? -1 : (boxOf(e.from)?.y ?? 0) + e.fromRow / 100;
  const entry = new Map<string, number>();
  const into = new Map<string, Edge[]>();
  for (const e of edges) into.set(e.to, [...(into.get(e.to) ?? []), e]);
  for (const [to, list] of into) {
    const box = boxOf(to);
    if (!box) continue;
    const spread = Math.min(ENTRY_GAP, (box.h - 16) / Math.max(1, list.length - 1));
    [...list]
      .sort((p, q) => arrival(p) - arrival(q))
      .forEach((e, i) =>
        entry.set(e.key, box.y + box.h / 2 + (i - (list.length - 1) / 2) * spread),
      );
  }

  const links: Routed[] = [];
  for (const e of edges) {
    const from = boxOf(e.from);
    const to = boxOf(e.to);
    if (!from || !to) continue;
    const a = { x: from.x + from.w, y: from.y + from.h / 2 };
    const b = { x: to.x, y: entry.get(e.key) ?? to.y + to.h / 2 };
    const kind = kindOf(e);
    if (kind === "next") {
      links.push({ ...base(e, kind), d: curve(a, b), end: b, dir: "right", samples: curvePoints(a, b) });
      continue;
    }
    let y: number;
    if (kind === "back") {
      y = cardTop - 10 - back.indexOf(e) * LANE;
    } else {
      const list = inChannel.get(channel(e)) ?? [e];
      const i = list.indexOf(e);
      y = rowY(channel(e)) + BOX_H + rowGap / 2 + (i - (list.length - 1) / 2) * LANE;
    }
    const xs = laneX(e.fromCol, `${e.key}:out`);
    const xt = laneX(e.toCol - 1, `${e.key}:in`);
    const points = [a, { x: xs, y: a.y }, { x: xs, y }, { x: xt, y }, { x: xt, y: b.y }, b];
    links.push({ ...base(e, kind), d: rounded(points), end: b, dir: "right", samples: along(points) });
  }
  if (openBox && notNow) {
    const top = { x: openBox.x + BOX_W / 2, y: openBox.y + BOX_H };
    const tip = { x: top.x, y: notNow.box.y };
    links.push({
      key: `${OPENING_KEY}-not-now`,
      from: OPENING_KEY,
      to: notNow.target,
      kind: "not-now",
      color: NO_COLOR,
      d: `M ${top.x} ${top.y} L ${tip.x} ${tip.y}`,
      end: tip,
      dir: "down",
      samples: along([top, tip]),
    });
  }

  const tallest = Math.max(1, ...items.map((p) => p.row));
  const cardsBottom = rowY(tallest) + BOX_H;
  const endsBottom = usedEnds.length ? cardTop + usedEnds.length * (END_H + ROW_GAP) : 0;
  const notNowBottom = notNow ? notNow.box.y + END_H : 0;
  const width = colX(endCol) + (usedEnds.length ? END_W : BOX_W) + PAD_X;
  const height = Math.max(cardsBottom, endsBottom, notNowBottom) + FOOT;

  return { colX, cardTop, boxes, usedEnds, opening: openBox, notNow, links, width, height };
}

function base(e: Edge, kind: LinkKind) {
  return { key: e.key, from: e.from, to: e.to, kind, color: e.color };
}

/** The arrowhead at a link's end. */
export function arrowHead(end: Point, dir: "right" | "down"): string {
  return dir === "right"
    ? `M ${end.x - 8} ${end.y - 5} L ${end.x} ${end.y} L ${end.x - 8} ${end.y + 5} z`
    : `M ${end.x - 5} ${end.y - 8} L ${end.x} ${end.y} L ${end.x + 5} ${end.y - 8} z`;
}
