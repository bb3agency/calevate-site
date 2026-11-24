"use client";

/**
 * THE CALL FLOW IN STEPS AND SCENARIOS (founder, 17 Nov 2026). Each column is a step of the
 * call; each box in it a scenario (2.1, 2.2, …). A scenario's green dot leads to the
 * scenarios it can go on to, drawn as arrows into the left of their boxes. A box is chosen
 * with a click (its editor opens beside the picture), and a right click offers what can be
 * done to it. Dragging from the dot onto another box links them; a link is removed where it
 * is drawn (`Columns`), from its box's menu, or from the "Next" chips when stacked.
 *
 * The call's opening is the first box, left of step 1 and linked into it, because every call
 * starts with those words and whether now suits; "not now" points to the end it reaches.
 * How the links are routed is `flowLayout`'s.
 *
 * Laid out by the steps, not by hand: the columns ARE the structure, so a picture somebody
 * dragged out of shape cannot disagree with the call order. Below the desktop width the
 * columns stack, and the links read as "Next: 3.1, 3.2" in each box.
 */

import {
  ArrowDown,
  ArrowUp,
  LoaderCircle,
  MoreHorizontal,
  Plus,
  Trash2,
  Unlink,
  X,
} from "lucide-react";
import {
  Fragment,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { TextShimmer } from "@/components/arc/text-shimmer";
import { useToast } from "@/components/arc/toast";
import { SegmentedControl } from "@/components/interior/segmented-control";
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
  openingOf,
  outcomeOf,
  placed,
  renameScenario,
  setNext,
  setOutcome,
  shiftInStep,
  type Placed,
} from "./scenarioModel";
import {
  CALL_BACK,
  END,
  SPECIAL_TARGETS,
  chars,
  saysScenarioLine,
  sectionsOf,
  updateSection,
  type Issue,
  type Limits,
} from "../agents/[agentId]/script/scriptModel";
import {
  BAND_INSET,
  BOX_H,
  BOX_W,
  DROP_MARGIN,
  END_H,
  HEAD_H,
  NOT_NOW_GAP,
  OPENING_KEY,
  ROW_GAP,
  arrowHead,
  curve,
  layoutFlow,
  type Box,
  type Point,
} from "./flowLayout";

/** A coloured block of the scenario editor: each kind of content keeps its own colour. */
const SECTION = "rounded-card border border-line border-l-4 p-3";

const OUTCOME_HINT =
  "What must be true before the call moves on. The agent reaches it however the call goes; the scenarios are examples.";
/** An empty outcome is Pip's to write (D-1036), never a box asking the owner to invent it. */
export const OUTCOME_PLACEHOLDER = "Pip writes this from the step.";
export const OUTCOME_WRITING = "Pip is writing this";

/**
 * A step's outcome (founder, 23 Nov 2026): what the agent must reach before the call leaves
 * the step, by whichever scenario. `compact` is the canvas column, which has room for the
 * field but not the hint, so the hint is read with it by a screen reader and shown once
 * above the canvas instead. While Pip writes an empty one (`writing`), the app's loader sits
 * beside the label; the box stays editable.
 */
