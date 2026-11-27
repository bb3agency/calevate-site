"use client";

/**
 * AN AI PROPOSAL, REVIEWED BEFORE IT TOUCHES ANYTHING.
 *
 * Every change is its own row with its own "Keep" box, all kept to start with; the owner
 * unticks what they do not want and only the rest is applied to their draft (`applyChanges`).
 * Nothing goes live from here: the draft still waits for "Put it live".
 *
 * Each suggestion can be reworded before it is kept (D-831): "Review" opens the row's fields
 * on a tinted ground, an edit ticks the row, and "Reset to suggestion" puts Pip's words back.
 * "Cancel" puts the row back as it was when "Review" was pressed; "Update" settles it, and the
 * row then shows only the final wording, without the Now/Suggested pair it was judged from,
 * and its button reads "Edit": editing it again opens that final wording alone, never the
 * comparison.
 * The edited values go through the same `applyChanges` and the builder's own `validate`, so
 * a kept change can
 * never be one the builder would refuse; a problem is shown on the row that caused it and
 * holds "Add" until it is fixed.
 *
 * `base` is the script the proposal was made from, when that is not the working copy (a
 * suggestion Pip wrote earlier, D-820): the changes are listed against it, so an edit the
 * owner made since is never offered back, and the kept ones are applied to `current`.
 */

import { Fragment, useMemo, useRef, useState, type ReactNode } from "react";

import { ExpandableText } from "@/components/arc/expandable-text";
import { ActionButton } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM, type NoticeTone } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";
import { keepInView } from "@/lib/keepInView";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { placed } from "../../../campaigns/scenarioModel";
import { PartEditor, SectionFields, partShows, sectionShows, unshownIssues } from "./ProposalEditors";
import { GeneratePart, type GeneratePartProps } from "./GeneratePart";
import { ExamplesReadout, WarningLines } from "./StepExamplesEditor";
import { exampleLanguages, partWarnings, stageWarnings, type LineWarning } from "./stepExamples";
import {
  applyTraced,
  changedSegments,
  diffScripts,
  keptAtFirstWithin,
  partText,
  removesContent,
  renamedOnly,
  spoken,
  type Change,
  type PartKey,
} from "./scriptDiff";
import {
  DEFAULT_LIMITS,
  sectionReadable,
  sectionsOf,
  validate,
  type Issue,
  type Limits,
  type Section,
} from "./scriptModel";

/** The row a script-wide problem from `validate` belongs to. */
const PART_OF_FIELD: { test: RegExp; part: PartKey }[] = [
  { test: /^business_line$/, part: "business_line" },
  { test: /^outbound_purpose$/, part: "outbound_purpose" },
  { test: /^objection-\d+$/, part: "objections" },
  { test: /^fact-\d+$/, part: "faqs" },
  { test: /^example-\d+$/, part: "example_exchange" },
  { test: /^pronunciation-\d+$/, part: "style" },
];

/** The suggested section a row carries, by its id in the proposal. */
function suggestedId(change: Change): string | null {
  return change.kind === "section-added" || change.kind === "section-changed" ? change.after.id : null;
}

/** A row's key in Pip's "why" notes: the part's name, or `stages.<id>` for a step (D-1004). */
export function whyKey(change: Change): string | null {
  if (change.kind === "part") return change.part;
  const id = suggestedId(change);
  return id ? `stages.${id}` : null;
}

/** Parts a person adds entries to (founder, 16 Nov 2026: "allow user to add further Q&As").
 * While editing, each has its row even when it holds nothing yet, placed after the parts that
 * come before it. */
const ADDABLE: { part: PartKey; label: string; after: PartKey[] }[] = [
  { part: "faqs", label: "Quick facts", after: ["business_line", "identity", "goal", "outbound_purpose", "opening_line", "outbound_opening_line"] },
  { part: "objections", label: "When callers push back", after: ["faqs", "style"] },
];

function withAddableParts(changes: Change[]): Change[] {
  const out = [...changes];
  for (const { part, label, after } of ADDABLE) {
    if (out.some((c) => c.kind === "part" && c.part === part)) continue;
    let at = 0;
    out.forEach((c, i) => {
      if (c.kind === "part" && (after.includes(c.part) || ADDABLE.some((a) => a.part === c.part && after.includes(a.part)))) at = i + 1;
    });
    out.splice(at, 0, { id: `part:${part}`, kind: "part", part, label, before: "", after: "" });
  }
  return out;
}

