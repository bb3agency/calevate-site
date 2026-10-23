"use client";

/**
 * THE structured script editor (founder, 24 Oct 2026): the script as named section blocks,
 * `{{variable}}` fields inserted from a list, a character budget per section and for the
 * whole script, and a "how it will sound" preview. What it hands back is plain text only.
 *
 * ## Plain text, enforced at the edge
 *
 * Every keystroke and every paste goes through `toSpokenPlainText`, so markdown, list
 * markers, HTML and emoji never enter the value — a client pasting a formatted document
 * from a word processor gets the words and nothing that would be read aloud as "asterisk"
 * on a call. The edited text box shows the result at once, so nothing is removed silently
 * behind the person's back; a one-line note says what was taken out.
 *
 * ## Variables are text, shown as fields
 *
 * The value keeps `{{key}}` tokens (what the server fills, `ScriptBuilder.insertVariable`).
 * Under each box the fields the section uses are listed by their human label, and a token
 * that matches no known field is flagged with what to do, because an unknown field is
 * spoken as nothing. Rich-text "chips" inside the box were rejected: a contenteditable chip
 * editor is the one way to get an atomic token, and it breaks Telugu input methods, undo
 * and paste on Android keyboards, which is where this is used.
 *
 * ## The budget
 *
 * Counted in code points (Python's `len`, so it agrees with the server). Near the limit
 * the meter turns amber; over it, the section is marked invalid and says by how much. It
 * does not cut the text off: a paste that runs over keeps everything so the person can
 * choose what to remove, and the caller holds the save while `overBudget` is true.
 */

import { useId, useRef, useState, type ReactNode } from "react";
import { Plus, TriangleAlert } from "lucide-react";
import clsx from "clsx";

import { formatCount } from "@/components/ui";

import { ActionButton, type FeedbackStatus } from "./feedback";
import { codePoints, fillVariables, toSpokenPlainText, variablesIn } from "./spoken-text";

export type ScriptVariableOption = {
  key: string;
  /** What the client calls it: "Caller's name". */
  label: string;
  /** What the preview says in its place: "Priya". */
  sample?: string;
};

export type ScriptEditorSection = {
  id: string;
  title: string;
  /** One line under the title: what goes here. */
  hint?: string;
  value: string;
  maxChars?: number;
  placeholder?: string;
  /** Rows of the text box. */
  rows?: number;
};

export type ScriptEditorStrings = {
  insertLabel: string;
  usesLabel: string;
  unknownVariable: (token: string) => string;
  cleaned: string;
  over: (n: string) => string;
  left: (n: string) => string;
  totalLabel: string;
  previewTitle: string;
  previewEmpty: string;
  save: string;
  saved: string;
  saving: string;
};

const DEFAULT_STRINGS: ScriptEditorStrings = {
  insertLabel: "Add a caller detail",
  usesLabel: "Uses",
  unknownVariable: (token) => `${token} is not a detail this agent knows, so the agent would say nothing there. Pick one from the list.`,
  cleaned: "Formatting was removed: the agent speaks plain words only.",
  over: (n) => `${n} ${n === "1" ? "character" : "characters"} over`,
  left: (n) => `${n} left`,
  totalLabel: "Whole script",
  previewTitle: "How it will sound",
  previewEmpty: "Write a section to hear how it reads.",
  save: "Save script",
  saved: "Saved",
  saving: "Saving",
};

/** Share of the budget at which the meter warns. */
const WARN_AT = 0.9;

function Meter({
  used,
  max,
  label,
  strings,
  id,
}: {
  used: number;
  max: number;
  label: string;
  strings: ScriptEditorStrings;
  id?: string;
}) {
  const over = used > max;
  const near = !over && used >= max * WARN_AT;
  const share = Math.min(1, max === 0 ? 1 : used / max);
  return (
    <div id={id} className="flex items-center gap-2">
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(used, max)}
        aria-valuetext={over ? strings.over(formatCount(used - max)) : strings.left(formatCount(max - used))}
        className="h-1 w-20 overflow-hidden rounded-full bg-ink/[0.07]"
      >
        <div
          className={clsx(
            "h-full origin-left rounded-full motion-safe:transition-transform motion-safe:duration-(--duration-fast)",
            over ? "bg-danger" : near ? "bg-chart-warn" : "bg-brand",
          )}
          style={{ transform: `scaleX(${share})` }}
        />
      </div>
      <span
        className={clsx(
          "text-meta tabular-nums",
          over ? "font-medium text-danger" : near ? "text-warn" : "text-ink-faint",
        )}
      >
        {over ? strings.over(formatCount(used - max)) : strings.left(formatCount(max - used))}
      </span>
    </div>
  );
}

