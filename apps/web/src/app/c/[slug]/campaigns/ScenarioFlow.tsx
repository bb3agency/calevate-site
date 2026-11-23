"use client";

/**
 * THE CALL FLOW IN STEPS AND SCENARIOS (founder, 17 Nov 2026). Each column is a step of the
 * call; each box in it a scenario (2.1, 2.2, …). A scenario's green dot leads to the
 * scenarios it can go on to, drawn as arrows into the left of their boxes. A box is chosen
 * with a click (its editor opens beside the picture), and a right click offers what can be
 * done to it. Dragging from the dot onto another box links them.
 *
 * Laid out by the steps, not by hand: the columns ARE the structure, so a picture somebody
 * dragged out of shape cannot disagree with the call order. Below the desktop width the
 * columns stack, and the links read as "Next: 3.1, 3.2" in each box.
 */

import {
  ArrowDown,
  ArrowUp,
  MoreHorizontal,
  Plus,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { FIELD, SECONDARY_BUTTON_SM, ToggleSwitch } from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { STEP_OUTCOME_MAX, type CallScript } from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

import { HearLine, type FlowAgent } from "./LineCoach";

import { languageName } from "./ScriptLanguages";
import {
  END_NAMES,
  addScenario,
  deleteScenario,
  moveToStep,
  outcomeOf,
  placed,
  renameScenario,
  setNext,
  setOutcome,
  shiftInStep,
  type Placed,
} from "./scenarioModel";
import {
  SPECIAL_TARGETS,
  chars,
  saysScenarioLine,
  sectionsOf,
  updateSection,
  type Issue,
  type Limits,
} from "../agents/[agentId]/script/scriptModel";

const BOX_W = 232;
const BOX_H = 112;
const COL_GAP = 88;
const ROW_GAP = 18;
/** A step's heading: its name and "Scenario" button, then its outcome field. */
const HEAD_H = 150;
/** How far outside a card a dragged link still lands on it. */
const DROP_MARGIN = 16;
const PAD = 20;
/** A step's band reaches `BAND_INSET` past its cards on each side, so the side padding must
 * hold it: with less, the first band and its "Step 1" heading start left of the canvas and
 * are clipped by the scroll box. */
const BAND_INSET = COL_GAP / 2 - 8;
const PAD_X = BAND_INSET + 12;
const END_W = 150;
const END_H = 40;

type Point = { x: number; y: number };
type Box = Point & { w: number; h: number };

const YES =
  /\b(yes|agrees?|accepts?|interested|okay|ok|sure|confirms?|ready|happy|installed|remembers?|knows?)\b/i;
const NO =
  /\b(no|not|don'?t|doesn'?t|refuses?|declines?|busy|later|can'?t|won'?t|never|wrong|forgot)\b/i;

/** The arrow's colour by the words of its way out: green yes, orange no, blue otherwise. */
function toneColor(when: string): string {
  const yes = YES.test(when);
  const no = NO.test(when);
  if (yes && !no) return "var(--series-1)";
  if (no && !yes) return "var(--series-3)";
  return "var(--series-2)";
}

/** A curve from a dot on the right of one box to the left edge of another. */
function link(a: Point, b: Point): string {
  const bend = Math.max(48, Math.abs(b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + bend} ${a.y}, ${b.x - bend} ${b.y}, ${b.x} ${b.y}`;
}

/** A coloured block of the scenario editor: each kind of content keeps its own colour. */
const SECTION = "rounded-card border border-line border-l-4 p-3";

const OUTCOME_HINT =
  "What must be true before the call moves on. The agent reaches it however the call goes; the scenarios are examples.";

/**
 * A step's outcome (founder, 23 Nov 2026): what the agent must reach before the call leaves
 * the step, by whichever scenario. `compact` is the canvas column, which has room for the
 * field but not the hint, so the hint is read with it by a screen reader and shown once
 * above the canvas instead.
 */
function StepOutcomeField({
  step,
  value,
  readOnly,
  compact,
  onChange,
}: {
  step: number;
  value: string;
  readOnly: boolean;
  compact: boolean;
  onChange: (next: string) => void;
}) {
  const id = useId();
  const used = chars(value);
  return (
    <div>
      <label htmlFor={id} className="block text-meta font-medium text-ink">
        Outcome of this step
        <span className="sr-only">, step {step}</span>
      </label>
      <p
        id={`${id}-hint`}
        className={compact ? "sr-only" : "text-meta text-ink-muted"}
      >
        {OUTCOME_HINT}
      </p>
      <textarea
        id={id}
        className={`${FIELD} ${compact ? "resize-none text-meta" : ""}`}
        rows={2}
        value={value}
        maxLength={STEP_OUTCOME_MAX}
        readOnly={readOnly}
        aria-describedby={`${id}-hint ${id}-count`}
        placeholder={compact ? "What must be true to move on" : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      <p
        id={`${id}-count`}
        className="text-right text-[11px] tabular-nums text-ink-faint"
      >
        {used}/{STEP_OUTCOME_MAX}
      </p>
    </div>
  );
}

type Menu = { x: number; y: number; id: string | null; step: number };

export function ScenarioFlow({
  script,
  limits,
  issues,
  languages,
  selected,
  readOnly,
  wide,
  onSelect,
  onChange,
  agent,
  hear,
}: {
  /** The campaign's agent, whose voice "Hear it" speaks in; null while none is chosen. */
  agent: FlowAgent | null;
  /** Whether this person may hear a line ("Hear it" is the owner's, `org:manage`). */
  hear: WriteAccess;
  script: CallScript;
  limits: Limits;
  issues: Issue[];
  /** The campaign's languages, main first; English's box shows when English is one of them. */
  languages: string[];
  selected: string | null;
  readOnly: boolean;
  /** The picture beside the editor (desktop); false stacks the steps. */
  wide: boolean;
  onSelect: (id: string | null) => void;
  onChange: (next: CallScript) => void;
}) {
  const items = useMemo(() => placed(sectionsOf(script)), [script]);
  const steps = Math.max(0, ...items.map((p) => p.step));
  const full = items.length >= limits.maxSections;
  const [menu, setMenu] = useState<Menu | null>(null);

  const add = (
    step: number,
    opts: { after?: string; newStep?: boolean } = {},
  ) => {
    if (full) return;
    const made = addScenario(script, step, opts);
    onChange(made.script);
    onSelect(made.id);
  };
  const remove = (id: string) => {
    onChange(deleteScenario(script, id));
    if (selected === id) onSelect(null);
  };

  const chosen = items.find((p) => p.section.id === selected) ?? null;
  const editor = chosen && (
    <ScenarioEditor
      key={chosen.section.id}
      item={chosen}
      items={items}
      steps={steps}
      script={script}
      limits={limits}
      issues={issues.filter((i) => i.section === chosen.section.id)}
      languages={languages}
      readOnly={readOnly}
      agent={agent}
      hear={hear}
      wide={wide}
      onChange={onChange}
      onDelete={() => remove(chosen.section.id)}
    />
  );

  const menuItems = (m: Menu) => {
    const item = m.id ? items.find((p) => p.section.id === m.id) : null;
    const list: {
      label: string;
      icon?: React.ReactNode;
      danger?: boolean;
      disabled?: boolean;
      run: () => void;
    }[] = [];
    if (item) {
      list.push({
        label: `Edit ${item.label}`,
        run: () => onSelect(item.section.id),
      });
      list.push({
        label: "Add a scenario below",
        icon: <Plus className="h-3.5 w-3.5" />,
        disabled: full,
        run: () => add(item.step, { after: item.section.id }),
      });
      list.push({
        label: `Add a scenario in step ${item.step + 1}`,
        icon: <Plus className="h-3.5 w-3.5" />,
        disabled: full,
        run: () => add(item.step + 1),
      });
      list.push({
        label: "Move up",
        icon: <ArrowUp className="h-3.5 w-3.5" />,
        disabled: item.row === 1,
        run: () => onChange(shiftInStep(script, item.section.id, -1)),
      });
      list.push({
        label: "Move down",
        icon: <ArrowDown className="h-3.5 w-3.5" />,
        disabled: !items.some(
          (p) => p.step === item.step && p.row === item.row + 1,
        ),
        run: () => onChange(shiftInStep(script, item.section.id, 1)),
      });
      list.push({
        label: "Delete scenario",
        icon: <Trash2 className="h-3.5 w-3.5" />,
        danger: true,
        run: () => remove(item.section.id),
      });
    } else {
      list.push({
        label: `Add a scenario to step ${m.step}`,
        icon: <Plus className="h-3.5 w-3.5" />,
        disabled: full,
        run: () => add(m.step),
      });
      list.push({
        label: `Insert a new step before step ${m.step}`,
        icon: <Plus className="h-3.5 w-3.5" />,
        disabled: full,
        run: () => add(m.step, { newStep: true }),
      });
    }
    return list;
  };

  const openMenu = (e: ReactMouseEvent, id: string | null, step: number) => {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, id, step });
  };

  const picture =
    items.length === 0 ? (
      <div className="rounded-card border border-dashed border-line px-4 py-8 text-center">
        <p className="text-meta text-ink-muted">
          No steps yet. Add the first scenario, or let Pip map the scenarios.
        </p>
        {!readOnly && (
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-3`}
            onClick={() => add(1)}
          >
            <Plus aria-hidden className="h-3.5 w-3.5" />
            Add a scenario
          </button>
        )}
      </div>
    ) : wide ? (
      <Columns
        items={items}
        steps={steps}
        selected={selected}
        readOnly={readOnly}
        full={full}
        issues={issues}
        onSelect={onSelect}
        onAdd={add}
        onMenu={openMenu}
        outcome={(step) => outcomeOf(script, step)}
        onOutcome={(step, text) => onChange(setOutcome(script, step, text))}
        onLink={(from, to) => {
          const source = items.find((p) => p.section.id === from)?.section;
          if (!source) return "That scenario is gone.";
          if (source.branches.some((b) => b.target === to)) return "It already goes there.";
          if (source.branches.length >= limits.maxBranches)
            return `A scenario can go to at most ${limits.maxBranches} next scenarios.`;
          onChange(
            setNext(script, from, [
              ...source.branches.map((b) => b.target),
              to,
            ]),
          );
          return null;
        }}
      />
    ) : (
      <Stacked
        items={items}
        steps={steps}
        selected={selected}
        readOnly={readOnly}
        full={full}
        onSelect={onSelect}
        onAdd={add}
        onMenu={openMenu}
        outcome={(step) => outcomeOf(script, step)}
        onOutcome={(step, text) => onChange(setOutcome(script, step, text))}
        editor={editor}
      />
    );

  return (
    <>
      {wide ? (
        <div className="mt-4 space-y-4">
          <div className="min-w-0">
            {items.length > 0 && (
              <p className="mb-2 text-meta text-ink-muted">
                Outcome of a step: {OUTCOME_HINT}
              </p>
            )}
            {picture}
          </div>
          <aside
            aria-label="Edit the chosen scenario"
            className="min-w-0 scroll-mt-4 rounded-card border border-series-2/40 bg-surface"
          >
            {editor ?? (
              <p className="px-4 py-6 text-center text-meta text-ink-muted">
                Choose a scenario to edit it here. Right-click a box for more.
              </p>
            )}
          </aside>
        </div>
      ) : (
        <div className="mt-4">{picture}</div>
      )}
      {full && !readOnly && (
        <p className="mt-2 text-meta text-ink-muted">
          {limits.maxSections} scenarios in all is the most a call can hold.
          Join two to make room.
        </p>
      )}
      {menu && (
        <ContextMenu
          menu={menu}
          items={menuItems(menu)}
          onClose={() => setMenu(null)}
        />
      )}
    </>
  );
}