/** Pip's reason for a part, behind a tap so the list stays short (D-1004). */
function WhyNote({ what, note }: { what: string; note: string }) {
  const [shown, setShown] = useState(false);
  return (
    <>
      <button
        type="button"
        className={`${TEXT_ACTION} text-meta`}
        aria-expanded={shown}
        aria-label={`Why Pip wrote ${what}`}
        onClick={() => setShown((was) => !was)}
      >
        Why?
      </button>
      {shown && <p className="basis-full pt-1 text-meta text-ink-muted [overflow-wrap:anywhere]">{note}</p>}
    </>
  );
}

/** A row's id as an element id: the change ids carry ":". */
function domId(change: Change): string {
  return `proposal-${change.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export function ProposalReview({
  current,
  base,
  proposal,
  onApply,
  onDiscard,
  pending = null,
  gate,
  limits = DEFAULT_LIMITS,
  language = "your callers' language",
  editing = false,
  generatePart,
  notes,
  languages = [],
  warnings = [],
  children,
}: {
  /** The call's languages, main first, each with its name: a step's examples are per language. */
  languages?: { tag: string; name: string }[];
  /** The checks' warnings on single lines of the draft (`stages.<id>.examples…`), shown on
   *  the line each is about. */
  warnings?: readonly LineWarning[];
  /** While editing: Pip rewrites one part in a chosen language (a campaign's script). */
  generatePart?: GeneratePartProps;
  /** Pip's reason for each part it wrote, by `whyKey`, shown behind "Why?" on its row. */
  notes?: Record<string, string>;
  /** Editing a script already kept, not reviewing a suggestion: every part starts as final
   * wording with an Edit button, nothing is ticked or labelled "Added", and the button saves. */
  editing?: boolean;
  current: CallScript;
  /** What the proposal was made from, when that is not `current`. */
  base?: CallScript;
  proposal: CallScript;
  onApply: (next: CallScript) => void;
  onDiscard: () => void;
  /** Which of the two is on its way to the server. Both wait while either is: a Discard
   * pressed while Add is still clearing would win, and the kept changes would be lost. */
  pending?: "apply" | "discard" | null;
  /** A reason "Keep" must wait (the owner has not confirmed the unplaced lines yet). */
  gate?: string | null;
  /** The builder's limits, so an edited suggestion is held to the same ones. */
  limits?: Limits;
  /** The call language in words, for the hints on lines the agent says. */
  language?: string;
  /** Shown above the changes: the server's account of how it was written, unplaced lines. */
  children?: ReactNode;
}) {
  const changes = useMemo(() => {
    const listed = diffScripts(base ?? current, proposal);
    return editing ? withAddableParts(listed) : listed;
  }, [base, current, proposal, editing]);
  // What the owner did to the draft since Pip wrote this: a change to a step they deleted
  // has nothing left to apply to, and one to a step or part they edited replaces their edit.
  const since = useMemo(() => sinceWritten(changes, base, current), [changes, base, current]);
  // A removal starts unticked: the owner keeps it only after looking at it (A-04), unless
  // the new steps alone would go over the step limit.
  const [ticked, setKept] = useState<Set<string>>(() =>
    keptAtFirstWithin(current, proposal, changes, limits.maxSections),
  );
  const kept = useMemo(() => new Set([...ticked].filter((id) => since.get(id) !== "deleted")), [ticked, since]);
  const offered = changes.filter((c) => since.get(c.id) !== "deleted").length;
  // The proposal as the owner reworded it. The parent keys this component by proposal id,
  // so a new suggestion always starts from Pip's own words.
  const [edited, setEdited] = useState<CallScript>(proposal);
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [tried, setTried] = useState(false);
  // Rows the owner settled with "Update": only the final wording shows.
  const [settled, setSettled] = useState<Set<string>>(() => (editing ? new Set(changes.map((c) => c.id)) : new Set()));
  // Rows whose "Update" was refused, so their problems show although nothing was typed.
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  // Each open row as it stood when "Review" was pressed, for "Cancel".
  const opened = useRef(new Map<string, { edited: CallScript; touched: boolean; kept: boolean; settled: boolean }>());
  // The owner's rewording lives only here until "Add", so leaving the tab or the page asks.
  useUnsavedGuard(touched.size > 0);
  const list = useRef<HTMLUListElement>(null);
  const keptCount = changes.filter((c) => kept.has(c.id)).length;

  const result = useMemo(() => applyTraced(current, proposal, kept, edited), [current, proposal, kept, edited]);
  const issuesByRow = useMemo(() => {
    const rows = new Map<string, Issue[]>();
    const add = (change: Change | undefined, issue: Issue) => {
      if (!change || !kept.has(change.id)) return;
      rows.set(change.id, [...(rows.get(change.id) ?? []), issue]);
    };
    for (const issue of validate(result.script, limits)) {
      if (issue.section !== null) {
        const from = result.from.get(issue.section);
        add(from ? changes.find((c) => suggestedId(c) === from) : undefined, issue);
      } else {
        const part = PART_OF_FIELD.find((p) => p.test.test(issue.field))?.part;
        add(changes.find((c) => c.kind === "part" && c.part === part), issue);
      }
    }
    return rows;
  }, [result, limits, changes, kept]);
  const blocked = changes.filter((c) => issuesByRow.has(c.id));
  // Too many steps belongs to no one row, so it is said beside the button.
  const steps = sectionsOf(result.script).length;
  const tooMany = steps > limits.maxSections;

  const setIn = (setter: typeof setKept, id: string, on: boolean) =>
    setter((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  /** An edit is a decision to keep the change, so it ticks the row. */
  const editRow = (change: Change, next: CallScript) => {
    setEdited(next);
    setIn(setTouched, change.id, true);
    setIn(setKept, change.id, true);
  };

  const editSection = (change: Change, id: string, patch: Partial<Section>) =>
    editRow(change, {
      ...edited,
      stages: sectionsOf(edited).map((s) => (s.id === id ? { ...s, ...patch, id } : s)),
    });

  /** Put one row's words back from `from`, leaving every other row's edits alone. */
  const restore = (change: Change, from: CallScript) => {
    if (change.kind === "part") {
      setEdited((e) => ({ ...e, [change.part]: from[change.part] }));
    } else {
      const id = suggestedId(change);
      const original = sectionsOf(from).find((s) => s.id === id);
      setEdited((e) => ({ ...e, stages: sectionsOf(e).map((s) => (s.id === id && original ? original : s)) }));
    }
  };

  const reset = (change: Change) => {
    restore(change, proposal);
    setIn(setTouched, change.id, false);
    setIn(setSettled, change.id, false);
  };

  const openRow = (id: string) => {
    if (!opened.current.has(id)) {
      opened.current.set(id, { edited, touched: touched.has(id), kept: kept.has(id), settled: settled.has(id) });
    }
    setIn(setOpen, id, true);
  };

  const closeRow = (id: string) => {
    opened.current.delete(id);
    setIn(setOpen, id, false);
    setIn(setChecked, id, false);
  };

  const cancel = (change: Change) => {
    const was = opened.current.get(change.id);
    if (was) {
      restore(change, was.edited);
      setIn(setTouched, change.id, was.touched);
      setIn(setKept, change.id, was.kept);
      setIn(setSettled, change.id, was.settled);
    }
    closeRow(change.id);
  };

  /** The builder's problems with this row, judged as if it were kept (Update keeps it). */
  const problemsIfKept = (change: Change): Issue[] => {
    const traced = applyTraced(current, proposal, new Set([...kept, change.id]), edited);
    return validate(traced.script, limits).filter((issue) =>
      issue.section !== null
        ? traced.from.get(issue.section) === suggestedId(change)
        : change.kind === "part" && PART_OF_FIELD.find((p) => p.test.test(issue.field))?.part === change.part,
    );
  };

  /** Settle a row: it is kept, and only its final wording shows. A row with a problem stays open. */
  const update = (change: Change) => {
    setIn(setKept, change.id, true);
    if (problemsIfKept(change).length > 0) {
      setIn(setChecked, change.id, true);
      return;
    }
    setIn(setSettled, change.id, true);
    closeRow(change.id);
  };

  const add = () => {
    if (blocked.length > 0) {
      setTried(true);
      blocked.forEach((c) => openRow(c.id));
      // After the rows open, the first field to fix takes the focus. Centred, because the
      // page header is sticky and a field scrolled to the top would sit under it.
      requestAnimationFrame(() => {
        const field = list.current?.querySelector<HTMLElement>("[aria-invalid='true']");
        field?.focus({ preventScroll: true });
        field?.scrollIntoView?.({ block: "center" });
      });
      return;
    }
    onApply(result.script);
  };

  return (
    <section aria-labelledby="proposal-heading" className="space-y-4">
      <div>
        <h3 id="proposal-heading" className="text-heading text-ink">
          {editing ? "Edit your script" : changes.length === 1 ? "1 suggested change" : `${changes.length} suggested changes`}
        </h3>
        <p className="mt-1 text-meta text-ink-muted">
          {editing ? "Press Edit on any part to change it, then save." : "Untick or review any. Kept ones go to your draft, not live."}
        </p>
        {!editing && changes.length > 1 && (
          <ul aria-label="Changes by kind" className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {tally(changes).map((line) => (
              <li key={line.tone}>
                <StatusPill tone={line.tone}>{line.label}</StatusPill>
              </li>
            ))}
          </ul>
        )}
      </div>
      {children}
      {changes.length === 0 ? (
        <p className="text-body text-ink-muted">Same as your script. Nothing to change.</p>
      ) : (
        <ul ref={list} className="divide-y divide-line border-y border-line">
          {changes.map((change) => {
            const on = kept.has(change.id);
            const rowIssues = issuesByRow.get(change.id) ?? [];
            const shownIssues = tried || touched.has(change.id) || checked.has(change.id) ? rowIssues : [];
            const isOpen = open.has(change.id);
            const isSettled = settled.has(change.id);
            const key = whyKey(change);
            return (
              <Row
                key={change.id}
                why={key ? notes?.[key] : undefined}
                change={change}
                kept={on}
                edited={touched.has(change.id)}
                open={isOpen}
                settled={isSettled}
                final={editing}
                since={since.get(change.id)}
                onKeep={(next) => setIn(setKept, change.id, next)}
                onEdit={() => openRow(change.id)}
                onUpdate={() => update(change)}
                onCancel={() => cancel(change)}
                onReset={() => reset(change)}
                generate={
                  generatePart && editing ? (
                    <GeneratePart
                      {...generatePart}
                      what={headline(change)}
                      held={touched.size > 0 ? "Save or close your edits first." : undefined}
                    />
                  ) : undefined
                }
              >
                {change.kind === "order" ? (
                  <OrderBody change={change} />
                ) : change.kind === "part" ? (
                  <PartBody
                    change={change}
                    edited={edited}
                    open={isOpen}
                    settled={isSettled}
                    issues={shownIssues}
                    language={language}
                    warnings={warnings}
                    onChange={(next) => editRow(change, next)}
                  />
                ) : (
                  <SectionBody
                    change={change}
                    edited={edited}
                    open={isOpen}
                    settled={isSettled}
                    issues={shownIssues}
                    limits={limits}
                    language={language}
                    languages={languages}
                    warnings={warnings}
                    generate={generatePart && editing ? generatePart : undefined}
                    onChange={(id, patch) => editSection(change, id, patch)}
                  />
                )}
              </Row>
            );
          })}
        </ul>
      )}
      {/* The one primary action stays in reach however long the list is. */}
      <div className="sticky bottom-0 -mx-1 space-y-2 border-t border-line bg-surface px-1 pb-1 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            variant="primary-sm"
            status={pending === "apply" ? "pending" : "idle"}
            pendingLabel={editing ? "Saving…" : "Adding…"}
            disabled={
              (editing ? touched.size === 0 : keptCount === 0) || tooMany || Boolean(gate) || pending === "discard"
            }
            title={gate ?? undefined}
            onClick={add}
          >
            {editing
              ? "Save changes"
              : keptCount === offered && offered > 0
                ? offered === 1
                  ? "Add it to my draft"
                  : `Add all ${offered} to my draft`
                : `Add ${keptCount} of ${offered} to my draft`}
          </ActionButton>
          <ActionButton
            variant="secondary-sm"
            status={pending === "discard" ? "pending" : "idle"}
            pendingLabel={editing ? "Close" : "Discarding…"}
            onClick={onDiscard}
            disabled={pending === "apply"}
          >
            {editing ? "Close" : "Discard"}
          </ActionButton>
        </div>
        {gate && <p className="text-meta text-ink-muted">{gate}</p>}
        {tooMany && (
          <p role="alert" className="text-meta text-danger">
            {`Over ${limits.maxSections} steps. Tick the steps this replaces.`}
          </p>
        )}
        {tried && blocked.length > 0 && (
          <p role="alert" className="text-meta text-danger">
            {blocked.length === 1
              ? `Fix “${blocked[0].label}” first, or untick it.`
              : `Fix the ${blocked.length} changes marked above first, or untick them.`}
          </p>
        )}
      </div>
    </section>
  );
}

/** One change: its keep box and name, then what is there now and the suggestion. */
function Row({
  change,
  kept,
  edited,
  open,
  settled,
  final = false,
  since,
  onKeep,
  onEdit,
  onUpdate,
  onCancel,
  onReset,
  generate,
  why,
  children,
}: {
  generate?: ReactNode;
  /** Pip's reason for this part, when it wrote one. */
  why?: string;
  change: Change;
  kept: boolean;
  edited: boolean;
  open: boolean;
  settled: boolean;
  /** Part of a script already kept: no keep box and no kind of change, only its name. */
  final?: boolean;
  since?: Since;
  onKeep: (on: boolean) => void;
  onEdit: () => void;
  onUpdate: () => void;
  onCancel: () => void;
  onReset: () => void;
  children: ReactNode;
}) {
  const id = domId(change);
  const gone = since === "deleted";
  // The row stays where it is on screen while it opens or closes and the page reflows.
  const row = useRef<HTMLLIElement>(null);
  const held = (act: () => void) => () => {
    keepInView(row.current);
    act();
  };
  const editable = !gone && change.kind !== "section-removed" && change.kind !== "order";
  return (
    // An unticked change fades, so what will be applied is visible at a glance; the row being
    // edited sits on a tinted ground so the eye stays on it.
    <li
      ref={row}
      data-editing={open || undefined}
      className={`flex items-start gap-3 py-3 transition-[opacity,background-color] duration-150 ${
        open
          ? "-mx-3 rounded-lg bg-brand-soft px-3 ring-1 ring-brand/40 dark:bg-brand-strong/20"
          : kept
            ? ""
            : "opacity-55"
      }`}
    >
      {!final && (
        <input
          id={`${id}-keep`}
          type="checkbox"
          className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[var(--brand-strong)]"
          checked={kept}
          disabled={gone}
          onChange={(e) => onKeep(e.target.checked)}
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {final ? (
            <span className="text-body font-medium text-ink">{headline(change)}</span>
          ) : (
            <label htmlFor={`${id}-keep`} className="cursor-pointer text-body font-medium text-ink">
              {headline(change)}
            </label>
          )}
          {/* Once updated there is one final version, so nothing says what it changed from. */}
          {final ? (
            edited && <span className="text-meta font-medium text-brand-strong">Edited, not saved yet</span>
          ) : settled ? (
            <span className="text-meta font-medium text-brand-strong">Reviewed by you</span>
          ) : (
            <>
              <StatusPill tone={kindTone(change)}>{kindLabel(change)}</StatusPill>
              {edited && <span className="text-meta font-medium text-brand-strong">Edited by you</span>}
            </>
          )}
        </div>
        {since && !settled && (
          <p className={`mt-1 text-meta ${gone ? "text-ink-muted" : "text-warn"}`}>{SINCE_NOTE[since](change)}</p>
        )}
        {children}
        {editable &&
          (open ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" className={PRIMARY_BUTTON_SM} aria-label={`Update ${headline(change)}`} onClick={held(onUpdate)}>
                Update
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Cancel ${settled ? "editing" : "reviewing"} ${headline(change)}`}
                onClick={held(onCancel)}
              >
                Cancel
              </button>
              {edited && !settled && (
                <button type="button" className={`${TEXT_ACTION} ml-2 text-meta`} onClick={onReset}>
                  Reset to suggestion
                </button>
              )}
            </div>
          ) : (
            <div className="mt-1.5 flex flex-wrap gap-x-4">
              <button
                type="button"
                className={`${TEXT_ACTION} text-meta`}
                aria-expanded={false}
                aria-label={`${settled ? "Edit" : "Review"} ${headline(change)}`}
                onClick={held(onEdit)}
              >
                {/* Reviewed once, a row is final: further changes are edits, not a review. */}
                {settled ? "Edit" : "Review"}
              </button>
              {why && <WhyNote what={headline(change)} note={why} />}
              {generate}
              {edited && !settled && (
                <button type="button" className={`${TEXT_ACTION} text-meta`} onClick={onReset}>
                  Reset to suggestion
                </button>
              )}
            </div>
          ))}
      </div>
    </li>
  );
}