function SectionBlock({
  section,
  variables,
  strings,
  onChange,
  index,
}: {
  section: ScriptEditorSection;
  variables: ScriptVariableOption[];
  strings: ScriptEditorStrings;
  onChange: (id: string, value: string) => void;
  index: number;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [cleaned, setCleaned] = useState(false);
  const base = useId();
  const hintId = `${base}-hint`;
  const meterId = `${base}-meter`;
  const fieldsId = `${base}-fields`;
  const used = codePoints(section.value);
  const over = section.maxChars !== undefined && used > section.maxChars;
  const known = new Map(variables.map((v) => [v.key, v]));
  const keys = variablesIn(section.value);
  const unknown = keys.filter((key) => !known.has(key));

  const commit = (raw: string) => {
    const plain = toSpokenPlainText(raw);
    setCleaned(plain !== raw);
    onChange(section.id, plain);
  };

  const insert = (key: string) => {
    const el = box.current;
    const token = `{{${key}}}`;
    const start = el?.selectionStart ?? section.value.length;
    const end = el?.selectionEnd ?? section.value.length;
    onChange(section.id, section.value.slice(0, start) + token + section.value.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  return (
    <li className="space-y-2 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <label htmlFor={`${base}-box`} className="text-body font-semibold text-ink">
          <span aria-hidden className="mr-2 tabular-nums text-ink-faint">
            {index + 1}
          </span>
          {section.title}
        </label>
        {section.maxChars !== undefined ? (
          <Meter used={used} max={section.maxChars} label={`${section.title} length`} strings={strings} id={meterId} />
        ) : null}
      </div>
      {section.hint ? (
        <p id={hintId} className="text-meta text-ink-muted">
          {section.hint}
        </p>
      ) : null}
      <textarea
        ref={box}
        id={`${base}-box`}
        value={section.value}
        rows={section.rows ?? 3}
        placeholder={section.placeholder}
        aria-invalid={over || unknown.length > 0 || undefined}
        aria-describedby={clsx(section.hint && hintId, section.maxChars !== undefined && meterId, keys.length > 0 && fieldsId) || undefined}
        onChange={(event) => commit(event.target.value)}
        className="w-full resize-y rounded-md border border-line bg-surface px-3 py-2 text-transcript text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/25 aria-[invalid=true]:border-danger"
      />
      {variables.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`${strings.insertLabel}: ${section.title}`}>
          <span className="text-meta text-ink-muted">{strings.insertLabel}</span>
          {variables.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => insert(v.key)}
              className="press inline-flex min-h-7 items-center gap-1 rounded-full border border-line px-2.5 text-meta text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
            >
              <Plus aria-hidden className="h-3 w-3" />
              {v.label}
            </button>
          ))}
        </div>
      ) : null}
      {keys.length > 0 ? (
        <div id={fieldsId} className="space-y-1">
          <p className="flex flex-wrap items-center gap-1.5 text-meta text-ink-muted">
            {strings.usesLabel}
            {keys.map((key) => {
              const v = known.get(key);
              return (
                <span
                  key={key}
                  className={clsx(
                    "inline-flex items-center rounded-full px-2 py-0.5 text-meta font-medium",
                    v ? "bg-brand-soft text-brand-strong" : "bg-danger-soft text-danger",
                  )}
                >
                  {v ? v.label : `{{${key}}}`}
                </span>
              );
            })}
          </p>
          {unknown.map((key) => (
            <p key={key} className="flex items-start gap-1.5 text-meta text-danger">
              <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {strings.unknownVariable(`{{${key}}}`)}
            </p>
          ))}
        </div>
      ) : null}
      {cleaned ? (
        <p role="status" className="text-meta text-ink-muted">
          {strings.cleaned}
        </p>
      ) : null}
    </li>
  );
}

