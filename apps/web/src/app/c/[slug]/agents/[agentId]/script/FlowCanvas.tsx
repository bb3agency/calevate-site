"use client";

/**
 * THE CALL AS A PICTURE — the desktop's flow canvas.
 *
 * Built here, in SVG and positioned buttons, rather than with a graph library: the brief
 * for this console allows no new npm dependency without the founder (REDESIGN-2), and what
 * a script needs is small — at most twelve nodes, three end points, arrows with a label.
 *
 * It draws `script.stages` and writes back through the same calls the list uses: a click
 * selects a step for the side panel, dragging a step stores its `position`, and
 * dragging from a step's dot to another step adds a way out (`connect`). Every one of
 * those has a keyboard way too: Tab to a step, Enter to edit it, arrow keys to move it
 * (Shift for bigger moves), and the editor's "Add a way out" in place of the dot.
 *
 * Where the host passes the handlers, the end points can be dragged (`onEndPosition`), an
 * arrow's label (or the dot on an unlabelled arrow) dragged to bend the line through that
 * point (`onBend`), and a label clicked to rewrite its condition (`onRelabel`). Arrows are
 * coloured by what they say: green for a yes, orange for a no, blue for any other condition.
 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { CircleAlert } from "lucide-react";

import type { ScriptContext } from "@/lib/api/script";

import {
  CALL_BACK,
  DEFAULT_COLUMNS,
  END,
  GAP_X,
  GAP_Y,
  HAND_OVER,
  MARGIN,
  NODE_H,
  NODE_W,
  SPECIAL_TARGETS,
  columnsFor,
  edgesOf,
  positionOf,
  type Issue,
  type Section,
} from "./scriptModel";
import { targetLabel } from "./sectionParts";

type Point = { x: number; y: number };
type Box = Point & { w: number; h: number };

const END_W = 168;
const END_H = 40;
const PAD = 48;
/** The lane between the last column of steps and the end-of-call column. */
const CORRIDOR = 64;
/** The canvas grows with its picture between these heights, then scrolls. */
const MIN_HEIGHT = 280;
const MAX_HEIGHT = 900;
const CORNER = 8;