/**
 * The suggestion's fields under the brand rule, where its text was. A row already updated is
 * edited as the final wording alone, so it carries no "Suggested" label.
 */
function Editing({ id, final = false, children }: { id: string; final?: boolean; children: ReactNode }) {
  return (
    <div id={`${id}-edit`} className="border-l-2 border-brand pl-3">
      {!final && <p className="mb-1 text-meta font-medium text-ink-muted">Suggested</p>}
      {children}
    </div>
  );
}

function PartBody({
  change,
  edited,
  open,
  settled,
  issues,
  language,
  warnings,
  onChange,
}: {
  change: Extract<Change, { kind: "part" }>;
  edited: CallScript;
  open: boolean;
  settled: boolean;
  issues: Issue[];
  language: string;
  warnings: readonly LineWarning[];
  onChange: (next: CallScript) => void;
}) {
  const id = domId(change);
  const suggested = partText(edited, change.part);
  const flagged = <WarningLines warnings={partWarnings(warnings, change.part)} idBase={`${id}-warn`} />;
  if (settled && !open)
    return (
      <>
        <Settled text={suggested} issues={issues} />
        {flagged}
      </>
    );
  return (
    <div className="mt-1.5 space-y-1.5">
      {change.before && !settled && <Quote tone="before" text={change.before} against={suggested || undefined} />}
      {open ? (
        <Editing id={id} final={settled}>
          <PartEditor part={change.part} script={edited} idBase={id} issues={issues} language={language} onChange={onChange} />
          <RowErrors issues={unshownIssues(issues, partShows)} />
          {flagged}
        </Editing>
      ) : (
        <>
          <Quote tone="after" text={suggested || "(left empty)"} against={change.before || undefined} />
          {flagged}
          <RowErrors issues={issues} />
        </>
      )}
    </div>
  );
}