export type ScriptEditorProps = {
  sections: ScriptEditorSection[];
  /** Receives plain text only: markdown, list markers, HTML and emoji are already removed. */
  onChange: (id: string, value: string) => void;
  variables?: ScriptVariableOption[];
  /** Budget for all sections together. */
  totalMaxChars?: number;
  /** The listen control (the caller's voice preview button) shown in the preview panel. */
  previewAction?: ReactNode;
  /** Turns off the preview panel, for a screen that shows its own. */
  showPreview?: boolean;
  /** With `onSave`, the editor shows its own save button carrying the action's state. */
  onSave?: () => void;
  status?: FeedbackStatus;
  /** Holds the save (e.g. a section over budget or an unknown field); the reason is shown. */
  saveBlockedReason?: string | null;
  strings?: Partial<ScriptEditorStrings>;
  className?: string;
};

/** True when any section, or the whole script, is over its budget. */
export function scriptOverBudget(sections: ScriptEditorSection[], totalMaxChars?: number): boolean {
  const total = sections.reduce((sum, s) => sum + codePoints(s.value), 0);
  return (
    sections.some((s) => s.maxChars !== undefined && codePoints(s.value) > s.maxChars) ||
    (totalMaxChars !== undefined && total > totalMaxChars)
  );
}

/** Variable keys used anywhere that match no known field. */
export function unknownVariables(sections: ScriptEditorSection[], variables: ScriptVariableOption[]): string[] {
  const known = new Set(variables.map((v) => v.key));
  return [...new Set(sections.flatMap((s) => variablesIn(s.value)))].filter((k) => !known.has(k));
}

export function ScriptEditor({
  sections,
  onChange,
  variables = [],
  totalMaxChars,
  previewAction,
  showPreview = true,
  onSave,
  status = "idle",
  saveBlockedReason = null,
  strings: overrides,
  className,
}: ScriptEditorProps) {
  const strings = { ...DEFAULT_STRINGS, ...overrides };
  const total = sections.reduce((sum, s) => sum + codePoints(s.value), 0);
  const samples = Object.fromEntries(variables.filter((v) => v.sample).map((v) => [v.key, v.sample as string]));
  const spoken = sections
    .map((s) => s.value.trim())
    .filter(Boolean)
    .map((text) => fillVariables(text, samples));

  return (
    <div className={clsx("grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]", className)}>
      <div className="min-w-0 space-y-4">
        <ol className="space-y-4">
          {sections.map((section, index) => (
            <SectionBlock
              key={section.id}
              section={section}
              index={index}
              variables={variables}
              strings={strings}
              onChange={onChange}
            />
          ))}
        </ol>
        {totalMaxChars !== undefined || onSave ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
            {totalMaxChars !== undefined ? (
              <div className="flex items-center gap-2">
                <span className="text-meta font-medium text-ink">{strings.totalLabel}</span>
                <Meter used={total} max={totalMaxChars} label={strings.totalLabel} strings={strings} />
              </div>
            ) : (
              <span />
            )}
            {onSave ? (
              <div className="flex flex-wrap items-center gap-3">
                {saveBlockedReason ? <p className="text-meta text-ink-muted">{saveBlockedReason}</p> : null}
                <ActionButton
                  status={status}
                  disabled={Boolean(saveBlockedReason)}
                  successLabel={strings.saved}
                  pendingLabel={strings.saving}
                  onClick={onSave}
                >
                  {strings.save}
                </ActionButton>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {showPreview ? (
        <aside aria-label={strings.previewTitle} className="h-fit space-y-3 rounded-card border border-line bg-surface-muted p-4 lg:sticky lg:top-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-body font-semibold text-ink">{strings.previewTitle}</h3>
            {previewAction}
          </div>
          {spoken.length > 0 ? (
            <div className="space-y-2 text-transcript text-ink">
              {spoken.map((line, i) => (
                <p key={i} className="whitespace-pre-wrap break-words">
                  {line}
                </p>
              ))}
            </div>
          ) : (
            <p className="text-meta text-ink-muted">{strings.previewEmpty}</p>
          )}
        </aside>
      ) : null}
    </div>
  );
}
