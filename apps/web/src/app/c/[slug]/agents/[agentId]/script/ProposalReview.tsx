"use client";

/**
 * AN AI PROPOSAL, REVIEWED BEFORE IT TOUCHES ANYTHING.
 *
 * Every change is its own row with its own "Keep" box, all kept to start with; the owner
 * unticks what they do not want and only the rest is applied to their draft (`applyChanges`).
 * Nothing goes live from here: the draft still waits for "Put it live".
 *
 * Each suggestion can be reworded before it is kept (D-831): "Edit" opens the row's fields,
 * an edit ticks the row, and "Reset to suggestion" puts Pip's words back. The edited values
 * go through the same `applyChanges` and the builder's own `validate`, so a kept change can
 * never be one the builder would refuse; a problem is shown on the row that caused it and
 * holds "Add" until it is fixed.
 *
 * `base` is the script the proposal was made from, when that is not the working copy (a
 * suggestion Pip wrote earlier, D-820): the changes are listed against it, so an edit the
 * owner made since is never offered back, and the kept ones are applied to `current`.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";

import { ExpandableText } from "@/components/arc/expandable-text";
import { TEXT_ACTION } from "@/components/console/section";
import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";

import { PartEditor, SectionFields, partShows, sectionShows, unshownIssues } from "./ProposalEditors";
import { applyTraced, diffScripts, partText, type Change, type PartKey } from "./scriptDiff";
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
  { test: /^example-\d+$/, part: "example_exchange" },
  { test: /^pronunciation-\d+$/, part: "style" },
];

/** The suggested section a row carries, by its id in the proposal. */
function suggestedId(change: Change): string | null {
  return change.kind === "section-added" || change.kind === "section-changed" ? change.after.id : null;
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
  gate,
  limits = DEFAULT_LIMITS,
  language = "your callers' language",
  children,
}: {
  current: CallScript;
  /** What the proposal was made from, when that is not `current`. */
  base?: CallScript;
  proposal: CallScript;
  onApply: (next: CallScript) => void;
  onDiscard: () => void;
  /** A reason "Keep" must wait (the owner has not confirmed the unplaced lines yet). */
  gate?: string | null;
  /** The builder's limits, so an edited suggestion is held to the same ones. */
  limits?: Limits;
  /** The call language in words, for the hints on lines the agent says. */
  language?: string;
  /** Shown above the changes: the server's account of how it was written, unplaced lines. */
  children?: ReactNode;
}) {
  const changes = useMemo(() => diffScripts(base ?? current, proposal), [base, current, proposal]);
  const [kept, setKept] = useState<Set<string>>(() => new Set(changes.map((c) => c.id)));
  // The proposal as the owner reworded it. The parent keys this component by proposal id,
  // so a new suggestion always starts from Pip's own words.
  const [edited, setEdited] = useState<CallScript>(proposal);
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [tried, setTried] = useState(false);
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

  const reset = (change: Change) => {
    if (change.kind === "part") {
      setEdited((e) => ({ ...e, [change.part]: proposal[change.part] }));
    } else {
      const id = suggestedId(change);
      const original = sectionsOf(proposal).find((s) => s.id === id);
      setEdited((e) => ({ ...e, stages: sectionsOf(e).map((s) => (s.id === id && original ? original : s)) }));
    }
    setIn(setTouched, change.id, false);
  };

  const add = () => {
    if (blocked.length > 0) {
      setTried(true);
      setOpen((o) => new Set([...o, ...blocked.map((c) => c.id)]));
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
          {changes.length === 1 ? "1 suggested change" : `${changes.length} suggested changes`}
        </h3>
        <p className="mt-1 text-meta text-ink-muted">
          Untick or edit any. Kept ones go to your draft, not live.
        </p>
      </div>
      {children}
      {changes.length === 0 ? (
        <p className="text-body text-ink-muted">Same as your script. Nothing to change.</p>
      ) : (
        <ul ref={list} className="divide-y divide-line border-y border-line">
          {changes.map((change) => {
            const on = kept.has(change.id);
            const rowIssues = issuesByRow.get(change.id) ?? [];
            const shownIssues = tried || touched.has(change.id) ? rowIssues : [];
            return (
              <Row
                key={change.id}
                change={change}
                kept={on}
                edited={touched.has(change.id)}
                open={open.has(change.id)}
                onKeep={(next) => setIn(setKept, change.id, next)}
                onOpen={(next) => setIn(setOpen, change.id, next)}
                onReset={() => reset(change)}
              >
                {change.kind === "part" ? (
                  <PartBody
                    change={change}
                    edited={edited}
                    open={open.has(change.id)}
                    issues={shownIssues}
                    language={language}
                    onChange={(next) => editRow(change, next)}
                  />
                ) : (
                  <SectionBody
                    change={change}
                    edited={edited}
                    open={open.has(change.id)}
                    issues={shownIssues}
                    limits={limits}
                    language={language}
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
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={keptCount === 0 || Boolean(gate)}
            title={gate ?? undefined}
            onClick={add}
          >
            {keptCount === changes.length
              ? changes.length === 1
                ? "Add it to my draft"
                : `Add all ${changes.length} to my draft`
              : `Add ${keptCount} of ${changes.length} to my draft`}
          </button>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDiscard}>
            Discard
          </button>
        </div>
        {gate && <p className="text-meta text-ink-muted">{gate}</p>}
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
  onKeep,
  onOpen,
  onReset,
  children,
}: {
  change: Change;
  kept: boolean;
  edited: boolean;
  open: boolean;
  onKeep: (on: boolean) => void;
  onOpen: (on: boolean) => void;
  onReset: () => void;
  children: ReactNode;
}) {
  const id = domId(change);
  const editable = change.kind !== "section-removed";
  return (
    // An unticked change fades, so what will be applied is visible at a glance.
    <li className={`flex items-start gap-3 py-3 transition-opacity duration-150 ${kept ? "" : "opacity-55"}`}>
      <input
        id={`${id}-keep`}
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[var(--brand-strong)]"
        checked={kept}
        onChange={(e) => onKeep(e.target.checked)}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <label htmlFor={`${id}-keep`} className="cursor-pointer text-body font-medium text-ink">
            {headline(change)}
          </label>
          <span className="text-meta text-ink-muted">{kindLabel(change)}</span>
          {edited && <span className="text-meta font-medium text-brand-strong">Edited by you</span>}
        </div>
        {children}
        {editable && (
          <div className="mt-1.5 flex flex-wrap gap-x-4">
            <button
              type="button"
              className={`${TEXT_ACTION} text-meta`}
              aria-expanded={open}
              aria-controls={open ? `${id}-edit` : undefined}
              aria-label={`${open ? "Done editing" : "Edit"} ${headline(change)}`}
              onClick={() => onOpen(!open)}
            >
              {open ? "Done" : "Edit"}
            </button>
            {edited && (
              <button type="button" className={`${TEXT_ACTION} text-meta`} onClick={onReset}>
                Reset to suggestion
              </button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

/** The suggestion's fields under the brand rule, where its text was. */
function Editing({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div id={`${id}-edit`} className="border-l-2 border-brand pl-3">
      <p className="mb-1 text-meta font-medium text-ink-muted">Suggested</p>
      {children}
    </div>
  );
}

function PartBody({
  change,
  edited,
  open,
  issues,
  language,
  onChange,
}: {
  change: Extract<Change, { kind: "part" }>;
  edited: CallScript;
  open: boolean;
  issues: Issue[];
  language: string;
  onChange: (next: CallScript) => void;
}) {
  const id = domId(change);
  return (
    <div className="mt-1.5 space-y-1.5">
      {change.before && <Quote tone="before" text={change.before} />}
      {open ? (
        <Editing id={id}>
          <PartEditor part={change.part} script={edited} idBase={id} issues={issues} language={language} onChange={onChange} />
          <RowErrors issues={unshownIssues(issues, partShows)} />
        </Editing>
      ) : (
        <>
          <Quote tone="after" text={partText(edited, change.part) || "(left empty)"} />
          <RowErrors issues={issues} />
        </>
      )}
    </div>
  );
}

function SectionBody({
  change,
  edited,
  open,
  issues,
  limits,
  language,
  onChange,
}: {
  change: Exclude<Change, { kind: "part" }>;
  edited: CallScript;
  open: boolean;
  issues: Issue[];
  limits: Limits;
  language: string;
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
  return (
    <div className="mt-1.5 space-y-1.5">
      {before && <Quote tone="before" text={before} />}
      {open ? (
        <Editing id={id}>
          <SectionFields
            section={after}
            idBase={id}
            issues={issues}
            limits={limits}
            language={language}
            onChange={(patch) => onChange(after.id, patch)}
          />
          <RowErrors issues={unshownIssues(issues, sectionShows)} />
        </Editing>
      ) : (
        <>
          <Quote tone="after" text={suggested || "(left empty)"} />
          <RowErrors issues={issues} />
        </>
      )}
    </div>
  );
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
      return change.before ? "Changed" : "Added";
    case "section-added":
      return "New step";
    case "section-removed":
      return "Step removed";
    case "section-changed":
      return "Step changed";
  }
}

/**
 * One side of a change. A rule down the left marks the side, rather than two filled boxes
 * that made every row equally loud: the suggestion carries the brand rule and full ink, what
 * is there now stays muted. Four lines is enough to judge most changes; longer text opens
 * in full on request.
 */
export function Quote({ tone, text }: { tone: "before" | "after"; text: string }) {
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
        {text}
      </ExpandableText>
    </div>
  );
}