/** A move: the steps in order now and as suggested, numbered as the step list numbers them. */
function OrderBody({ change }: { change: Extract<Change, { kind: "order" }> }) {
  const numbered = (names: string[]) => names.map((name, i) => `${i + 1}. ${name}`).join("\n");
  return (
    <div className="mt-1.5 space-y-1.5">
      <Quote tone="before" text={numbered(change.before)} />
      <Quote tone="after" text={numbered(change.after)} />
    </div>
  );
}

function SectionBody({
  change,
  edited,
  open,
  settled,
  issues,
  limits,
  language,
  languages,
  warnings,
  generate,
  onChange,
}: {
  change: Exclude<Change, { kind: "part" } | { kind: "order" }>;
  edited: CallScript;
  open: boolean;
  settled: boolean;
  issues: Issue[];
  limits: Limits;
  language: string;
  languages: { tag: string; name: string }[];
  warnings: readonly LineWarning[];
  generate?: GeneratePartProps;
  onChange: (id: string, patch: Partial<Section>) => void;
}) {
  if (change.kind === "section-removed") {
    return (
      <div className="mt-1.5">
        <Quote tone="before" text={sectionReadable(change.before)} />
      </div>
    );
  }
  const id = domId(change);
  const after = sectionsOf(edited).find((s) => s.id === change.after.id) ?? change.after;
  const renamed = change.kind === "section-changed" && change.before.name !== after.name;
  const before =
    change.kind === "section-changed"
      ? [renamed && `Name: ${change.before.name}`, sectionReadable(change.before)].filter(Boolean).join("\n")
      : "";
  const suggested = [renamed && `Name: ${after.name}`, sectionReadable(after)].filter(Boolean).join("\n");
  const first = placed(sectionsOf(edited)).find((p) => p.section.id === after.id)?.step === 1;
  // The examples Pip wrote, in each language, for reading without opening the row.
  const named = new Map(languages.map((l) => [l.tag, l.name]));
  const readout = (
    <ExamplesReadout
      stageId={after.id}
      examples={after.examples}
      languages={exampleLanguages(after.examples, languages.map((l) => l.tag)).map((tag) => ({
        tag,
        name: named.get(tag) ?? tag,
      }))}
      first={first}
      warnings={warnings}
    />
  );
  // The checks' findings on the step outside its examples, which sit on their own lines.
  const flagged = <WarningLines warnings={stageWarnings(warnings, after.id, null)} idBase={`${id}-warn`} />;
  if (settled && !open)
    return (
      <>
        <Settled text={suggested} issues={issues} />
        {flagged}
        <div className="mt-1.5">{readout}</div>
      </>
    );
  return (
    <div className="mt-1.5 space-y-1.5">
      {before && !settled && <Quote tone="before" text={before} against={suggested || undefined} />}
      {open ? (
        <Editing id={id} final={settled}>
          <SectionFields
            section={after}
            idBase={id}
            issues={issues}
            limits={limits}
            language={language}
            languages={languages}
            first={first}
            warnings={warnings}
            generate={generate}
            onChange={(patch) => onChange(after.id, patch)}
          />
          <RowErrors issues={unshownIssues(issues, sectionShows)} />
          {flagged}
        </Editing>
      ) : (
        <>
          <Quote tone="after" text={suggested || "(left empty)"} against={before || undefined} />
          {flagged}
          {readout}
          <RowErrors issues={issues} />
        </>
      )}
    </div>
  );
}