/** The desktop picture: a column per step, arrows from each green dot to the next scenarios. */
function Columns({
  items,
  steps,
  selected,
  readOnly,
  full,
  issues,
  onSelect,
  onAdd,
  onMenu,
  onLink,
  outcome,
  onOutcome,
}: {
  items: Placed[];
  steps: number;
  selected: string | null;
  readOnly: boolean;
  full: boolean;
  issues: Issue[];
  onSelect: (id: string | null) => void;
  onAdd: (step: number, opts?: { after?: string; newStep?: boolean }) => void;
  onMenu: (e: ReactMouseEvent, id: string | null, step: number) => void;
  /** Links `from` to `to`; returns why it did not, or null when it did. */
  onLink: (from: string, to: string) => string | null;
  outcome: (step: number) => string;
  onOutcome: (step: number, text: string) => void;
}) {
  const plane = useRef<HTMLDivElement>(null);
  const [linking, setLinking] = useState<{ from: string; to: Point } | null>(
    null,
  );
  const [linkNote, setLinkNote] = useState<string | null>(null);
  const colX = (step: number) => PAD_X + (step - 1) * (BOX_W + COL_GAP);
  const boxes = new Map<string, Box>();
  for (const p of items) {
    boxes.set(p.section.id, {
      x: colX(p.step),
      y: PAD + HEAD_H + (p.row - 1) * (BOX_H + ROW_GAP),
      w: BOX_W,
      h: BOX_H,
    });
  }
  const usedEnds = SPECIAL_TARGETS.filter((t) =>
    items.some((p) => p.section.branches.some((b) => b.target === t)),
  );
  const endX = colX(steps + 1);
  usedEnds.forEach((t, i) =>
    boxes.set(t, {
      x: endX,
      y: PAD + HEAD_H + i * (END_H + ROW_GAP),
      w: END_W,
      h: END_H,
    }),
  );
  const tallest = Math.max(...items.map((p) => p.row), usedEnds.length ? 1 : 0);
  const width = endX + (usedEnds.length ? END_W : BOX_W) + PAD_X;
  const height = PAD + HEAD_H + tallest * (BOX_H + ROW_GAP) + 56;

  const local = (e: { clientX: number; clientY: number }): Point => {
    const r = plane.current?.getBoundingClientRect();
    return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 };
  };
  // A drop counts on a card or just around it: people let go on the arrowhead at a card's
  // edge, a few pixels outside its box, and that used to link nothing and say nothing.
  const boxAt = (p: Point, except: string) => {
    for (const [id, b] of boxes) {
      if (
        id !== except &&
        p.x >= b.x - DROP_MARGIN &&
        p.x <= b.x + b.w + DROP_MARGIN &&
        p.y >= b.y - DROP_MARGIN &&
        p.y <= b.y + b.h + DROP_MARGIN
      )
        return id;
    }
    return null;
  };
  // The card under the pointer as the page lays it out, before the drawn geometry.
  const dropTarget = (e: { clientX: number; clientY: number }, except: string) => {
    const under =
      typeof document.elementFromPoint === "function"
        ? document.elementFromPoint(e.clientX, e.clientY)?.closest<HTMLElement>("[data-scenario]")
        : null;
    const id = under?.dataset.scenario;
    return id && id !== except ? id : boxAt(local(e), except);
  };
  const hovered = linking ? boxAt(linking.to, linking.from) : null;

  const links = items.flatMap((p) =>
    p.section.branches.map((b, j) => {
      const from = boxes.get(p.section.id);
      const to = boxes.get(b.target);
      if (!from || !to) return null;
      const lit =
        selected == null || selected === p.section.id || selected === b.target;
      return {
        key: `${p.section.id}-${j}`,
        d: link(
          { x: from.x + from.w, y: from.y + from.h / 2 },
          { x: to.x, y: to.y + to.h / 2 },
        ),
        color: toneColor(b.when),
        lit,
      };
    }),
  );

  return (
    <>
    <div
      className="relative max-h-[78dvh] overflow-auto rounded-card border border-line bg-surface-muted"
      role="region"
      aria-label="The call flow, step by step"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a region that scrolls must take focus, or no key can scroll it
      tabIndex={0}
    >
      <div ref={plane} className="relative" style={{ width, height }}>
        {/* Column bands, each a step: a right click on one adds to it. */}
        {Array.from({ length: steps }, (_, i) => i + 1).map((step) => (
          <div
            key={step}
            className={`absolute top-0 rounded-card ${step % 2 ? "bg-surface/40" : ""}`}
            style={{
              left: colX(step) - BAND_INSET,
              width: BOX_W + 2 * BAND_INSET,
              height,
            }}
            onContextMenu={(e) => onMenu(e, null, step)}
          >
            <div className="px-3 pt-3" style={{ height: HEAD_H }}>
              <div className="flex items-center justify-between">
                <span className="text-meta font-semibold text-ink">
                  Step {step}
                </span>
                {!readOnly && (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-brand-strong hover:bg-brand/10 disabled:opacity-40"
                    disabled={full}
                    onClick={() => onAdd(step)}
                    aria-label={`Add a scenario to step ${step}`}
                  >
                    <Plus aria-hidden className="h-3 w-3" />
                    Scenario
                  </button>
                )}
              </div>
              <div className="mt-1.5">
                <StepOutcomeField
                  step={step}
                  value={outcome(step)}
                  readOnly={readOnly}
                  compact
                  onChange={(text) => onOutcome(step, text)}
                />
              </div>
            </div>
          </div>
        ))}
        {!readOnly && (
          <button
            type="button"
            className="absolute inline-flex items-center gap-1 rounded-card border border-dashed border-line bg-surface px-3 py-2 text-meta text-ink-muted hover:border-ink-faint hover:text-ink disabled:opacity-40"
            style={{
              left: usedEnds.length ? endX : colX(steps + 1),
              top: usedEnds.length
                ? PAD + HEAD_H + usedEnds.length * (END_H + ROW_GAP) + 8
                : PAD + HEAD_H,
            }}
            disabled={full}
            onClick={() => onAdd(steps + 1)}
          >
            <Plus aria-hidden className="h-3.5 w-3.5" />
            Add step {steps + 1}
          </button>
        )}

        <svg
          className="pointer-events-none absolute inset-0"
          width={width}
          height={height}
          aria-hidden
        >
          {links.map(
            (l) =>
              l && (
                <path
                  key={l.key}
                  d={l.d}
                  fill="none"
                  style={{ stroke: l.color, opacity: l.lit ? 1 : 0.25 }}
                  strokeWidth={l.lit && selected ? 2.25 : 1.75}
                />
              ),
          )}
          {links.map((l) => {
            if (!l) return null;
            const end = l.d.split(" ").slice(-2).map(Number);
            return (
              <path
                key={`${l.key}-head`}
                d={`M ${end[0] - 8} ${end[1] - 5} L ${end[0]} ${end[1]} L ${end[0] - 8} ${end[1] + 5} z`}
                style={{ fill: l.color, opacity: l.lit ? 1 : 0.25 }}
              />
            );
          })}
          {linking && boxes.get(linking.from) && (
            <path
              d={link(
                {
                  x: (boxes.get(linking.from) as Box).x + BOX_W,
                  y: (boxes.get(linking.from) as Box).y + BOX_H / 2,
                },
                linking.to,
              )}
              fill="none"
              className="stroke-brand"
              strokeWidth={2}
              strokeDasharray="4 4"
            />
          )}
        </svg>

        {usedEnds.map((t) => {
          const b = boxes.get(t) as Box;
          return (
            <span
              key={t}
              className="absolute flex items-center justify-center rounded-full border border-dashed border-ink-faint bg-surface px-3 text-meta text-ink-muted"
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
            >
              {END_NAMES[t]}
            </span>
          );
        })}

        {items.map((p) => {
          const b = boxes.get(p.section.id) as Box;
          const on = selected === p.section.id;
          const wrong = issues.some((i) => i.section === p.section.id);
          const scripts = Object.keys(p.section.scripts ?? {}).length;
          const qa = p.section.qa?.length ?? 0;
          return (
            <div
              key={p.section.id}
              data-scenario={p.section.id}
              className={`absolute rounded-card ${hovered === p.section.id ? "ring-2 ring-brand ring-offset-2" : ""}`}
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
            >
              <button
                type="button"
                aria-pressed={on}
                aria-label={`Scenario ${p.label}: ${p.section.name}${wrong ? ", needs finishing" : ""}`}
                className={`flex h-full w-full flex-col rounded-card border bg-surface p-3 text-left shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  on
                    ? "border-brand ring-1 ring-brand"
                    : wrong
                      ? "border-danger"
                      : "border-line hover:border-ink-faint"
                }`}
                onClick={() => onSelect(on ? null : p.section.id)}
                onContextMenu={(e) => onMenu(e, p.section.id, p.step)}
              >
                <span className="flex w-full items-center gap-2">
                  <span className="inline-flex h-5 min-w-8 items-center justify-center rounded-full bg-series-2 px-1.5 text-[11px] font-semibold tabular-nums text-white">
                    {p.label}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-body font-semibold text-ink">
                    {p.section.name.trim() || "Untitled"}
                  </span>
                </span>
                <span className="mt-1 line-clamp-2 text-meta text-ink-muted">
                  {p.section.instruction.trim() || "No description yet."}
                </span>
                <span className="mt-auto truncate text-[11px] text-ink-faint">
                  {[
                    p.section.mode === "say" ? "Exact words" : null,
                    scripts
                      ? `Script in ${scripts} ${scripts === 1 ? "language" : "languages"}`
                      : null,
                    qa ? `${qa} Q&A` : null,
                    p.section.branches.length
                      ? `${p.section.branches.length} next`
                      : "No next yet",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </button>
              {!readOnly && (
                <>
                  <button
                    type="button"
                    className="absolute right-1.5 top-1.5 rounded p-0.5 text-ink-faint hover:bg-ink/[0.06] hover:text-ink"
                    aria-label={`More for scenario ${p.label}`}
                    onClick={(e) => onMenu(e, p.section.id, p.step)}
                  >
                    <MoreHorizontal aria-hidden className="h-4 w-4" />
                  </button>
                  <div
                    aria-hidden
                    title="Drag to a scenario to make it a next scenario"
                    className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 cursor-crosshair touch-none rounded-full border-2 border-surface bg-brand-strong before:absolute before:-inset-3 before:content-['']"
                    onPointerDown={(e: ReactPointerEvent<HTMLDivElement>) => {
                      if (e.button !== 0) return;
                      e.stopPropagation();
                      e.currentTarget.setPointerCapture(e.pointerId);
                      setLinkNote(null);
                      setLinking({ from: p.section.id, to: local(e) });
                    }}
                    onPointerMove={(e) =>
                      linking && setLinking({ ...linking, to: local(e) })
                    }
                    onPointerUp={(e) => {
                      if (!linking) return;
                      const target = dropTarget(e, linking.from);
                      setLinking(null);
                      setLinkNote(
                        target
                          ? onLink(linking.from, target)
                          : "Let go on a scenario to make it a next scenario.",
                      );
                    }}
                    onPointerCancel={() => setLinking(null)}
                  />
                </>
              )}
              {readOnly && (
                <span
                  aria-hidden
                  className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-surface bg-brand-strong"
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
    <p role="status" className="mt-2 min-h-5 text-meta text-ink-muted">
      {linkNote}
    </p>
    </>
  );
}

/** Below the desktop width: each step a block of scenario cards, the editor under the chosen one. */
function Stacked({
  items,
  steps,
  selected,
  readOnly,
  full,
  onSelect,
  onAdd,
  onMenu,
  editor,
  outcome,
  onOutcome,
}: {
  items: Placed[];
  steps: number;
  selected: string | null;
  readOnly: boolean;
  full: boolean;
  onSelect: (id: string | null) => void;
  onAdd: (step: number) => void;
  onMenu: (e: ReactMouseEvent, id: string | null, step: number) => void;
  editor: React.ReactNode;
  outcome: (step: number) => string;
  onOutcome: (step: number, text: string) => void;
}) {
  const labelOf = (target: string) =>
    lookup(END_NAMES, target) ?? items.find((p) => p.section.id === target)?.label ?? "?";
  return (
    <div className="space-y-5">
      {Array.from({ length: steps }, (_, i) => i + 1).map((step) => (
        <section
          key={step}
          aria-label={`Step ${step}`}
          className="border-l-4 border-series-2 pl-3"
        >
          <div className="flex items-center justify-between">
            <h4 className="text-body font-semibold text-ink">Step {step}</h4>
            {!readOnly && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={full}
                onClick={() => onAdd(step)}
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                Scenario
              </button>
            )}
          </div>
          <div className="mt-2">
            <StepOutcomeField
              step={step}
              value={outcome(step)}
              readOnly={readOnly}
              compact={false}
              onChange={(text) => onOutcome(step, text)}
            />
          </div>
          <ul className="mt-2 space-y-2">
            {items
              .filter((p) => p.step === step)
              .map((p) => (
                <li
                  key={p.section.id}
                  className="rounded-card border border-line bg-surface"
                >
                  <button
                    type="button"
                    aria-expanded={selected === p.section.id}
                    className="w-full p-3 text-left"
                    onClick={() =>
                      onSelect(selected === p.section.id ? null : p.section.id)
                    }
                    onContextMenu={(e) => onMenu(e, p.section.id, p.step)}
                  >
                    <span className="flex items-center gap-2">
                      <span className="rounded-full bg-series-2 px-1.5 text-[11px] font-semibold text-white">
                        {p.label}
                      </span>
                      <span className="font-semibold text-ink">
                        {p.section.name}
                      </span>
                      {p.section.mode === "say" && (
                        <span className="ml-auto shrink-0 text-[11px] text-ink-muted">
                          Exact words
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block text-meta text-ink-muted">
                      {p.section.instruction}
                    </span>
                    {p.section.branches.length > 0 && (
                      <span className="mt-1 block text-[11px] text-ink-faint">
                        Next:{" "}
                        {p.section.branches
                          .map((b) => labelOf(b.target))
                          .join(", ")}
                      </span>
                    )}
                  </button>
                  {selected === p.section.id && (
                    <div className="border-t border-line">{editor}</div>
                  )}
                </li>
              ))}
          </ul>
        </section>
      ))}
      {!readOnly && (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={full}
          onClick={() => onAdd(steps + 1)}
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add step {steps + 1}
        </button>
      )}
    </div>
  );
}

/** A scenario's own editor: number, step, name, description, scripts, Q&A, next scenarios. */
function ScenarioEditor({
  item,
  items,
  steps,
  script,
  limits,
  issues,
  languages,
  readOnly,
  agent,
  hear,
  wide,
  onChange,
  onDelete,
}: {
  agent: FlowAgent | null;
  hear: WriteAccess;
  /** Under the picture at full width: three columns. */
  wide: boolean;
  item: Placed;
  items: Placed[];
  steps: number;
  script: CallScript;
  limits: Limits;
  issues: Issue[];
  languages: string[];
  readOnly: boolean;
  onChange: (next: CallScript) => void;
  onDelete: () => void;
}) {
  const s = item.section;
  const id = s.id;
  const patch = (p: Parameters<typeof updateSection>[2]) =>
    onChange(updateSection(script, id, p));
  const scripts = s.scripts ?? {};
  // A line written before scenarios ("how it sounds") becomes the main language's script.
  const main = languages[0];
  const legacy =
    main && !scripts[main] && s.sounds_like.trim() ? s.sounds_like : "";
  const qa = s.qa ?? [];
  const next = s.branches.map((b) => b.target);
  const issue = (field: string) =>
    issues.find((i) => i.field === field)?.message;
  const toggleNext = (target: string, on: boolean) =>
    onChange(
      setNext(
        script,
        id,
        on ? [...next, target] : next.filter((t) => t !== target),
      ),
    );
  const label = (cls = "") => `block text-meta font-medium text-ink ${cls}`;

  const english = "en-IN";
  // English and the campaign's main language only (founder, 17 Nov 2026: Hindi boxes off
  // for now); a campaign in English has the one script.
  const local = main && main !== english ? main : null;
  // English's script box only where the campaign speaks English or the scenario already has
  // an English line (founder, 23 Nov 2026): a Telugu-only campaign showed an empty English
  // box nobody fills. The caller-and-agent answers keep English as their base either way.
  const showEnglish =
    !local || languages.includes(english) || Boolean(scripts[english]?.trim());
  const scriptBox = (tag: string) => (
    <div key={tag}>
      <label className={label()} htmlFor={`sc-${tag}-${id}`}>
        Script in {languageName(tag)}
      </label>
      <p className="text-meta text-ink-muted">What the agent says here.</p>
      <textarea
        id={`sc-${tag}-${id}`}
        className={`${FIELD} mt-1 min-h-24`}
        value={scripts[tag] ?? (tag === main ? legacy : "")}
        maxLength={1000}
        readOnly={readOnly}
        onChange={(e) => {
          const nextScripts = { ...scripts, [tag]: e.target.value };
          if (!e.target.value.trim()) delete nextScripts[tag];
          patch(
            tag === main && legacy
              ? { scripts: nextScripts, sounds_like: "" }
              : { scripts: nextScripts },
          );
        }}
      />
      <HearLine
        agent={agent}
        access={hear}
        language={tag}
        line={scripts[tag] ?? (tag === main ? legacy : "")}
      />
    </div>
  );
  const setQa = (i: number, change: Partial<(typeof qa)[number]>) =>
    patch({ qa: qa.map((r, j) => (j === i ? { ...r, ...change } : r)) });
  const setLocalQa = (
    i: number,
    field: "question" | "answer",
    value: string,
  ) => {
    if (!local) return;
    const row = qa[i];
    const held = row.translations?.[local] ?? { question: "", answer: "" };
    setQa(i, {
      translations: {
        ...(row.translations ?? {}),
        [local]: { ...held, [field]: value },
      },
    });
  };
  const nextChoice = (target: string, text: ReactNode) => (
    <label
      key={target}
      className="flex items-center gap-2 py-0.5 text-meta text-ink"
    >
      <input
        type="checkbox"
        className="h-4 w-4 accent-brand-strong"
        checked={next.includes(target)}
        disabled={
          readOnly ||
          (!next.includes(target) && next.length >= limits.maxBranches)
        }
        onChange={(e) => toggleNext(target, e.target.checked)}
      />
      {text}
    </label>
  );

  // Two columns side by side, English left and the local language beside it; the right
  // column holds where the call goes next (founder, 17 Nov 2026).
  const pair = wide ? "grid gap-x-6 gap-y-3 lg:grid-cols-2" : "space-y-3";
  const toLocal = local ? languageName(local) : "";

  return (
    <div className="space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full bg-series-2 px-2 py-0.5 text-meta font-semibold tabular-nums text-white">
          Scenario {item.label}
        </span>
        <div className="min-w-0 flex-1">
          {agent && !agent.id ? agent.missing : null}
        </div>
        <label className="flex items-center gap-1.5 text-meta text-ink">
          Step
          <select
            className="rounded border border-line bg-surface px-1.5 py-0.5 text-meta"
            value={item.step}
            disabled={readOnly}
            onChange={(e) =>
              onChange(moveToStep(script, id, Number(e.target.value)))
            }
          >
            {Array.from({ length: steps + 1 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n > steps ? `${n} (new)` : n}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div
        className={
          wide
            ? "grid gap-x-6 gap-y-6 lg:grid-cols-[minmax(0,1fr)_16rem]"
            : "space-y-5"
        }
      >
        {/* English and the local language, side by side. */}
        <div className="min-w-0 space-y-5">
          <div className={`${SECTION} border-l-series-2 bg-series-2/5`}>
            <label className={label()} htmlFor={`sc-name-${id}`}>
              Scenario name
            </label>
            <input
              id={`sc-name-${id}`}
              className={`${FIELD} mt-1 lg:max-w-[calc(50%-0.75rem)]`}
              value={s.name}
              maxLength={limits.nameMax}
              readOnly={readOnly}
              placeholder="For example: Does not remember us"
              aria-invalid={issue("name") ? true : undefined}
              onChange={(e) =>
                onChange(renameScenario(script, id, e.target.value))
              }
            />
            {issue("name") && (
              <p className="mt-1 text-meta text-danger">{issue("name")}</p>
            )}

            <div className="mt-4">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <label className={label("inline")} htmlFor={`sc-desc-${id}`}>
                  Scenario description
                </label>
                <span className="text-meta text-ink-muted">
                  When this happens and what the agent does, in plain English.
                </span>
              </p>
              <textarea
                id={`sc-desc-${id}`}
                className={`${FIELD} mt-1 min-h-20`}
                value={s.instruction}
                readOnly={readOnly}
                aria-invalid={issue("instruction") ? true : undefined}
                onChange={(e) => patch({ instruction: e.target.value })}
              />
              {issue("instruction") && (
                <p className="mt-1 text-meta text-danger">
                  {issue("instruction")}
                </p>
              )}
            </div>
          </div>

          <div className={pair}>
            {showEnglish ? (
              <div className={`${SECTION} border-l-series-2 bg-series-2/5`}>
                {scriptBox(english)}
              </div>
            ) : null}
            {local ? (
              <div className={`${SECTION} border-l-series-6 bg-series-6/5`}>
                {scriptBox(local)}
              </div>
            ) : null}
          </div>

          <ToggleSwitch
            label="Say this line exactly"
            hint="On: the agent says the script line word for word. Off: it says it in its own words."
            checked={s.mode === "say"}
            disabled={readOnly}
            // The step is written out so a section drawn before scenarios is read as a
            // scenario (its description is never said), and a line it held as "how it
            // sounds" becomes its script line, as typing in the box does.
            onChange={(on) =>
              patch(
                !on
                  ? { mode: "guide" }
                  : main && legacy
                    ? {
                        mode: "say",
                        step: item.step,
                        scripts: { ...scripts, [main]: legacy },
                        sounds_like: "",
                      }
                    : { mode: "say", step: item.step },
              )
            }
          >
            {s.mode === "say" && !saysScenarioLine(s) && (
              <p className="ml-12 mt-1 text-meta text-ink-muted">
                Write the script line above. Until then the agent uses its own
                words.
              </p>
            )}
          </ToggleSwitch>

          <fieldset
            className={`min-w-0 ${SECTION} border-l-series-5 bg-series-5/5`}
          >
            <legend className={`${label()} rounded bg-surface px-1`}>
              Caller and agent responses
            </legend>
            <p className="text-meta text-ink-muted">
              What the caller may say here and what the agent answers, in
              English{local ? ` and ${toLocal}` : ""}.
            </p>
            <ul className="mt-3 space-y-3">
              {qa.map((row, i) => {
                const held = local
                  ? (row.translations?.[local] ?? { question: "", answer: "" })
                  : null;
                return (
                  <li
                    key={i}
                    className="rounded-card border border-line bg-surface p-3"
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-meta font-medium text-ink">
                        Response {i + 1}
                      </span>
                      {!readOnly && (
                        <button
                          type="button"
                          className="text-meta text-danger hover:underline"
                          onClick={() =>
                            patch({ qa: qa.filter((_, j) => j !== i) })
                          }
                          aria-label={`Remove response ${i + 1}`}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                    <div className={pair}>
                      <label className="block text-meta text-ink-muted">
                        Caller (English)
                        <input
                          className={`${FIELD} mt-0.5`}
                          placeholder="What the caller says"
                          value={row.question}
                          maxLength={300}
                          readOnly={readOnly}
                          onChange={(e) =>
                            setQa(i, { question: e.target.value })
                          }
                        />
                      </label>
                      {local && held ? (
                        <label className="block text-meta text-ink-muted">
                          Caller ({toLocal})
                          <input
                            className={`${FIELD} mt-0.5`}
                            value={held.question}
                            maxLength={300}
                            readOnly={readOnly}
                            onChange={(e) =>
                              setLocalQa(i, "question", e.target.value)
                            }
                          />
                        </label>
                      ) : null}
                      <div>
                        <label className="block text-meta text-ink-muted">
                          Agent (English)
                          <textarea
                            className={`${FIELD} mt-0.5 min-h-14`}
                            placeholder="What the agent answers"
                            value={row.answer}
                            maxLength={1000}
                            readOnly={readOnly}
                            onChange={(e) =>
                              setQa(i, { answer: e.target.value })
                            }
                          />
                        </label>
                        <HearLine
                          agent={agent}
                          access={hear}
                          language={english}
                          line={row.answer}
                        />
                      </div>
                      {local && held ? (
                        <div>
                          <label className="block text-meta text-ink-muted">
                            Agent ({toLocal})
                            <textarea
                              className={`${FIELD} mt-0.5 min-h-14`}
                              value={held.answer}
                              maxLength={1000}
                              readOnly={readOnly}
                              onChange={(e) =>
                                setLocalQa(i, "answer", e.target.value)
                              }
                            />
                          </label>
                          <HearLine
                            agent={agent}
                            access={hear}
                            language={local}
                            line={held.answer}
                          />
                        </div>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
            {!readOnly && (
              <button
                type="button"
                className={`${SECONDARY_BUTTON_SM} mt-3`}
                disabled={qa.length >= 10}
                onClick={() =>
                  patch({ qa: [...qa, { question: "", answer: "" }] })
                }
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                Add a caller response
              </button>
            )}
            {issues.some((i) => i.field.startsWith("qa")) && (
              <p className="mt-1 text-meta text-danger">
                Fill in the English caller and agent words, or remove the row.
              </p>
            )}
          </fieldset>
        </div>

        {/* Right: where the call goes next. */}
        <fieldset
          className={`min-w-0 self-start ${SECTION} border-l-series-4 bg-series-4/5`}
        >
          <legend className={`${label()} rounded bg-surface px-1`}>
            Next scenarios
          </legend>
          <p className="text-meta text-ink-muted">
            Where the call can go from here. Up to {limits.maxBranches}.
          </p>
          <div className="mt-2 space-y-3">
            {Array.from({ length: steps }, (_, i) => i + 1).map((step) => {
              const choices = items.filter(
                (p) => p.step === step && p.section.id !== id,
              );
              if (choices.length === 0) return null;
              return (
                <div key={step}>
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                    Step {step}
                  </p>
                  {choices.map((p) =>
                    nextChoice(
                      p.section.id,
                      <span>
                        <span className="tabular-nums text-ink-muted">
                          {p.label}
                        </span>{" "}
                        {p.section.name}
                      </span>,
                    ),
                  )}
                </div>
              );
            })}
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                End points
              </p>
              {SPECIAL_TARGETS.map((t) => nextChoice(t, END_NAMES[t]))}
            </div>
          </div>
          {s.branches.length === 0 && (
            <p className="mt-2 text-meta text-ink-muted">
              With none chosen, the call goes on to the next scenario in order.
            </p>
          )}
        </fieldset>
      </div>

      {!readOnly && (
        <div className="border-t border-line pt-4">
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} border-danger text-danger`}
            onClick={onDelete}
          >
            <Trash2 aria-hidden className="h-3.5 w-3.5" />
            Delete scenario {item.label}
          </button>
        </div>
      )}
    </div>
  );
}

/** The right-click menu, at the pointer; Escape, a click outside or a choice closes it. */
function ContextMenu({
  menu,
  items,
  onClose,
}: {
  menu: Menu;
  items: {
    label: string;
    icon?: React.ReactNode;
    danger?: boolean;
    disabled?: boolean;
    run: () => void;
  }[];
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e instanceof MouseEvent && box.current?.contains(e.target as Node))
        return;
      onClose();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    window.addEventListener("scroll", onClose, true);
    box.current
      ?.querySelector<HTMLButtonElement>("button:not([disabled])")
      ?.focus();
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose]);
  const left = Math.min(
    menu.x,
    (typeof window === "undefined" ? 9999 : window.innerWidth) - 240,
  );
  const top = Math.min(
    menu.y,
    (typeof window === "undefined" ? 9999 : window.innerHeight) -
      items.length * 36 -
      16,
  );
  return (
    <div
      ref={box}
      role="menu"
      className="fixed z-modal w-56 rounded-card border border-line bg-surface py-1 shadow-overlay"
      style={{ left, top }}
    >
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          disabled={item.disabled}
          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-meta hover:bg-ink/[0.05] disabled:opacity-40 ${item.danger ? "text-danger" : "text-ink"}`}
          onClick={() => {
            onClose();
            item.run();
          }}
        >
          <span className="w-3.5" aria-hidden>
            {item.icon}
          </span>
          {item.label}
        </button>
      ))}
    </div>
  );
}
