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

import { Fragment, useMemo, useRef, useState, type ReactNode } from "react";

import { ExpandableText } from "@/components/arc/expandable-text";
import { TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM, type NoticeTone } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { PartEditor, SectionFields, partShows, sectionShows, unshownIssues } from "./ProposalEditors";
import {
  applyTraced,
  changedSegments,
  diffScripts,
  keptAtFirst,
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
  children,
}: {
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
  const changes = useMemo(() => diffScripts(base ?? current, proposal), [base, current, proposal]);
  // What the owner did to the draft since Pip wrote this: a change to a step they deleted
  // has nothing left to apply to, and one to a step or part they edited replaces their edit.
  const since = useMemo(() => sinceWritten(changes, base, current), [changes, base, current]);
  // A removal starts unticked: the owner keeps it only after looking at it (A-04).
  const [ticked, setKept] = useState<Set<string>>(() => keptAtFirst(changes));
  const kept = useMemo(() => new Set([...ticked].filter((id) => since.get(id) !== "deleted")), [ticked, since]);
  const offered = changes.filter((c) => since.get(c.id) !== "deleted").length;
  // The proposal as the owner reworded it. The parent keys this component by proposal id,
  // so a new suggestion always starts from Pip's own words.
  const [edited, setEdited] = useState<CallScript>(proposal);
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [tried, setTried] = useState(false);
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
        {changes.length > 1 && (
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
            const shownIssues = tried || touched.has(change.id) ? rowIssues : [];
            return (
              <Row
                key={change.id}
                change={change}
                kept={on}
                edited={touched.has(change.id)}
                open={open.has(change.id)}
                since={since.get(change.id)}
                onKeep={(next) => setIn(setKept, change.id, next)}
                onOpen={(next) => setIn(setOpen, change.id, next)}
                onReset={() => reset(change)}
              >
                {change.kind === "order" ? (
                  <OrderBody change={change} />
                ) : change.kind === "part" ? (
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
            disabled={keptCount === 0 || Boolean(gate) || pending !== null}
            title={gate ?? undefined}
            onClick={add}
          >
            {pending === "apply"
              ? "Adding…"
              : keptCount === offered && offered > 0
                ? offered === 1
                  ? "Add it to my draft"
                  : `Add all ${offered} to my draft`
                : `Add ${keptCount} of ${offered} to my draft`}
          </button>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDiscard} disabled={pending !== null}>
            {pending === "discard" ? "Discarding…" : "Discard"}
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
  since,
  onKeep,
  onOpen,
  onReset,
  children,
}: {
  change: Change;
  kept: boolean;
  edited: boolean;
  open: boolean;
  since?: Since;
  onKeep: (on: boolean) => void;
  onOpen: (on: boolean) => void;
  onReset: () => void;
  children: ReactNode;
}) {
  const id = domId(change);
  const gone = since === "deleted";
  const editable = !gone && change.kind !== "section-removed" && change.kind !== "order";
  return (
    // An unticked change fades, so what will be applied is visible at a glance.
    <li className={`flex items-start gap-3 py-3 transition-opacity duration-150 ${kept ? "" : "opacity-55"}`}>
      <input
        id={`${id}-keep`}
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[var(--brand-strong)]"
        checked={kept}
        disabled={gone}
        onChange={(e) => onKeep(e.target.checked)}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <label htmlFor={`${id}-keep`} className="cursor-pointer text-body font-medium text-ink">
            {headline(change)}
          </label>
          <StatusPill tone={kindTone(change)}>{kindLabel(change)}</StatusPill>
          {edited && <span className="text-meta font-medium text-brand-strong">Edited by you</span>}
        </div>
        {since && (
          <p className={`mt-1 text-meta ${gone ? "text-ink-muted" : "text-warn"}`}>{SINCE_NOTE[since](change)}</p>
        )}
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
  const suggested = partText(edited, change.part);
  return (
    <div className="mt-1.5 space-y-1.5">
      {change.before && <Quote tone="before" text={change.before} against={suggested || undefined} />}
      {open ? (
        <Editing id={id}>
          <PartEditor part={change.part} script={edited} idBase={id} issues={issues} language={language} onChange={onChange} />
          <RowErrors issues={unshownIssues(issues, partShows)} />
        </Editing>
      ) : (
        <>
          <Quote tone="after" text={suggested || "(left empty)"} against={change.before || undefined} />
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
  issues,
  limits,
  language,
  onChange,
}: {
  change: Exclude<Change, { kind: "part" } | { kind: "order" }>;
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
      {before && <Quote tone="before" text={before} against={suggested || undefined} />}
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
          <Quote tone="after" text={suggested || "(left empty)"} against={before || undefined} />
          <RowErrors issues={issues} />
        </>
      )}
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
