"use client";

import { Plus, Sparkles, TriangleAlert, X } from "lucide-react";
import { useState } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { ActionButton } from "@/components/arc/feedback";
import { FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON } from "@/components/ui";
import type { StepExamples } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import type { Issue } from "./scriptModel";
import {
  EXAMPLE_LINE_MAX,
  MOMENT_LABEL,
  MOMENT_PLACEHOLDER,
  TURNS_MAX,
  TURNS_MIN,
  addTurn,
  exampleField,
  examplesIn,
  isBlank,
  momentsFor,
  removeTurn,
  setTurn,
  startExamples,
  warningsAt,
  withExamples,
  type Examples,
  type LineWarning,
  type Moment,
} from "./stepExamples";

/** "Let Pip write examples": the step's own Pip ask, and why it waits when it cannot run. */
export interface ExamplesAsk {
  run: () => void;
  /** Why it cannot be pressed now (unsaved changes, Pip already writing, no permission). */
  wait?: string | null;
  pending?: boolean;
}

/**
 * ONE STEP'S EXAMPLES IN ONE LANGUAGE, edited where the step is edited: the campaign's
 * scenario editor and a Pip draft's review. The language is chosen by the caller (it shares
 * the script box's switch), so this shows one language at a time.
 *
 * A step with no examples in this language shows its old example line read-only, if it has
 * one, and two ways to start: Pip writes them for review, or the owner writes them, starting
 * from that old line. A check's warning sits under the line it is about, in one short line,
 * with the detail behind "Why?".
 */