/** A row the owner settled with "Update": the wording that goes to the draft, nothing to compare. */
function Settled({ text, issues }: { text: string; issues: Issue[] }) {
  return (
    <div className="mt-1.5">
      <div className="border-l-2 border-brand-strong pl-3 text-meta text-ink">
        <span className="sr-only">Final wording: </span>
        <ExpandableText lines={4} moreLabel="Show all" textClassName="whitespace-pre-wrap">
          {text || "(left empty)"}
        </ExpandableText>
      </div>
      <RowErrors issues={issues} />
    </div>
  );
}

type Since = "deleted" | "changed";

const SINCE_NOTE: Record<Since, (change: Change) => string> = {
  deleted: () => "You deleted this step after Pip wrote this.",
  changed: (change) =>
    change.kind === "part"
      ? "You changed this since. Keeping this replaces your change."
      : "You changed this step. Keeping this replaces your edit.",
};

/**
 * Each change's standing against what the owner did to the draft after Pip wrote it from
 * `base`, read from the same comparison the review lists (`diffScripts(base, current)`).
 * A step the owner deleted is `deleted`: `applyTraced` has nothing to apply the change to
 * and drops it, so it cannot be kept or counted. A step or part they edited is `changed`:
 * keeping it puts Pip's whole step or part over their edit, which the row says.
 */