/** A path through `points` with its corners rounded, so a route reads as one line. */
function rounded(points: Point[]): string {
  const pts = points.filter((p, i) => i === 0 || p.x !== points[i - 1].x || p.y !== points[i - 1].y);
  if (pts.length < 2) return "";
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i += 1) {
    const [a, p, b] = [pts[i - 1], pts[i], pts[i + 1]];
    const lenIn = Math.hypot(p.x - a.x, p.y - a.y);
    const lenOut = Math.hypot(b.x - p.x, b.y - p.y);
    const r = Math.min(CORNER, lenIn / 2, lenOut / 2);
    const inPt = { x: p.x - ((p.x - a.x) / lenIn) * r, y: p.y - ((p.y - a.y) / lenIn) * r };
    const outPt = { x: p.x + ((b.x - p.x) / lenOut) * r, y: p.y + ((b.y - p.y) / lenOut) * r };
    d += ` L ${inPt.x} ${inPt.y} Q ${p.x} ${p.y} ${outPt.x} ${outPt.y}`;
  }
  const last = pts[pts.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

/** The middle of the longest horizontal run, where a way out's label sits. */
function labelPoint(points: Point[]): Point {
  let best = { len: -1, at: points[0] };
  for (let i = 1; i < points.length; i += 1) {
    const [a, b] = [points[i - 1], points[i]];
    const len = a.y === b.y ? Math.abs(b.x - a.x) : 0;
    if (len > best.len) best = { len, at: { x: (a.x + b.x) / 2, y: a.y } };
  }
  if (best.len > 0) return best.at;
  const [a, b] = [points[0], points[points.length - 1]];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * The route of one arrow, drawn in the gaps between steps rather than across them: a
 * neighbour to the right is a straight line; anything else leaves from the bottom (or the
 * top, going up), runs along the gap between rows, and comes in from the top or bottom.
 * A jump of more than one row drops down the gap beside the step it leaves. End-of-call
 * targets in their own column (`isEnd`) are reached along the corridor in front of it;
 * in a row under the steps they are routed like any other step.
 *
 * `lane` nudges arrows that share a gap apart, so two never draw as one.
 */
function route(a: Box, b: Box, isEnd: boolean, steps: Box[], corridorX: number, lane: number): Point[] {
  const acx = a.x + a.w / 2;
  const bcx = b.x + b.w / 2;
  const acy = a.y + a.h / 2;
  const bcy = b.y + b.h / 2;
  const sameRow = Math.abs(a.y - b.y) < a.h / 2;
  const clearRight = !steps.some((s) => s !== a && Math.abs(s.y - a.y) < a.h / 2 && s.x > a.x);

  if (isEnd) {
    if (clearRight) return [{ x: a.x + a.w, y: acy }, { x: corridorX, y: acy }, { x: corridorX, y: bcy }, { x: b.x, y: bcy }];
    const gap = a.y + a.h + GAP_Y / 2 + lane;
    return [{ x: acx, y: a.y + a.h }, { x: acx, y: gap }, { x: corridorX, y: gap }, { x: corridorX, y: bcy }, { x: b.x, y: bcy }];
  }
  if (sameRow && b.x > a.x && b.x - (a.x + a.w) <= GAP_X + 1) {
    const midX = (a.x + a.w + b.x) / 2;
    return [{ x: a.x + a.w, y: acy }, { x: midX, y: acy }, { x: midX, y: bcy }, { x: b.x, y: bcy }];
  }
  if (sameRow) {
    const gap = Math.max(a.y + a.h, b.y + b.h) + GAP_Y / 2 + lane;
    return [{ x: acx, y: a.y + a.h }, { x: acx, y: gap }, { x: bcx, y: gap }, { x: bcx, y: b.y + b.h }];
  }
  if (b.y > a.y) {
    const below = a.y + a.h + GAP_Y / 2 + lane;
    const above = b.y - GAP_Y / 2 + lane;
    if (above - below <= 2 * Math.abs(lane) + 1) {
      return [{ x: acx, y: a.y + a.h }, { x: acx, y: below }, { x: bcx, y: below }, { x: bcx, y: b.y }];
    }
    const colX = bcx >= acx ? a.x + a.w + GAP_X / 2 : a.x - GAP_X / 2;
    return [{ x: acx, y: a.y + a.h }, { x: acx, y: below }, { x: colX, y: below }, { x: colX, y: above }, { x: bcx, y: above }, { x: bcx, y: b.y }];
  }
  const above = a.y - GAP_Y / 2 + lane;
  const below = b.y + b.h + GAP_Y / 2 + lane;
  if (above - below <= 2 * Math.abs(lane) + 1) {
    return [{ x: acx, y: a.y }, { x: acx, y: above }, { x: bcx, y: above }, { x: bcx, y: b.y + b.h }];
  }
  const colX = bcx >= acx ? a.x + a.w + GAP_X / 2 : a.x - GAP_X / 2;
  return [{ x: acx, y: a.y }, { x: acx, y: above }, { x: colX, y: above }, { x: colX, y: below }, { x: bcx, y: below }, { x: bcx, y: b.y + b.h }];
}

/** Where a line from `box`'s centre towards `to` leaves the box. */
function anchor(box: Box, to: Point): Point {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const dx = to.x - cx;
  const dy = to.y - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const t = Math.min(dx === 0 ? Infinity : box.w / 2 / Math.abs(dx), dy === 0 ? Infinity : box.h / 2 / Math.abs(dy));
  return { x: cx + dx * t, y: cy + dy * t };
}

/** A gentle curve between two anchors, bent along the main direction of travel. */
function curve(a: Point, b: Point): string {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const k = 0.4;
  const c1 = horizontal ? { x: a.x + dx * k, y: a.y } : { x: a.x, y: a.y + dy * k };
  const c2 = horizontal ? { x: b.x - dx * k, y: b.y } : { x: b.x, y: b.y - dy * k };
  return `M ${a.x} ${a.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${b.x} ${b.y}`;
}

type Tone = "yes" | "no" | "branch" | "otherwise" | "next";

const YES = /\b(yes|agrees?|accepts?|interested|okay|ok|sure|confirms?|ready|happy|installed)\b/i;
const NO = /\b(no|not|don'?t|doesn'?t|refuses?|declines?|busy|later|can'?t|won'?t|never|wrong)\b/i;

/** Yes or no by the condition's words; one that says both ("says yes or no") is neither. */
function toneOf(kind: "branch" | "otherwise" | "next", label: string): Tone {
  if (kind !== "branch") return kind;
  const yes = YES.test(label);
  const no = NO.test(label);
  if (yes && !no) return "yes";
  if (no && !yes) return "no";
  return "branch";
}

/** The arrow colours: the chart series tokens, so both palettes keep their contrast. */
const TONE_COLOR: Record<Tone, string> = {
  yes: "var(--series-1)",
  no: "var(--series-3)",
  branch: "var(--series-2)",
  otherwise: "var(--ink-muted)",
  next: "var(--ink-faint)",
};

function short(text: string, n = 28): string {
  const t = text.trim() || "…";
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

export function FlowCanvas({
  sections,
  context,
  issues,
  selected,
  readOnly,
  onSelect,
  onPosition,
  onConnect,
  endPositions,
  onEndPosition,
  onBend,
  onRelabel,
}: {
  sections: Section[];
  context: ScriptContext | null;
  issues: Issue[];
  selected: string | null;
  readOnly: boolean;
  onSelect: (id: string) => void;
  onPosition: (id: string, at: Point) => void;
  onConnect: (from: string, to: string) => void;
  /** Where each end point was dragged to; absent ones sit in their column. */
  endPositions?: Record<string, Point>;
  onEndPosition?: (target: string, at: Point) => void;
  /** Bend an arrow through `via`; null straightens it. `branch` null is the default way on. */
  onBend?: (from: string, branch: number | null, via: Point | null) => void;
  onRelabel?: (from: string, branch: number, when: string) => void;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const plane = useRef<HTMLDivElement>(null);
  const [moving, setMoving] = useState<{ id: string; start: Point; origin: Point; at: Point; moved: boolean } | null>(null);
  const [linking, setLinking] = useState<{ from: string; to: Point } | null>(null);
  // An end point or an arrow's bend being dragged: `key` is the end's target or the edge index.
  const [dragging, setDragging] = useState<{
    kind: "end" | "bend";
    key: string;
    start: Point;
    origin: Point;
    at: Point;
    moved: boolean;
  } | null>(null);
  const [relabelling, setRelabelling] = useState<{ edge: number; text: string } | null>(null);
  const [announce, setAnnounce] = useState("");
  const [frameWidth, setFrameWidth] = useState(0);

  // The canvas lays unplaced steps out to the width it actually has, so it follows the
  // window rather than a fixed three to a row.
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => setFrameWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const edges = edgesOf(sections);
  const usedEnds = SPECIAL_TARGETS.filter((t) => edges.some((e) => e.to === t));
  // The end points take a column on the right while that still leaves three steps to a
  // row (or room for every step); on a narrower canvas they sit in a row under the steps,
  // so the steps keep the width.
  const besideCols = frameWidth ? columnsFor(frameWidth, usedEnds.length ? CORRIDOR + END_W : 0) : DEFAULT_COLUMNS;
  const endsBeside = usedEnds.length === 0 || besideCols >= Math.min(3, sections.length);
  const columns = Math.min(
    Math.max(sections.length, 1),
    endsBeside || !frameWidth ? besideCols : columnsFor(frameWidth),
  );

  const stepBoxMap = useMemo(() => {
    const out = new Map<string, Box>();
    sections.forEach((s, i) => {
      const p = moving?.id === s.id ? moving.at : positionOf(s, i, columns);
      out.set(s.id, { x: Math.max(0, p.x), y: Math.max(0, p.y), w: NODE_W, h: NODE_H });
    });
    return out;
  }, [sections, moving, columns]);

  // Steps and end points together; a new map each render, so the memoised step boxes are
  // never mutated.
  const boxes = new Map(stepBoxMap);
  const stepBoxes = [...stepBoxMap.values()];
  const stepsRight = Math.max(MARGIN, ...stepBoxes.map((b) => b.x + b.w));
  const stepsBottom = Math.max(...stepBoxes.map((b) => b.y + b.h), 0);
  const corridorX = stepsRight + CORRIDOR / 2;
  usedEnds.forEach((t, i) => {
    const placed = dragging?.kind === "end" && dragging.key === t ? dragging.at : endPositions?.[t];
    boxes.set(
      t,
      placed
        ? { x: Math.max(0, placed.x), y: Math.max(0, placed.y), w: END_W, h: END_H }
        : endsBeside
        ? { x: corridorX + CORRIDOR / 2, y: MARGIN + i * (END_H + 24), w: END_W, h: END_H }
        : {
            x: MARGIN + (i % columns) * (NODE_W + GAP_X) + (NODE_W - END_W) / 2,
            y: stepsBottom + GAP_Y + Math.floor(i / columns) * (END_H + GAP_Y),
            w: END_W,
            h: END_H,
          },
    );
  });
  const allBoxes = [...boxes.values()];
  const width = Math.max(...allBoxes.map((b) => b.x + b.w), stepsRight) + MARGIN;
  const height = Math.max(...allBoxes.map((b) => b.y + b.h), 0) + PAD;
  // Each arrow's bend: the one being dragged, else the one stored on its step.
  const viaOf = (edge: (typeof edges)[number], i: number): Point | null => {
    if (dragging?.kind === "bend" && dragging.key === String(i)) return dragging.at;
    const source = sections.find((x) => x.id === edge.from);
    if (!source) return null;
    if (edge.kind === "branch") return source.branches[edge.branch ?? -1]?.via ?? null;
    return source.otherwise_via ?? null;
  };
  const vias = edges.map(viaOf);
  const routes = edges.map((edge, i) => {
    const a = boxes.get(edge.from);
    const b = boxes.get(edge.to);
    if (!a || !b) return null;
    const via = vias[i];
    if (via) return [anchor(a, via), via, anchor(b, via)];
    const lane = ((i % 3) - 1) * 6;
    const toEnd = (SPECIAL_TARGETS as readonly string[]).includes(edge.to);
    const endPlaced = toEnd && endPositions?.[edge.to] != null;
    return route(a, b, toEnd && endsBeside && !endPlaced, stepBoxes, corridorX, lane);
  });
  const tones = edges.map((edge) => toneOf(edge.kind, edge.label));
  const labelAt = (i: number): Point | null => {
    const points = routes[i];
    return points ? (vias[i] ?? labelPoint(points)) : null;
  };

  const local = (e: { clientX: number; clientY: number }): Point => {
    const box = plane.current?.getBoundingClientRect();
    return box ? { x: e.clientX - box.left, y: e.clientY - box.top } : { x: e.clientX, y: e.clientY };
  };

  const nodeAt = (p: Point, except: string): string | null => {
    for (const s of sections) {
      if (s.id === except) continue;
      const b = boxes.get(s.id);
      if (b && p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h) return s.id;
    }
    return null;
  };

  const startMove = (e: ReactPointerEvent<HTMLButtonElement>, s: Section, i: number) => {
    if (readOnly || e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const origin = positionOf(s, i, columns);
    setMoving({ id: s.id, start: local(e), origin, at: origin, moved: false });
  };
  const doMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (!moving) return;
    const p = local(e);
    const dx = p.x - moving.start.x;
    const dy = p.y - moving.start.y;
    const moved = moving.moved || Math.abs(dx) + Math.abs(dy) > 4;
    setMoving({ ...moving, moved, at: { x: Math.max(0, moving.origin.x + dx), y: Math.max(0, moving.origin.y + dy) } });
  };
  const endMove = (id: string) => {
    if (!moving) return;
    const { moved, at } = moving;
    setMoving(null);
    if (moved) onPosition(id, at);
    else onSelect(id);
  };

  // Dragging an end point or a bend: a press that does not move is a click (`onClick`).
  const startDrag = (e: ReactPointerEvent<HTMLElement>, kind: "end" | "bend", key: string, origin: Point) => {
    if (readOnly || e.button !== 0) return;
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging({ kind, key, start: local(e), origin, at: origin, moved: false });
  };
  const doDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (!dragging) return;
    const p = local(e);
    const dx = p.x - dragging.start.x;
    const dy = p.y - dragging.start.y;
    const moved = dragging.moved || Math.abs(dx) + Math.abs(dy) > 4;
    setDragging({ ...dragging, moved, at: { x: Math.max(0, dragging.origin.x + dx), y: Math.max(0, dragging.origin.y + dy) } });
  };
  const endDrag = (onClick?: () => void) => {
    if (!dragging) return;
    const { kind, key, moved, at } = dragging;
    setDragging(null);
    if (!moved) {
      onClick?.();
      return;
    }
    if (kind === "end") {
      onEndPosition?.(key, at);
      return;
    }
    const edge = edges[Number(key)];
    if (edge) onBend?.(edge.from, edge.kind === "branch" ? (edge.branch ?? null) : null, at);
  };
  const straighten = (i: number) => {
    const edge = edges[i];
    if (edge) onBend?.(edge.from, edge.kind === "branch" ? (edge.branch ?? null) : null, null);
  };

  const nudge = (s: Section, i: number, dx: number, dy: number) => {
    const p = positionOf(s, i, columns);
    onPosition(s.id, { x: Math.max(0, p.x + dx), y: Math.max(0, p.y + dy) });
    setAnnounce(`${s.name.trim() || "Step"} moved.`);
  };

  const endLabel: Record<string, string> = { [END]: "End the call", [HAND_OVER]: "Hand to a person", [CALL_BACK]: "Offer a call back" };

  return (
    <div
      ref={frame}
      // Tall enough for the picture (+2 for the frame's border, so one that fits does not
      // scroll by a hair), within the bounds; `h-full` lets it match the step editor beside
      // it when that is taller, rather than leaving white space under a short canvas.
      style={{ minHeight: Math.min(Math.max(height, MIN_HEIGHT), MAX_HEIGHT) + 2, maxHeight: MAX_HEIGHT + 2 }}
      className="relative h-full overflow-auto rounded-card border border-line bg-surface-muted"
      role="region"
      aria-label="The call as a flow picture"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a region that scrolls must take focus, or no key can scroll it
      tabIndex={0}
    >
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      {/* Centred when the frame is wider than the picture, so spare width sits evenly. */}
      <div ref={plane} className="relative mx-auto" style={{ width, height, minHeight: "100%" }}>
        <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
          <defs>
            {(Object.keys(TONE_COLOR) as Tone[]).map((tone) => (
              <marker
                key={tone}
                id={`flow-arrow-${tone}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" style={{ fill: TONE_COLOR[tone] }} />
              </marker>
            ))}
          </defs>
          {edges.map((edge, i) => {
            const points = routes[i];
            if (!points) return null;
            const tone = tones[i];
            return (
              <path
                key={`${edge.from}-${edge.kind}-${edge.branch ?? ""}-${i}`}
                d={rounded(points)}
                className="fill-none"
                style={{ stroke: TONE_COLOR[tone] }}
                strokeWidth={edge.kind === "next" ? 1.25 : tone === "yes" || tone === "no" ? 2 : 1.5}
                strokeDasharray={edge.kind === "next" ? "5 4" : undefined}
                markerEnd={`url(#flow-arrow-${tone})`}
              />
            );
          })}
          {linking && boxes.get(linking.from) && (
            <path
              d={curve(anchor(boxes.get(linking.from) as Box, linking.to), linking.to)}
              className="fill-none stroke-brand"
              strokeWidth={2}
              strokeDasharray="4 4"
            />
          )}
        </svg>

        {edges.map((edge, i) => {
          const points = routes[i];
          // "Otherwise" means something only beside a condition; alone it is just the way on.
          const plainWayOn =
            edge.kind === "otherwise" && !sections.find((s) => s.id === edge.from)?.branches.length;
          const at = labelAt(i);
          if (!points || !at) return null;
          const tone = tones[i];
          const bendable = !readOnly && onBend != null;
          // An arrow with no words gets a small dot to drag its line by.
          if (edge.kind === "next" || plainWayOn) {
            if (!bendable) return null;
            return (
              <span
                key={`bend-${i}`}
                aria-hidden
                title="Drag to move this line; double-click to straighten it"
                className="absolute z-raised h-3 w-3 -translate-x-1/2 -translate-y-1/2 cursor-move touch-none rounded-full border-2 border-surface"
                style={{ left: at.x, top: at.y, background: TONE_COLOR[tone] }}
                onPointerDown={(e) => startDrag(e, "bend", String(i), at)}
                onPointerMove={doDrag}
                onPointerUp={() => endDrag()}
                onPointerCancel={() => setDragging(null)}
                onDoubleClick={() => straighten(i)}
              />
            );
          }
          if (relabelling?.edge === i && edge.kind === "branch") {
            const done = (keep: boolean) => {
              const text = relabelling.text.trim();
              setRelabelling(null);
              if (keep && text && text !== edge.label && edge.branch != null) onRelabel?.(edge.from, edge.branch, text);
            };
            return (
              <span
                key={`edit-${i}`}
                className="absolute z-raised flex -translate-x-1/2 -translate-y-1/2 items-center gap-1 rounded-full border bg-surface px-1 py-0.5 shadow-overlay"
                style={{ left: at.x, top: at.y, borderColor: TONE_COLOR[tone] }}
              >
                {/* Focused as it opens, from a click on the label, so the owner types at once. */}
                <input
                  ref={(el) => el?.focus()}
                  aria-label="When the call goes this way"
                  className="w-52 bg-transparent px-1 text-[12px] text-ink outline-none"
                  value={relabelling.text}
                  maxLength={300}
                  onChange={(e) => setRelabelling({ edge: i, text: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      done(true);
                    } else if (e.key === "Escape") {
                      e.preventDefault();
                      e.stopPropagation();
                      done(false);
                    }
                  }}
                  onBlur={() => done(true)}
                />
                {vias[i] && (
                  <button
                    type="button"
                    className="rounded-full px-1.5 text-[11px] text-ink-muted hover:text-ink"
                    onPointerDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setRelabelling(null);
                      straighten(i);
                    }}
                  >
                    Straighten
                  </button>
                )}
              </span>
            );
          }
          const words = edge.kind === "otherwise" ? "Otherwise" : short(edge.label);
          const style = { left: at.x, top: at.y, borderColor: TONE_COLOR[tone], color: tone === "otherwise" ? undefined : TONE_COLOR[tone] };
          const pill =
            "absolute max-w-44 -translate-x-1/2 -translate-y-1/2 truncate rounded-full border bg-surface px-2 py-0.5 text-[11px] font-medium text-ink-muted";
          if (!bendable) {
            return (
              <span key={`label-${i}`} aria-hidden className={`pointer-events-none ${pill}`} style={style}>
                {words}
              </span>
            );
          }
          return (
            <button
              key={`label-${i}`}
              type="button"
              title={edge.kind === "branch" ? "Click to change the words; drag to move the line" : "Drag to move the line; double-click to straighten it"}
              aria-label={edge.kind === "branch" ? `Change "${edge.label}"` : "Otherwise"}
              className={`${pill} z-raised cursor-move touch-none hover:shadow-card ${dragging?.key === String(i) ? "shadow-overlay" : ""}`}
              style={style}
              onPointerDown={(e) => startDrag(e, "bend", String(i), at)}
              onPointerMove={doDrag}
              onPointerUp={() =>
                endDrag(() => {
                  if (edge.kind === "branch" && onRelabel) setRelabelling({ edge: i, text: edge.label });
                })
              }
              onPointerCancel={() => setDragging(null)}
              onDoubleClick={() => edge.kind !== "branch" && straighten(i)}
            >
              {words}
            </button>
          );
        })}

        {usedEnds.map((t) => {
          const b = boxes.get(t) as Box;
          const movable = !readOnly && onEndPosition != null;
          return (
            <span
              key={t}
              title={movable ? "Drag to move" : undefined}
              className={`absolute flex select-none items-center justify-center rounded-full border border-dashed border-ink-faint bg-surface px-3 text-meta text-ink-muted ${
                movable ? "cursor-grab touch-none active:cursor-grabbing" : ""
              } ${dragging?.kind === "end" && dragging.key === t ? "z-raised shadow-overlay" : ""}`}
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
              onPointerDown={movable ? (e) => startDrag(e, "end", t, { x: b.x, y: b.y }) : undefined}
              onPointerMove={movable ? doDrag : undefined}
              onPointerUp={movable ? () => endDrag() : undefined}
              onPointerCancel={movable ? () => setDragging(null) : undefined}
            >
              {endLabel[t]}
            </span>
          );
        })}

        {sections.map((s, i) => {
          const b = boxes.get(s.id) as Box;
          const own = issues.filter((x) => x.section === s.id);
          const outs = s.branches.length;
          const on = selected === s.id;
          return (
            <div
              key={s.id}
              className={`absolute ${moving?.id === s.id && moving.moved ? "z-raised" : ""}`}
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
            >
              <button
                type="button"
                aria-pressed={on}
                aria-label={`${i + 1}. ${s.name.trim() || "Untitled step"}${own.length ? ", needs finishing" : ""}. Press Enter to edit, arrow keys to move.`}
                className={`flex h-full w-full touch-none select-none flex-col rounded-card border bg-surface p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  on ? "border-brand ring-1 ring-brand" : "border-line hover:border-ink-faint"
                } ${readOnly ? "" : "cursor-grab active:cursor-grabbing"} ${moving?.id === s.id && moving.moved ? "shadow-overlay" : ""}`}
                onPointerDown={(e) => startMove(e, s, i)}
                onPointerMove={doMove}
                onPointerUp={() => endMove(s.id)}
                onPointerCancel={() => setMoving(null)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(s.id);
                    return;
                  }
                  if (readOnly) return;
                  const step = e.shiftKey ? 64 : 16;
                  const d: Record<string, [number, number]> = {
                    ArrowLeft: [-step, 0],
                    ArrowRight: [step, 0],
                    ArrowUp: [0, -step],
                    ArrowDown: [0, step],
                  };
                  if (d[e.key]) {
                    e.preventDefault();
                    nudge(s, i, d[e.key][0], d[e.key][1]);
                  }
                }}
              >
                <span className="flex w-full items-center gap-2">
                  <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-ink/[0.07] px-1 text-[11px] font-semibold tabular-nums text-ink">
                    {i + 1}
                  </span>
                  <span title={s.name.trim() || undefined} className="min-w-0 flex-1 truncate text-body font-semibold text-ink">
                    {s.name.trim() || "Untitled step"}
                  </span>
                  {own.length > 0 && <CircleAlert aria-hidden className="h-4 w-4 shrink-0 text-danger" />}
                </span>
                <span className="mt-1 line-clamp-2 text-meta text-ink-muted">
                  {s.instruction.trim() || "Nothing written yet."}
                </span>
                <span className="mt-auto truncate text-[11px] text-ink-faint">
                  {i === 0 ? "Start · " : ""}
                  {s.mode === "say" ? "Exact words · " : ""}
                  {outs ? `${outs} ${outs === 1 ? "way out" : "ways out"}` : "One way on"}
                  {s.collect.length ? ` · finds out ${s.collect.length}` : ""}
                </span>
              </button>
              {!readOnly && (
                <div
                  aria-hidden
                  title="Drag to another step to add a way out"
                  className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 cursor-crosshair touch-none rounded-full border-2 border-surface bg-brand-strong before:absolute before:-inset-y-3.5 before:-left-2 before:-right-5 before:content-['']"
                  onPointerDown={(e) => {
                    if (e.button !== 0) return;
                    e.stopPropagation();
                    e.currentTarget.setPointerCapture(e.pointerId);
                    setLinking({ from: s.id, to: local(e) });
                  }}
                  onPointerMove={(e) => linking && setLinking({ ...linking, to: local(e) })}
                  onPointerUp={(e) => {
                    if (!linking) return;
                    const target = nodeAt(local(e), linking.from);
                    setLinking(null);
                    if (target) {
                      onConnect(linking.from, target);
                      setAnnounce(`Added a way out from ${s.name.trim() || "the step"}.`);
                    }
                  }}
                  onPointerCancel={() => setLinking(null)}
                />
              )}
            </div>
          );
        })}
      </div>
      <p className="sr-only">
        {sections.length} steps.{" "}
        {edges
          .filter((e) => e.kind !== "next")
          .map((e) => `${targetLabel(sections, e.from, context)} goes to ${targetLabel(sections, e.to, context)}${e.kind === "branch" ? ` when ${e.label}` : " otherwise"}.`)
          .join(" ")}
      </p>
    </div>
  );
}

