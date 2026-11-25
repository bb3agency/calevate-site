/**
 * Where the call-flow canvas puts its boxes and how each link between them is drawn. Pure:
 * scenarios in, rectangles and SVG paths out, so the routing is tested without a browser.
 *
 * Columns left to right: the call's opening (column 0), then a column per step. End points
 * (call back, end of call, hand over) are not columns and take no lines: each way out to one
 * is a chip on the scenario it leaves (`exitsOf`). A link to the very next column is a curve inside the gap between the two columns,
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
 *
 * Two kinds of way on. An EXPLICIT link is a branch or an Otherwise the script holds. An
 * IMPLICIT link is the call's own order: a scenario with no Otherwise goes on to the next
 * step once that step's outcome is reached (`call_script.OUTCOMES_LEAD`; ThinnestAI takes the
 * steps as "the conversation script, in order" with no next field, update-agent.md:818-825,
 * snapshot 2026-10-29). It always runs to the very next column, so it is a curve inside the
 * gap and never passes behind a card; one into a scenario the source already links to is not
 * drawn twice.
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

export type LinkKind = "next" | "skip" | "back";

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
 * A way out of a scenario that is NOT drawn as a line: one to an end point (call back, end of
 * call, hand over) or back into the scenario itself. Drawn as lines, an eight-step script's
 * ends were ten parallel strokes running the full width of the canvas to a column of end
 * nodes at the far right, crossing every step on the way; none of them says anything the
 * scenario it leaves cannot say in one line. So they sit on that scenario as chips, and the
 * lines are left for what only a line can show: the call moving from one step to another.
 */
export interface Exit {
  /** The same key the link had when it was drawn: `<id>-<branch index>` or `<id>-otherwise`. */
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
  fromCol: number;
  toCol: number;
  fromRow: number;
  toRow: number;
}

/**
 * The ways out of a scenario that go on its card: every one to an end point in `ends`, and a
 * branch back into itself. An Otherwise into itself is not one: "Otherwise stays on this
 * step" is the card's own Then line (`thenOf`).
 */