function sinceWritten(changes: readonly Change[], base: CallScript | undefined, current: CallScript): Map<string, Since> {
  const out = new Map<string, Since>();
  if (!base) return out;
  const owner = new Set(diffScripts(base, current).map((c) => c.id));
  for (const change of changes) {
    if (change.kind === "part") {
      if (owner.has(change.id)) out.set(change.id, "changed");
    } else if (change.kind === "section-changed" || change.kind === "section-removed") {
      if (owner.has(`remove:${change.before.id}`)) out.set(change.id, "deleted");
      else if (change.kind === "section-changed" && owner.has(`change:${change.before.id}`)) out.set(change.id, "changed");
    }
  }
  return out;
}

function RowErrors({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  return <p className="mt-2 text-meta text-danger">{issues.map((i) => i.message).join(" ")}</p>;
}

export function headline(change: Change): string {
  return change.label;
}

/** What kind of change a row is, said quietly beside its name rather than in it. */
export function kindLabel(change: Change): string {
  switch (change.kind) {
    case "part":
      if (removesContent(change)) return "Pip removes this";
      return change.before ? "Changed" : "Added";
    case "section-added":
      return "New step";
    case "section-removed":
      return "Pip removes this step";
    case "section-changed":
      if (renamedOnly(change)) return "Step renamed";
      return change.before.name.trim() !== change.after.name.trim() ? "Step renamed and changed" : "Step changed";
    case "order":
      return "Steps moved";
  }
}

/**
 * How loud a row's kind is. What changes the call (a step or part added, changed or taken
 * away) carries a tone; a rename or a move, which changes nothing a caller hears, stays quiet.
 * The word beside the dot says it, so the tone is never the only signal.
 */
export function kindTone(change: Change): NoticeTone {
  switch (change.kind) {
    case "part":
      if (removesContent(change)) return "stop";
      return change.before ? "warn" : "ok";
    case "section-added":
      return "ok";
    case "section-removed":
      return "stop";
    case "section-changed":
      return renamedOnly(change) ? "neutral" : "warn";
    case "order":
      return "info";
  }
}

/** The counts above the list: what is new, changed and removed, for a glance at the size. */
export function tally(changes: readonly Change[]): { tone: NoticeTone; label: string }[] {
  const count = (tone: NoticeTone) => changes.filter((c) => kindTone(c) === tone).length;
  const lines: { tone: NoticeTone; n: number; label: (n: number) => string }[] = [
    { tone: "ok", n: count("ok"), label: (n) => `${n} new` },
    { tone: "warn", n: count("warn"), label: (n) => `${n} changed` },
    { tone: "stop", n: count("stop"), label: (n) => `${n} removed` },
    { tone: "info", n: count("info"), label: () => "Steps moved" },
  ];
  return lines.filter((l) => l.n > 0).map((l) => ({ tone: l.tone, label: l.label(l.n) }));
}

/**
 * One side of a change. A rule down the left marks the side, rather than two filled boxes
 * that made every row equally loud: the suggestion carries the brand rule and full ink, what
 * is there now stays muted. Four lines is enough to judge most changes; longer text opens
 * in full on request.
 */
export function Quote({
  tone,
  text,
  against,
}: {
  tone: "before" | "after";
  text: string;
  /** The other side of the change: the sentences this side adds or drops are marked. */
  against?: string;
}) {
  const after = tone === "after";
  return (
    <div
      className={`border-l-2 pl-3 text-meta ${
        after ? "border-brand text-ink" : "border-line text-ink-muted"
      }`}
    >
      <span className="block font-medium text-ink-muted">
        {after ? "Suggested" : "Now"}
      </span>
      <ExpandableText lines={4} moreLabel="Show all" textClassName="whitespace-pre-wrap">
        {against ? <Marked text={text} against={against} tone={tone} /> : text}
      </ExpandableText>
    </div>
  );
}

/**
 * A quote with the sentences that changed marked: on the suggestion, what is new (green
 * ground, underlined); on what is there now, what goes (red ground, struck through). The
 * line style and the words read out before each ("New:", "Removed:") carry the meaning
 * without the colour. Sentences both sides say alike stay plain, so a long step reads as
 * the one or two lines Pip actually changed.
 */
function Marked({ text, against, tone }: { text: string; against: string; tone: "before" | "after" }) {
  const after = tone === "after";
  const segments = changedSegments(text, against);
  // Every sentence changed: the whole quote is new, and marking all of it says nothing more.
  if (segments.every((s) => s.changed || spoken(s.text) === "")) return <>{text}</>;
  return (
    <>
      {segments.map((segment, i) => (
        <Fragment key={i}>
          {segment.changed ? (
            <mark className={after ? MARK_NEW : MARK_GONE}>
              <span className="sr-only">{after ? "New: " : "Removed: "}</span>
              {segment.text}
            </mark>
          ) : (
            segment.text
          )}
          {segment.gap}
        </Fragment>
      ))}
    </>
  );
}

const MARK_BASE = "rounded-sm px-0.5 text-ink decoration-1 underline-offset-2 [box-decoration-break:clone]";
const MARK_NEW = `${MARK_BASE} bg-success-soft underline decoration-success dark:bg-success/25`;
const MARK_GONE = `${MARK_BASE} bg-danger-soft line-through decoration-danger dark:bg-danger/25`;