function StepOutcomeField({
  step,
  value,
  readOnly,
  compact,
  writing,
  onChange,
}: {
  step: number;
  value: string;
  readOnly: boolean;
  compact: boolean;
  writing: boolean;
  onChange: (next: string) => void;
}) {
  const id = useId();
  const used = chars(value);
  const busy = writing && !value.trim();
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="block text-meta font-medium text-ink">
          Outcome of this step
          <span className="sr-only">, step {step}</span>
        </label>
        {busy && (
          <span className="inline-flex items-center gap-1 text-[11px] text-ink-muted">
            <LoaderCircle aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
            <TextShimmer>{OUTCOME_WRITING}</TextShimmer>
          </span>
        )}
      </div>
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
        placeholder={busy ? undefined : OUTCOME_PLACEHOLDER}
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

/** The opening as the flow draws it: the line as stored, and where "not now" goes. */
export interface FlowOpening {
  line: string;
  /** The line is a "both" agent's first words on a call it places (D-920). */
  placed: boolean;
  /** A caller who cannot talk now is asked when suits them where call backs are offered,
   * else the call closes politely (`OPENING_CONTINUES_RULE`, `NO_CALL_BACKS_POLICY`). */
  notNow: string;
}

export function flowOpening(script: CallScript): FlowOpening {
  const { line, placed: onPlaced } = openingOf(script);
  return {
    line,
    placed: onPlaced,
    notNow: script.policies?.offer_call_backs === false ? END : CALL_BACK,
  };
}

type Menu = { x: number; y: number; id: string | null; step: number };

export function ScenarioFlow({
  script,
  limits,
  issues,
  languages,
  selected,
  readOnly,
  outcomesPending = false,
  wide,
  onSelect,
  onChange,
  onUndo,
  agent,
  hear,
  onEditOpening,
}: {
  /** The canvas's own Undo, offered by the toast after a link is removed. */
  onUndo?: () => void;
  /** Opens the script where the opening line is edited; absent when this person cannot. */
  onEditOpening?: () => void;
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
  /** Pip is writing the outcome of each step that has none (D-1036). */
  outcomesPending?: boolean;
  /** The picture beside the editor (desktop); false stacks the steps. */
  wide: boolean;
  onSelect: (id: string | null) => void;
  /** `discrete`: one deliberate act, its own Undo step (`CampaignFlow.commit`). */
  onChange: (next: CallScript, discrete?: boolean) => void;
}) {
  const items = useMemo(() => placed(sectionsOf(script)), [script]);
  const steps = Math.max(0, ...items.map((p) => p.step));
  const full = items.length >= limits.maxSections;
  const opening = useMemo(() => flowOpening(script), [script]);
  const [menu, setMenu] = useState<Menu | null>(null);
  const toasts = useToast();

  // Where a link goes, as people read it: "3.1 Setup farms", or an end's own words.
  const named = (target: string) => {
    const end = lookup(END_NAMES, target);
    if (end) return { short: end, full: end };
    const p = items.find((q) => q.section.id === target);
    return p
      ? { short: p.label, full: `${p.label} ${p.section.name.trim() || "Untitled"}` }
      : { short: "?", full: "?" };
  };

  // The toast's Undo is the canvas's Undo, so it is offered only while the removal is still
  // the latest change: once anything else changes, that Undo would take back something else.
  const unlinked = useRef<{ toast: string; after: CallScript } | null>(null);
  // The toast outlives the render that made it, whose `onUndo` still sees no history.
  const undoLatest = useRef(onUndo);
  useEffect(() => {
    undoLatest.current = onUndo;
  }, [onUndo]);
  useEffect(() => {
    const last = unlinked.current;
    if (last && last.after !== script) {
      toasts.dismiss(last.toast);
      unlinked.current = null;
    }
  }, [script, toasts]);

  /** Removes one link: the same `setNext` the editor's "Next scenarios" ticks go through. */
  const unlink = (from: string, to: string) => {
    const source = items.find((p) => p.section.id === from);
    if (!source) return;
    const after = setNext(
      script,
      from,
      source.section.branches.map((b) => b.target).filter((t) => t !== to),
    );
    onChange(after, true);
    const toast = toasts.toast({
      id: "flow-unlink",
      kind: "success",
      title: `Unlinked ${source.label} → ${named(to).short}`,
      action: onUndo
        ? {
            label: "Undo",
            onClick: () => {
              if (unlinked.current?.after === after) undoLatest.current?.();
            },
          }
        : undefined,
    });
    unlinked.current = { toast, after };
  };

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
      for (const b of item.section.branches)
        list.push({
          label: `Unlink from ${named(b.target).full}`,
          icon: <Unlink className="h-3.5 w-3.5" />,
          run: () => unlink(item.section.id, b.target),
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
        writing={outcomesPending}
        outcome={(step) => outcomeOf(script, step)}
        onOutcome={(step, text) => onChange(setOutcome(script, step, text))}
        opening={opening}
        onEditOpening={onEditOpening}
        onUnlink={readOnly ? undefined : unlink}
        named={(id) => named(id).full}
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
            true,
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
        writing={outcomesPending}
        outcome={(step) => outcomeOf(script, step)}
        onOutcome={(step, text) => onChange(setOutcome(script, step, text))}
        editor={editor}
        opening={opening}
        onEditOpening={onEditOpening}
        onUnlink={readOnly ? undefined : unlink}
        named={(id) => named(id).full}
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

/** The desktop picture: the opening, a column per step, arrows from each green dot onwards. */
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
  writing,
  opening,
  onEditOpening,
  onUnlink,
  named,
}: {
  /** Removes the link `from` → `to`; absent for a person who cannot change the flow. */
  onUnlink?: (from: string, to: string) => void;
  /** "3.1 Setup farms", or an end's words, for a link's spoken name. */
  named: (id: string) => string;
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
  writing: boolean;
  opening: FlowOpening | null;
  onEditOpening?: () => void;
}) {
  const plane = useRef<HTMLDivElement>(null);
  const [linking, setLinking] = useState<{ from: string; to: Point } | null>(
    null,
  );
  const [linkNote, setLinkNote] = useState<string | null>(null);
  // The box the pointer or the keyboard is on: its links stay lit, the rest dim, as for the
  // chosen one.
  const [pointed, setPointed] = useState<string | null>(null);
  const layout = useMemo(
    () =>
      layoutFlow(items, SPECIAL_TARGETS, opening ? { notNow: opening.notNow } : null),
    [items, opening],
  );
  const { colX, boxes, usedEnds, width, height, cardTop } = layout;
  const endX = colX(steps + 1);

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

  // A link is a target of its own, as in node-graph editors: React Flow draws an invisible
  // wider path around each edge "to make them easier to click or tap on", and selects one
  // with a click for its delete key (`interactionWidth`, `deleteKeyCode` default
  // 'Backspace': reactflow.dev/api-reference/types/edge and /react-flow); n8n shows a delete
  // button on the connection the pointer is over (docs.n8n.io/workflows/connections). Here
  // the removal control is a real button at the link's middle, so a keyboard reaches it
  // with Tab after the box the link leaves, and Delete, Backspace or Enter removes it.
  const [chosenLink, setChosenLink] = useState<string | null>(null);
  const [hoverLink, setHoverLink] = useState<string | null>(null);
  const leave = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (leave.current) clearTimeout(leave.current);
  }, []);
  const unlinkButtons = useRef(new Map<string, HTMLButtonElement>());
  const removable = (l: { from: string; kind: string }) =>
    Boolean(onUnlink) && l.from !== OPENING_KEY && l.kind !== "not-now";
  const hoverOn = (key: string) => {
    if (leave.current) clearTimeout(leave.current);
    setHoverLink(key);
  };
  // A short grace on leaving, so the pointer can cross from the thin line onto its button.
  const hoverOff = (key: string) => {
    if (leave.current) clearTimeout(leave.current);
    leave.current = setTimeout(() => setHoverLink((h) => (h === key ? null : h)), 150);
  };
  const removeLink = (l: { from: string; to: string }) => {
    setChosenLink(null);
    setHoverLink(null);
    onUnlink?.(l.from, l.to);
    // The button goes with its link; focus lands on the box the link left, not the page.
    Array.from(plane.current?.querySelectorAll<HTMLElement>("[data-scenario]") ?? [])
      .find((el) => el.dataset.scenario === l.from)
      ?.querySelector<HTMLButtonElement>(":scope > button")
      ?.focus();
  };

  const activeLink = layout.links.some((l) => l.key === (chosenLink ?? hoverLink))
    ? (chosenLink ?? hoverLink)
    : null;
  const focus = selected ?? pointed;
  const links = layout.links.map((l) => ({
    ...l,
    lit: activeLink
      ? activeLink === l.key
      : focus == null || focus === l.from || focus === l.to,
  }));
  const strong = activeLink != null || focus != null;
  const middle = (l: (typeof links)[number]) =>
    l.samples[Math.floor(l.samples.length / 2)] ?? l.end;
  const point = (id: string) => ({
    onPointerEnter: () => setPointed(id),
    onPointerLeave: () => setPointed((p) => (p === id ? null : p)),
    onFocus: () => setPointed(id),
    onBlur: () => setPointed((p) => (p === id ? null : p)),
  });

  const band = (key: string | number, left: number, children: ReactNode, step?: number) => (
    <div
      key={key}
      className={`absolute top-0 rounded-card ${typeof step === "number" && step % 2 === 0 ? "" : "bg-surface/40"}`}
      style={{ left: left - BAND_INSET, width: BOX_W + 2 * BAND_INSET, height }}
      onContextMenu={step ? (e) => onMenu(e, null, step) : undefined}
    >
      <div className="px-3 pt-3" style={{ height: HEAD_H }}>
        {children}
      </div>
    </div>
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
        {opening &&
          band(
            "opening",
            colX(0),
            <>
              <span className="text-meta font-semibold text-ink">Opening</span>
              <p className="mt-1.5 text-meta text-ink-muted">
                Every call starts here: the first words, then whether now suits.
              </p>
            </>,
          )}
        {/* Column bands, each a step: a right click on one adds to it. */}
        {Array.from({ length: steps }, (_, i) => i + 1).map((step) =>
          band(
            step,
            colX(step),
            <>
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
                  writing={writing}
                  onChange={(text) => onOutcome(step, text)}
                />
              </div>
            </>,
            step,
          ),
        )}
        {!readOnly && (
          <button
            type="button"
            className="absolute inline-flex items-center gap-1 rounded-card border border-dashed border-line bg-surface px-3 py-2 text-meta text-ink-muted hover:border-ink-faint hover:text-ink disabled:opacity-40"
            style={{
              left: endX,
              top: usedEnds.length
                ? cardTop + usedEnds.length * (END_H + ROW_GAP) + 8
                : cardTop,
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
          {links.map((l) => (
            <path
              key={l.key}
              data-link={l.key}
              data-kind={l.kind}
              d={l.d}
              fill="none"
              style={{ stroke: l.color, opacity: l.lit ? 1 : 0.25 }}
              strokeWidth={l.lit && strong ? 2.25 : 1.75}
            />
          ))}
          {/* Each removable link's wide, invisible hit path: a click or a tap chooses it. */}
          {links.filter(removable).map((l) => (
            <path
              key={`${l.key}-hit`}
              data-link-hit={l.key}
              d={l.d}
              fill="none"
              stroke="transparent"
              strokeWidth={16}
              className="cursor-pointer"
              style={{ pointerEvents: "stroke" }}
              onPointerEnter={() => hoverOn(l.key)}
              onPointerLeave={() => hoverOff(l.key)}
              onClick={(e) => {
                e.stopPropagation();
                setChosenLink(l.key);
                unlinkButtons.current.get(l.key)?.focus({ preventScroll: true });
              }}
            />
          ))}
          {links.map((l) => (
            <path
              key={`${l.key}-head`}
              d={arrowHead(l.end, l.dir)}
              style={{ fill: l.color, opacity: l.lit ? 1 : 0.25 }}
            />
          ))}
          {linking && boxes.get(linking.from) && (
            <path
              d={curve(
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

        {opening && layout.opening && (
          <OpeningNode
            box={layout.opening}
            opening={opening}
            onEdit={onEditOpening}
            pointer={point(OPENING_KEY)}
          />
        )}
        {layout.notNow && (
          <>
            <span
              className="absolute text-[11px] font-medium text-ink-muted"
              style={{
                left: layout.notNow.box.x + layout.notNow.box.w / 2 + 8,
                top: layout.notNow.box.y - NOT_NOW_GAP / 2 - 8,
              }}
            >
              Not now
            </span>
            <span
              className="absolute flex items-center justify-center rounded-full border border-dashed border-ink-faint bg-surface px-3 text-meta text-ink-muted"
              style={{
                left: layout.notNow.box.x,
                top: layout.notNow.box.y,
                width: layout.notNow.box.w,
                height: layout.notNow.box.h,
              }}
            >
              {lookup(END_NAMES, layout.notNow.target)}
            </span>
          </>
        )}

        {usedEnds.map((t) => {
          const b = boxes.get(t) as Box;
          return (
            <span
              key={t}
              className="absolute flex items-center justify-center rounded-full border border-dashed border-ink-faint bg-surface px-3 text-meta text-ink-muted"
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
              {...point(t)}
            >
              {lookup(END_NAMES, t)}
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
            <Fragment key={p.section.id}>
            <div
              data-scenario={p.section.id}
              className={`absolute rounded-card ${hovered === p.section.id ? "ring-2 ring-brand ring-offset-2" : ""}`}
              style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
              {...point(p.section.id)}
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
            {/* Its links' remove buttons, next in Tab order to the box they leave. */}
            {links
              .filter((l) => l.from === p.section.id && removable(l))
              .map((l) => {
                const m = middle(l);
                const shown = activeLink === l.key;
                return (
                  <button
                    key={`${l.key}-unlink`}
                    ref={(el) => {
                      if (el) unlinkButtons.current.set(l.key, el);
                      else unlinkButtons.current.delete(l.key);
                    }}
                    type="button"
                    data-unlink={l.key}
                    data-shown={shown}
                    aria-label={`Remove the link from ${named(l.from)} to ${named(l.to)}`}
                    aria-keyshortcuts="Delete Backspace"
                    title="Remove this link"
                    className="absolute flex h-6 w-6 scale-90 items-center justify-center rounded-full border border-line bg-surface text-ink-muted opacity-0 shadow-raised transition-[opacity,transform] duration-fast ease-out pointer-events-none before:absolute before:-inset-2 before:content-[''] hover:border-danger hover:text-danger focus-visible:pointer-events-auto focus-visible:scale-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand active:scale-[0.97] data-[shown=true]:pointer-events-auto data-[shown=true]:scale-100 data-[shown=true]:opacity-100 motion-reduce:scale-100 motion-reduce:transition-opacity"
                    style={{ left: m.x - 12, top: m.y - 12 }}
                    onPointerEnter={() => hoverOn(l.key)}
                    onPointerLeave={() => hoverOff(l.key)}
                    onFocus={() => setChosenLink(l.key)}
                    onBlur={() => setChosenLink((c) => (c === l.key ? null : c))}
                    onClick={() => removeLink(l)}
                    onKeyDown={(e) => {
                      if (e.key === "Delete" || e.key === "Backspace") {
                        e.preventDefault();
                        removeLink(l);
                      } else if (e.key === "Escape") {
                        // Deselects the link only; the full-screen dialog stays open.
                        e.preventDefault();
                        e.stopPropagation();
                        setChosenLink(null);
                        e.currentTarget.blur();
                      }
                    }}
                  >
                    <X aria-hidden className="h-3.5 w-3.5" />
                  </button>
                );
              })}
            </Fragment>
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

/**
 * The call's first words, the flow's first box: read-only here, since the opening is part of
 * the script and its notices are woven into it (D-971); a click opens the script where it is
 * edited. No dot: nothing links out of it but the steps it always goes on to.
 */
function OpeningNode({
  box,
  opening,
  onEdit,
  pointer,
}: {
  box: Box;
  opening: FlowOpening;
  onEdit?: () => void;
  pointer: Record<string, () => void>;
}) {
  const body = (
    <>
      <span className="flex w-full items-center gap-2">
        <span className="inline-flex h-5 items-center justify-center rounded-full bg-series-1 px-2 text-[11px] font-semibold text-white">
          {opening.placed ? "Opening when it calls" : "Opening"}
        </span>
      </span>
      <span className="mt-1 line-clamp-3 text-meta text-ink">
        {opening.line ? `“${opening.line}”` : "No opening line yet."}
      </span>
      {onEdit && (
        <span className="mt-auto text-[11px] font-medium text-brand-strong">
          Edit in the script
        </span>
      )}
    </>
  );
  const shell =
    "flex h-full w-full flex-col rounded-card border border-series-1/50 bg-surface p-3 text-left shadow-card";
  return (
    <div
      className="absolute rounded-card"
      style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
      {...pointer}
    >
      {onEdit ? (
        <button
          type="button"
          aria-label={`Opening: ${opening.line || "no opening line yet"}. Edit it in the script.`}
          className={`${shell} hover:border-series-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand`}
          onClick={onEdit}
        >
          {body}
        </button>
      ) : (
        <div className={shell}>{body}</div>
      )}
    </div>
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
  writing,
  opening,
  onEditOpening,
  onUnlink,
  named,
}: {
  opening: FlowOpening;
  onEditOpening?: () => void;
  onUnlink?: (from: string, to: string) => void;
  named: (id: string) => string;
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
  writing: boolean;
}) {
  const labelOf = (target: string) =>
    lookup(END_NAMES, target) ?? items.find((p) => p.section.id === target)?.label ?? "?";
  return (
    <div className="space-y-5">
      <section aria-label="Opening" className="border-l-4 border-series-1 pl-3">
        <h4 className="text-body font-semibold text-ink">
          {opening.placed ? "Opening when it calls" : "Opening"}
        </h4>
        <p className="mt-1 text-meta text-ink">
          {opening.line ? `“${opening.line}”` : "No opening line yet."}
        </p>
        <p className="mt-1 text-[11px] text-ink-faint">
          Next:{" "}
          {items
            .filter((p) => p.step === 1)
            .map((p) => p.label)
            .join(", ")}
          {" · "}Not now: {lookup(END_NAMES, opening.notNow)}
        </p>
        {onEditOpening && (
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} mt-2`}
            onClick={onEditOpening}
          >
            Edit in the script
          </button>
        )}
      </section>
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
              writing={writing}
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
                  </button>
                  {/* Outside the box's button, so each chip can carry its own remove button. */}
                  {p.section.branches.length > 0 && (
                    <div className="-mt-1 flex flex-wrap items-center gap-1.5 px-3 pb-3 text-[11px] text-ink-faint">
                      <span>Next:</span>
                      {p.section.branches.map((b) => (
                        <span
                          key={b.target}
                          data-next-chip={b.target}
                          className={`inline-flex items-center rounded-full border border-line tabular-nums text-ink-muted ${onUnlink ? "py-0.5 pl-2 pr-0.5" : "px-2 py-0.5"}`}
                        >
                          {labelOf(b.target)}
                          {onUnlink && (
                            <button
                              type="button"
                              aria-label={`Remove the link from ${named(p.section.id)} to ${named(b.target)}`}
                              className="relative ml-0.5 flex h-5 w-5 items-center justify-center rounded-full text-ink-faint transition-transform duration-press ease-out before:absolute before:-inset-2 before:content-[''] hover:bg-ink/[0.06] hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand active:scale-[0.97] motion-reduce:transition-none"
                              onClick={() => onUnlink(p.section.id, b.target)}
                            >
                              <X aria-hidden className="h-3 w-3" />
                            </button>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
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
  onChange: (next: CallScript, discrete?: boolean) => void;
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
      true,
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
  // One script box with a language switch rather than a box per language (founder, 24 Nov
  // 2026): a campaign may speak seven or eight languages. Every language it speaks is
  // reachable, main first, and a line already written in a language it no longer speaks
  // stays reachable rather than hidden.
  const scriptTags = [
    ...new Set([
      ...(main ? [main] : []),
      ...languages.filter((t) => t !== english),
      ...(showEnglish ? [english] : []),
      ...Object.keys(scripts).filter((t) => scripts[t]?.trim()),
    ]),
  ];
  const written = (tag: string) =>
    Boolean((scripts[tag] ?? (tag === main ? legacy : "")).trim());
  const [scriptTag, setScriptTag] = useState(scriptTags[0] ?? english);
  const shownTag = scriptTags.includes(scriptTag) ? scriptTag : (scriptTags[0] ?? english);
  const unwritten = scriptTags.filter((t) => !written(t)).length;
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

          <div className={`${SECTION} border-l-series-6 bg-series-6/5`}>
            {scriptTags.length > 1 ? (
              <div className="mb-3">
                <SegmentedControl
                  label="Script language"
                  value={shownTag}
                  onValueChange={setScriptTag}
                  options={scriptTags.map((tag) => ({
                    value: tag,
                    label: languageName(tag),
                    dot: written(tag) ? undefined : "bg-ink-faint",
                  }))}
                />
                {unwritten > 0 ? (
                  <p className="mt-1 text-meta text-ink-muted">
                    A dot marks a language with no line yet.
                  </p>
                ) : null}
              </div>
            ) : null}
            {scriptBox(shownTag)}
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
          <span className="min-w-0 truncate">{item.label}</span>
        </button>
      ))}
    </div>
  );
}