export function StepExamplesEditor({
  idBase,
  stageId,
  examples,
  tag,
  languageLabel,
  first,
  legacy,
  showLegacy = true,
  readOnly = false,
  issues,
  warnings = [],
  maxLength = EXAMPLE_LINE_MAX,
  pip,
  onChange,
}: {
  idBase: string;
  stageId: string;
  examples: Record<string, StepExamples> | undefined;
  tag: string;
  languageLabel: string;
  /** The call's first step, which also has "If they're busy". */
  first: boolean;
  /** The step's old single example line (`sounds_like`). */
  legacy: string;
  /** False where the old line is already shown in an editable box beside this one. */
  showLegacy?: boolean;
  readOnly?: boolean;
  /** The step's problems from `validate`; the ones on examples are shown on their lines. */
  issues: Issue[];
  warnings?: readonly LineWarning[];
  maxLength?: number;
  pip?: ExamplesAsk;
  onChange: (next: Record<string, StepExamples>) => void;
}) {
  const held = examplesIn(examples, tag);
  const id = (part: string) => `${idBase}-ex-${tag}-${part}`;
  const on = (field: string) => issues.filter((i) => i.field === field);
  const set = (next: Examples) => onChange(withExamples(examples, tag, next));
  const legacyShown = showLegacy && legacy.trim() !== "";

  if (!held) {
    return (
      <div className="space-y-2" data-testid="examples-empty">
        <p className={FIELD_LABEL}>Ways the agent says it</p>
        {legacyShown && (
          <div className="border-l-2 border-line pl-3">
            <p className="text-meta text-ink-muted">Old example line</p>
            <p className="text-meta text-ink [overflow-wrap:anywhere]">{legacy.trim()}</p>
          </div>
        )}
        <p className="text-meta text-ink-muted">No examples in {languageLabel} yet.</p>
        {!readOnly && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {pip && (
              <ActionButton
                variant="secondary-sm"
                status={pip.pending ? "pending" : "idle"}
                pendingLabel={`${ASSISTANT_NAME} is writing…`}
                disabled={Boolean(pip.wait)}
                title={pip.wait ?? undefined}
                aria-describedby={pip.wait ? id("pip-wait") : undefined}
                onClick={pip.run}
              >
                <Sparkles aria-hidden className="h-3.5 w-3.5" />
                Let {ASSISTANT_NAME} write examples
              </ActionButton>
            )}
            <button
              type="button"
              className={`${TEXT_ACTION} text-meta`}
              onClick={() => set(startExamples(legacy))}
            >
              Write them myself
            </button>
          </div>
        )}
        {pip?.wait && !readOnly && (
          <p id={id("pip-wait")} className="text-meta text-ink-muted">
            {pip.wait}
          </p>
        )}
      </div>
    );
  }

  const listProblems = on(exampleField.list(tag));
  const blockWarnings = warningsAt(warnings, stageId, tag, null);
  const written = held.turns.filter((t) => t.trim()).length;
  return (
    <div className="space-y-4" data-testid="examples">
      <fieldset className="min-w-0">
        <legend className="flex w-full flex-wrap items-baseline justify-between gap-x-2">
          <span className={FIELD_LABEL}>Ways the agent says it</span>
          <span className="text-meta tabular-nums text-ink-muted">
            {written} of {TURNS_MAX}
          </span>
        </legend>
        <span className={FIELD_HINT}>In {languageLabel}. Each one a little different.</span>
        <WarningLines warnings={blockWarnings} idBase={id("all")} />
        <ol className="mt-2 space-y-2">
          {held.turns.map((turn, i) => {
            const problems = on(exampleField.turn(tag, i));
            const lineWarnings = warningsAt(warnings, stageId, tag, { turn: i }, turn);
            return (
              <li key={i}>
                <div className="flex items-start gap-2">
                  <ExampleInput
                    id={id(`turn-${i}`)}
                    label={`Way ${i + 1}`}
                    value={turn}
                    maxLength={maxLength}
                    readOnly={readOnly}
                    problems={problems}
                    warnings={lineWarnings}
                    onChange={(v) => set(setTurn(held, i, v))}
                  />
                  {!readOnly && (
                    <button
                      type="button"
                      className={QUIET_ICON_BUTTON}
                      aria-label={`Remove way ${i + 1}`}
                      disabled={held.turns.length <= TURNS_MIN}
                      title={held.turns.length <= TURNS_MIN ? `Keep at least ${TURNS_MIN}.` : undefined}
                      onClick={() => set(removeTurn(held, i))}
                    >
                      <X aria-hidden className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {!readOnly &&
          (held.turns.length < TURNS_MAX ? (
            <button
              type="button"
              className={`${TEXT_ACTION} mt-1 text-meta`}
              onClick={() => set(addTurn(held))}
            >
              <Plus aria-hidden className="h-3.5 w-3.5" />
              Add another way
            </button>
          ) : (
            <p className="mt-1 text-meta text-ink-muted">{TURNS_MAX} is the most.</p>
          ))}
        {listProblems.length > 0 && (
          <p className="mt-1 text-meta text-danger">{listProblems.map((p) => p.message).join(" ")}</p>
        )}
      </fieldset>

      <div className="space-y-3">
        {momentsFor(first).map((moment) => (
          <MomentField
            key={moment}
            moment={moment}
            id={id(moment)}
            value={held[moment]}
            maxLength={maxLength}
            readOnly={readOnly}
            problems={on(exampleField.moment(tag, moment))}
            warnings={warningsAt(warnings, stageId, tag, { moment }, held[moment])}
            onChange={(v) => set({ ...held, [moment]: v })}
          />
        ))}
      </div>
    </div>
  );
}

function MomentField({
  moment,
  id,
  value,
  maxLength,
  readOnly,
  problems,
  warnings,
  onChange,
}: {
  moment: Moment;
  id: string;
  value: string;
  maxLength: number;
  readOnly: boolean;
  problems: Issue[];
  warnings: LineWarning[];
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className={FIELD_LABEL} htmlFor={id}>
        {MOMENT_LABEL[moment]}
      </label>
      <ExampleInput
        id={id}
        value={value}
        placeholder={MOMENT_PLACEHOLDER[moment]}
        maxLength={maxLength}
        readOnly={readOnly}
        problems={problems}
        warnings={warnings}
        onChange={onChange}
      />
    </div>
  );
}

function ExampleInput({
  id,
  label,
  value,
  placeholder,
  maxLength,
  readOnly,
  problems,
  warnings,
  onChange,
}: {
  id: string;
  /** For a screen reader, where no visible label names the box. */
  label?: string;
  value: string;
  placeholder?: string;
  maxLength: number;
  readOnly: boolean;
  problems: Issue[];
  warnings: LineWarning[];
  onChange: (value: string) => void;
}) {
  const described = [problems.length ? `${id}-err` : null, warnings.length ? `${id}-warn-0` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="min-w-0 flex-1">
      {/* Grows with its line where the browser can (`field-sizing`), so a long way is read whole. */}
      <textarea
        id={id}
        rows={1}
        className={`${FIELD} mt-0.5 field-sizing-content min-h-10 resize-none`}
        aria-label={label}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        readOnly={readOnly}
        aria-invalid={problems.length > 0 || undefined}
        aria-describedby={described || undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {problems.length > 0 && (
        <p id={`${id}-err`} className="mt-1 text-meta text-danger">
          {problems.map((p) => p.message).join(" ")}
        </p>
      )}
      <WarningLines warnings={warnings} idBase={`${id}-warn`} />
    </div>
  );
}

/** A check's warnings, one short line each; the detail opens behind "Why?". */
export function WarningLines({ warnings, idBase }: { warnings: readonly LineWarning[]; idBase: string }) {
  if (warnings.length === 0) return null;
  return (
    <ul className="mt-1 space-y-1" data-testid="line-warnings">
      {warnings.map((w, i) => (
        <WarningLine key={`${w.path}-${i}`} id={`${idBase}-${i}`} warning={w} />
      ))}
    </ul>
  );
}

function WarningLine({ id, warning }: { id: string; warning: LineWarning }) {
  const [open, setOpen] = useState(false);
  const detail = warning.detail?.trim();
  return (
    <li className="flex items-start gap-1.5 text-meta text-warn">
      <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0">
        <span id={id}>{warning.message}</span>
        {detail && (
          <>
            {" "}
            <button
              type="button"
              className="rounded-sm py-0.5 font-medium text-brand-strong underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:py-2 dark:text-brand-bright"
              aria-expanded={open}
              aria-controls={open ? `${id}-why` : undefined}
              onClick={() => setOpen((was) => !was)}
            >
              Why?
            </button>
          </>
        )}
        {detail && open && (
          <p id={`${id}-why`} className="mt-0.5 text-ink-muted [overflow-wrap:anywhere]">
            {detail}
          </p>
        )}
      </div>
    </li>
  );
}

/**
 * A step's examples as written, for reading on a review row: each language Pip wrote, its
 * ways and its moments, with any warning under its line.
 */
export function ExamplesReadout({
  stageId,
  examples,
  languages,
  first,
  warnings = [],
}: {
  stageId: string;
  examples: Record<string, StepExamples> | undefined;
  /** Each tag with its name, in the order to show them. */
  languages: { tag: string; name: string }[];
  first: boolean;
  warnings?: readonly LineWarning[];
}) {
  const shown = languages.flatMap(({ tag, name }) => {
    const ex = examplesIn(examples, tag);
    return ex !== null && !isBlank(ex) ? [{ tag, name, ex }] : [];
  });
  if (shown.length === 0) return null;
  return (
    <div className="space-y-2 border-l-2 border-brand pl-3" data-testid="examples-readout">
      {shown.map(({ tag, name, ex }) => {
        const turns = ex.turns.map((t, i) => ({ t, i })).filter(({ t }) => t.trim());
        return (
          <div key={tag} className="text-meta">
            <p className="font-medium text-ink-muted">Ways the agent says it{shown.length > 1 || languages.length > 1 ? ` · ${name}` : ""}</p>
            <ul className="mt-0.5 space-y-0.5">
              {turns.map(({ t, i }) => (
                <li key={i} className="text-ink [overflow-wrap:anywhere]">
                  {t}
                  <WarningLines warnings={warningsAt(warnings, stageId, tag, { turn: i }, t)} idBase={`${stageId}-${tag}-turn-${i}-w`} />
                </li>
              ))}
            </ul>
            {momentsFor(first)
              .filter((m) => ex[m].trim())
              .map((m) => (
                <div key={m} className="mt-1">
                  <span className="text-ink-muted">{MOMENT_LABEL[m]}: </span>
                  <span className="text-ink [overflow-wrap:anywhere]">{ex[m]}</span>
                  <WarningLines warnings={warningsAt(warnings, stageId, tag, { moment: m }, ex[m])} idBase={`${stageId}-${tag}-${m}-w`} />
                </div>
              ))}
          </div>
        );
      })}
    </div>
  );
}
