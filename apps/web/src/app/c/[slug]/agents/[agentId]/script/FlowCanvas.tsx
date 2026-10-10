"use client";

/**
 * THE CALL AS A PICTURE — the desktop's flow canvas.
 *
 * Built here, in SVG and positioned buttons, rather than with a graph library: the brief
 * for this console allows no new npm dependency without the founder (REDESIGN-2), and what
 * a script needs is small — at most twelve nodes, three end points, arrows with a label.
 *
 * It draws `script.stages` and writes back through the same calls the list uses: a click
 * selects a section for the side panel, dragging a section stores its `position`, and
 * dragging from a section's dot to another section adds a way out (`connect`). Every one of
 * those has a keyboard way too: Tab to a section, Enter to edit it, arrow keys to move it
 * (Shift for bigger steps), and the editor's "Add a way out" in place of the dot.
 */

import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { CircleAlert } from "lucide-react";

import type { ScriptContext } from "@/lib/api/script";

import {
  CALL_BACK,
  END,
  HAND_OVER,
  NODE_H,
  NODE_W,
  SPECIAL_TARGETS,
  edgesOf,
  positionOf,
  type Edge,
  type Issue,
  type Section,
} from "./scriptModel";
import { targetLabel } from "./sectionParts";

type Point = { x: number; y: number };
type Box = Point & { w: number; h: number };

const END_W = 168;
const END_H = 40;
const PAD = 48;

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

function centre(box: Box): Point {
  return { x: box.x + box.w / 2, y: box.y + box.h / 2 };
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
}: {
  sections: Section[];
  context: ScriptContext | null;
  issues: Issue[];
  selected: string | null;
  readOnly: boolean;
  onSelect: (id: string) => void;
  onPosition: (id: string, at: Point) => void;
  onConnect: (from: string, to: string) => void;
}) {
  const plane = useRef<HTMLDivElement>(null);
  const [moving, setMoving] = useState<{ id: string; start: Point; origin: Point; at: Point; moved: boolean } | null>(null);
  const [linking, setLinking] = useState<{ from: string; to: Point } | null>(null);
  const [announce, setAnnounce] = useState("");

  const boxes = useMemo(() => {
    const out = new Map<string, Box>();
    sections.forEach((s, i) => {
      const p = moving?.id === s.id ? moving.at : positionOf(s, i);
      out.set(s.id, { x: Math.max(0, p.x), y: Math.max(0, p.y), w: NODE_W, h: NODE_H });
    });
    return out;
  }, [sections, moving]);

  const edges = edgesOf(sections);
  const usedEnds = SPECIAL_TARGETS.filter((t) => edges.some((e) => e.to === t));
  const right = Math.max(PAD, ...[...boxes.values()].map((b) => b.x + b.w)) + 96;
  const bottom = Math.max(...[...boxes.values()].map((b) => b.y + b.h), 0);
  usedEnds.forEach((t, i) => {
    boxes.set(t, { x: right, y: PAD / 2 + i * (END_H + 32), w: END_W, h: END_H });
  });
  const width = right + (usedEnds.length ? END_W : 0) + PAD;
  const height = Math.max(bottom, usedEnds.length * (END_H + 32)) + PAD * 2;

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
    const origin = positionOf(s, i);
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

  const nudge = (s: Section, i: number, dx: number, dy: number) => {
    const p = positionOf(s, i);
    onPosition(s.id, { x: Math.max(0, p.x + dx), y: Math.max(0, p.y + dy) });
    setAnnounce(`${s.name.trim() || "Section"} moved.`);
  };

  const endLabel: Record<string, string> = { [END]: "End the call", [HAND_OVER]: "Hand to a person", [CALL_BACK]: "Offer a call back" };

  return (
    <div
      className="relative h-[min(640px,70dvh)] overflow-auto rounded-card border border-line bg-surface-muted"
      role="region"
      aria-label="The call as a flow picture"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a region that scrolls must take focus, or no key can scroll it
      tabIndex={0}
    >
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      <div ref={plane} className="relative" style={{ width, height, minWidth: "100%", minHeight: "100%" }}>
        <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
          <defs>
            <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-ink-muted" />
            </marker>
          </defs>
          {edges.map((edge, i) => (
            <EdgePath key={`${edge.from}-${edge.kind}-${edge.branch ?? ""}-${i}`} edge={edge} boxes={boxes} />
          ))}
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
          if (edge.kind === "next") return null;
          const a = boxes.get(edge.from);
          const b = boxes.get(edge.to);
          if (!a || !b) return null;
          const p1 = anchor(a, centre(b));
          const p2 = anchor(b, centre(a));
          return (
            <span
              key={`label-${i}`}
              aria-hidden
              className="pointer-events-none absolute max-w-44 -translate-x-1/2 -translate-y-1/2 truncate rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] text-ink-muted"
              style={{ left: (p1.x + p2.x) / 2, top: (p1.y + p2.y) / 2 }}
            >
              {edge.kind === "otherwise" ? "Otherwise" : short(edge.label)}
            </span>
          );
        })}

        {usedEnds.map((t) => {
          const b = boxes.get(t) as Box;
          return (
            <span
              key={t}
              className="absolute flex items-center justify-center rounded-full border border-dashed border-ink-faint bg-surface px-3 text-meta text-ink-muted"
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
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
              className={`absolute ${moving?.id === s.id && moving.moved ? "z-10" : ""}`}
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
            >
              <button
                type="button"
                aria-pressed={on}
                aria-label={`${i + 1}. ${s.name.trim() || "Untitled section"}${own.length ? ", needs finishing" : ""}. Press Enter to edit, arrow keys to move.`}
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
                  <span className="min-w-0 flex-1 truncate text-body font-semibold text-ink">
                    {s.name.trim() || "Untitled section"}
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
                  title="Drag to another section to add a way out"
                  className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 cursor-crosshair touch-none rounded-full border-2 border-surface bg-brand-strong"
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
                      setAnnounce(`Added a way out from ${s.name.trim() || "the section"}.`);
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
        {sections.length} sections.{" "}
        {edges
          .filter((e) => e.kind !== "next")
          .map((e) => `${targetLabel(sections, e.from, context)} goes to ${targetLabel(sections, e.to, context)}${e.kind === "branch" ? ` when ${e.label}` : " otherwise"}.`)
          .join(" ")}
      </p>
    </div>
  );
}

function EdgePath({ edge, boxes }: { edge: Edge; boxes: Map<string, Box> }) {
  const a = boxes.get(edge.from);
  const b = boxes.get(edge.to);
  if (!a || !b) return null;
  const from = anchor(a, centre(b));
  const to = anchor(b, centre(a));
  return (
    <path
      d={curve(from, to)}
      className={`fill-none ${edge.kind === "next" ? "stroke-ink-faint" : "stroke-ink-muted"}`}
      strokeWidth={edge.kind === "next" ? 1.25 : 1.5}
      strokeDasharray={edge.kind === "next" ? "5 4" : undefined}
      markerEnd="url(#flow-arrow)"
    />
  );
}