export function exitsOf(item: Placed, ends: readonly string[]): Exit[] {
  const s = item.section;
  const out: Exit[] = s.branches.flatMap((b, j) =>
    ends.includes(b.target) || b.target === s.id
      ? [{ key: `${s.id}-${j}`, target: b.target, when: b.when, via: "branch" as const }]
      : [],
  );
  if (s.otherwise && ends.includes(s.otherwise))
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
  const where = new Map<string, { col: number; row: number }>();
  for (const p of items) where.set(p.section.id, { col: p.step, row: p.row });
  const exits = new Map(items.map((p) => [p.section.id, exitsOf(p, ends)]));

  const edges: Edge[] = [];
  if (opening)
    for (const p of items.filter((q) => q.step === 1))
      edges.push({
        key: `${OPENING_KEY}-${p.section.id}`,
        from: OPENING_KEY,
        to: p.section.id,
        color: YES_COLOR,
        via: "opening",
        fromCol: 0,
        toCol: 1,
        fromRow: 1,
        toRow: p.row,
      });
  // Only a move to ANOTHER scenario is a line: `where` holds scenarios alone, so an end point
  // has nowhere to be drawn to, and a scenario's way back into itself is skipped here.
  for (const p of items)
    p.section.branches.forEach((b, j) => {
      const to = where.get(b.target);
      if (!to || b.target === p.section.id) return;
      edges.push({
        key: `${p.section.id}-${j}`,
        from: p.section.id,
        to: b.target,
        color: toneColor(b.when),
        via: "branch",
        fromCol: p.step,
        toCol: to.col,
        fromRow: p.row,
        toRow: to.row,
      });
    });
  for (const p of items) {
    if (p.section.otherwise) {
      const to = where.get(p.section.otherwise);
      if (to && p.section.otherwise !== p.section.id)
        edges.push({
          key: `${p.section.id}-otherwise`,
          from: p.section.id,
          to: p.section.otherwise,
          color: OTHER_COLOR,
          via: "otherwise",
          fromCol: p.step,
          toCol: to.col,
          fromRow: p.row,
          toRow: to.row,
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
          fromCol: p.step,
          toCol: q.step,
          fromRow: p.row,
          toRow: q.row,
        });
  }
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

  // Rows line up across columns, so a row is as tall as its card with the most chips: the
  // gap under every row then holds no card, which is what the skip lanes run along.
  const tallest = Math.max(1, ...items.map((p) => p.row));
  const chipLines = Array.from({ length: tallest + 1 }, () => 0);
  for (const p of items)
    chipLines[p.row] = Math.max(chipLines[p.row], exits.get(p.section.id)?.length ?? 0);
  if (opening) chipLines[1] = Math.max(chipLines[1], 1);
  const rowH = (row: number) => BOX_H + (chipLines[row] ?? 0) * CHIP_LINE;
  const rowY = (row: number) => {
    let y = cardTop;
    for (let r = 1; r < row; r++) y += rowH(r) + rowGap;
    return y;
  };

  const boxes = new Map<string, Box>();
  for (const p of items)
    boxes.set(p.section.id, { x: colX(p.step), y: rowY(p.row), w: BOX_W, h: rowH(p.row) });
  const openBox: Box | null = opening ? { x: colX(0), y: cardTop, w: BOX_W, h: rowH(1) } : null;
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
  // point and a line's colour is never hidden under another's. Links leave and enter at the
  // middle of a chipless card, so a row grown by chips keeps its lines level with the dot.
  const mid = (box: Box) => box.y + BOX_H / 2;
  const arrival = (e: Edge) =>
    kindOf(e) === "back" ? -1 : (boxOf(e.from)?.y ?? 0) + e.fromRow / 100;
  const entry = new Map<string, number>();
  const into = new Map<string, Edge[]>();
  for (const e of edges) into.set(e.to, [...(into.get(e.to) ?? []), e]);
  for (const [to, list] of into) {
    const box = boxOf(to);
    if (!box) continue;
    const spread = Math.min(ENTRY_GAP, (BOX_H - 16) / Math.max(1, list.length - 1));
    [...list]
      .sort((p, q) => arrival(p) - arrival(q))
      .forEach((e, i) => entry.set(e.key, mid(box) + (i - (list.length - 1) / 2) * spread));
  }

  const links: Routed[] = [];
  for (const e of edges) {
    const from = boxOf(e.from);
    const to = boxOf(e.to);
    if (!from || !to) continue;
    const a = { x: from.x + from.w, y: mid(from) };
    const b = { x: to.x, y: entry.get(e.key) ?? mid(to) };
    const kind = kindOf(e);
    if (kind === "next") {
      links.push({ ...base(e, kind), d: curve(a, b), end: b, samples: curvePoints(a, b) });
      continue;
    }
    let y: number;
    if (kind === "back") {
      y = cardTop - 10 - back.indexOf(e) * LANE;
    } else {
      const list = inChannel.get(channel(e)) ?? [e];
      const i = list.indexOf(e);
      y = rowY(channel(e)) + rowH(channel(e)) + rowGap / 2 + (i - (list.length - 1) / 2) * LANE;
    }
    const xs = laneX(e.fromCol, `${e.key}:out`);
    const xt = laneX(e.toCol - 1, `${e.key}:in`);
    const points = [a, { x: xs, y: a.y }, { x: xs, y }, { x: xt, y }, { x: xt, y: b.y }, b];
    links.push({ ...base(e, kind), d: rounded(points), end: b, samples: along(points) });
  }

  const width = colX(steps + 1) + TAIL_W + PAD_X;
  const height = rowY(tallest) + rowH(tallest) + FOOT;

  return { colX, cardTop, boxes, exits, opening: openBox, links, width, height };
}

function base(e: Edge, kind: LinkKind) {
  return { key: e.key, from: e.from, to: e.to, kind, color: e.color, via: e.via };
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
