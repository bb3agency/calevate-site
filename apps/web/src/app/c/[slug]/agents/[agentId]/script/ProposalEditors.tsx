"use client";

/**
 * THE FIELDS OF ONE SUGGESTED CHANGE, OPENED FOR EDITING IN THE REVIEW (D-831).
 *
 * The owner reads Pip's suggestion and fixes the wording before keeping it, rather than
 * keeping it and then hunting for the same text in the builder. Each editor takes the value
 * and hands back the next one; `ProposalReview` owns the state and runs the builder's own
 * validation (`scriptModel.validate`) on the result, whose messages arrive here by field.
 *
 * The labels and limits are the builder's (`ScriptSections`, `SectionEditor`), so a field
 * reads the same in both places. Ids are prefixed with the row, because the builder's own
 * fields are on the same page.
 */

import { Trash2 } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON } from "@/components/ui";
import type { CallScript, CodeMix, ExampleLine, SpeakingStyle } from "@/lib/api/script";

import type { PartKey } from "./scriptDiff";
import type { Issue, Limits, Section } from "./scriptModel";

/** The issue fields an editor shows beside a control; any other issue is shown for the row. */
export function unshownIssues(issues: Issue[], shown: (field: string) => boolean): Issue[] {
  return issues.filter((issue) => !shown(issue.field));
}

const SECTION_FIELDS = /^(name|instruction|sounds_like|branch-\d+)$/;
const PART_FIELDS = /^(business_line|outbound_purpose|objection-\d+|example-\d+|pronunciation-\d+)$/;

export function sectionShows(field: string): boolean {
  return SECTION_FIELDS.test(field);
}

export function partShows(field: string): boolean {
  return PART_FIELDS.test(field);
}

/** Enough rows to show a suggestion whole without a scrollbar, up to a point. */
function rowsFor(text: string, min = 2): number {
  const lines = text.split("\n").reduce((n, line) => n + Math.max(1, Math.ceil(line.length / 72)), 0);
  return Math.min(10, Math.max(min, lines));
}

function Errors({ id, issues }: { id: string; issues: Issue[] }) {
  if (issues.length === 0) return null;
  return (
    <p id={id} className="mt-1 text-meta text-danger">
      {issues.map((i) => i.message).join(" ")}
    </p>
  );
}

function Text({
  id,
  label,
  labelHidden,
  hint,
  value,
  long,
  maxLength,
  issues = [],
  onChange,
}: {
  id: string;
  label: string;
  /** The row already names the part: the label is for a screen reader only. */
  labelHidden?: boolean;
  hint?: string;
  value: string;
  long?: boolean;
  maxLength?: number;
  issues?: Issue[];
  onChange: (value: string) => void;
}) {
  const invalid = issues.length > 0;
  const control = {
    id,
    className: FIELD,
    value,
    maxLength,
    "aria-invalid": invalid || undefined,
    "aria-describedby": invalid ? `${id}-err` : undefined,
  };
  return (
    <div>
      <label className={labelHidden ? "sr-only" : FIELD_LABEL} htmlFor={id}>
        {label}
      </label>
      {hint && <span className={FIELD_HINT}>{hint}</span>}
      {long ? (
        // Grows with its text where the browser can (`field-sizing`); elsewhere `rows` fits it.
        <textarea
          {...control}
          className={`${FIELD} field-sizing-content max-h-80 min-h-16`}
          rows={rowsFor(value)}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input {...control} onChange={(e) => onChange(e.target.value)} />
      )}
      <Errors id={`${id}-err`} issues={issues} />
    </div>
  );
}

function RemoveButton({ what, onClick }: { what: string; onClick: () => void }) {
  return (
    <button type="button" className={`${QUIET_ICON_BUTTON} mt-1`} aria-label={`Remove ${what}`} onClick={onClick}>
      <Trash2 aria-hidden className="h-3.5 w-3.5" />
    </button>
  );
}

const CODE_MIX: { value: CodeMix; label: string }[] = [
  { value: "light", label: "Mostly local" },
  { value: "natural", label: "Everyday mix" },
  { value: "heavy", label: "Lots of English" },
];

/** One part of the script (`scriptDiff`'s PARTS), as the builder edits it. */
export function PartEditor({
  part,
  script,
  idBase,
  issues,
  language,
  onChange,
}: {
  part: PartKey;
  script: CallScript;
  idBase: string;
  issues: Issue[];
  /** The call language's name, for the hints on lines the agent says. */
  language: string;
  onChange: (next: CallScript) => void;
}) {
  const on = (field: string) => issues.filter((i) => i.field === field);
  const id = (field: string) => `${idBase}-${field}`;
  const set = <K extends keyof CallScript>(key: K, value: CallScript[K]) => onChange({ ...script, [key]: value });

  switch (part) {
    case "business_line":
      return (
        <Text labelHidden id={id("business_line")} label="Your business in one line" hint="Up to 200 letters." maxLength={200}
          value={script.business_line} issues={on("business_line")} onChange={(v) => set("business_line", v)} />
      );
    case "outbound_purpose":
      return (
        <Text labelHidden id={id("outbound_purpose")} label="Why you are calling" hint="In plain English. Up to 300 letters."
          maxLength={300} value={script.outbound_purpose} issues={on("outbound_purpose")}
          onChange={(v) => set("outbound_purpose", v)} />
      );
    case "identity":
      return <Text labelHidden id={id("identity")} label="Its role" hint="In plain English." long value={script.identity} onChange={(v) => set("identity", v)} />;
    case "goal":
      return <Text labelHidden id={id("goal")} label="The goal" hint="In plain English." long value={script.goal} onChange={(v) => set("goal", v)} />;
    case "ending":
      return <Text labelHidden id={id("ending")} label="How it ends the call" hint="In plain English." long value={script.ending} onChange={(v) => set("ending", v)} />;
    case "opening_line":
      return (
        <Text labelHidden id={id("opening_line")} label="Opening line" hint={`In ${language}, as callers should hear it.`} long
          maxLength={1000} value={script.opening_line} onChange={(v) => set("opening_line", v)} />
      );
    case "style":
      return <StyleEditor style={script.style} idBase={idBase} issues={issues} onChange={(s) => set("style", s)} />;
    case "objections":
      return (
        <div className="space-y-3">
          {script.objections.map((o, i) => (
            <div key={i} className="flex items-start gap-2">
              <div className="min-w-0 flex-1 space-y-2">
                <Text id={id(`objection-${i}-said`)} label={`Push-back ${i + 1}: what they say`} maxLength={300}
                  value={o.objection}
                  onChange={(v) => set("objections", script.objections.map((x, j) => (j === i ? { ...x, objection: v } : x)))} />
                <Text id={id(`objection-${i}`)} label="How to answer" hint="In plain English." long maxLength={1000}
                  value={o.response} issues={on(`objection-${i}`)}
                  onChange={(v) => set("objections", script.objections.map((x, j) => (j === i ? { ...x, response: v } : x)))} />
              </div>
              <RemoveButton what={`push-back ${i + 1}`}
                onClick={() => set("objections", script.objections.filter((_, j) => j !== i))} />
            </div>
          ))}
        </div>
      );
    case "example_exchange":
      return (
        <ExampleEditor lines={script.example_exchange} idBase={idBase} issues={issues}
          onChange={(lines) => set("example_exchange", lines)} />
      );
    case "adherence":
      return (
        <fieldset>
          <legend className={FIELD_LABEL}>How closely it follows the steps</legend>
          <div className="mt-1 flex flex-wrap gap-x-4">
            {(["flexible", "strict"] as const).map((value) => (
              <label key={value} className="flex cursor-pointer items-center gap-2 text-body text-ink touch:min-h-11">
                <input type="radio" name={id("adherence")} checked={(script.adherence ?? "flexible") === value}
                  onChange={() => set("adherence", value)} />
                {value === "strict" ? "Follow the steps closely" : "Use the steps as a guide"}
              </label>
            ))}
          </div>
        </fieldset>
      );
  }
}

function StyleEditor({
  style,
  idBase,
  issues,
  onChange,
}: {
  style: SpeakingStyle;
  idBase: string;
  issues: Issue[];
  onChange: (style: SpeakingStyle) => void;
}) {
  const patch = (next: Partial<SpeakingStyle>) => onChange({ ...style, ...next });
  const id = (field: string) => `${idBase}-${field}`;
  return (
    <div className="space-y-3">
      <Text id={id("tone")} label="Tone" hint="In plain English." maxLength={300} value={style.tone} onChange={(v) => patch({ tone: v })} />
      <Text id={id("address")} label="How it addresses callers" hint="In plain English." maxLength={200}
        value={style.address_form} onChange={(v) => patch({ address_form: v })} />
      <fieldset>
        <legend className={FIELD_LABEL}>English words in its speech</legend>
        <div className="mt-1 flex flex-wrap gap-x-4">
          {CODE_MIX.map((option) => (
            <label key={option.value} className="flex cursor-pointer items-center gap-2 text-body text-ink touch:min-h-11">
              <input type="radio" name={id("code-mix")} checked={style.code_mix === option.value}
                onChange={() => patch({ code_mix: option.value })} />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <Text id={id("phrases")} label="Phrases it can use" hint="One per line, in your callers' language." long
        value={style.sample_phrases.join("\n")} onChange={(v) => patch({ sample_phrases: v.split("\n") })} />
      {style.pronunciations.map((p, i) => {
        const problems = issues.filter((issue) => issue.field === `pronunciation-${i}`);
        const words = (next: Partial<typeof p>) =>
          patch({ pronunciations: style.pronunciations.map((w, j) => (j === i ? { ...w, ...next } : w)) });
        return (
          <div key={i}>
            <div className="flex items-start gap-2">
              <div className="grid grid-cols-1 min-w-0 flex-1 gap-2 sm:grid-cols-2">
                <Text id={id(`word-${i}`)} label={`Name ${i + 1}`} maxLength={80} value={p.word} onChange={(v) => words({ word: v })} />
                <Text id={id(`say-${i}`)} label="Say it as" maxLength={120} value={p.say_as} onChange={(v) => words({ say_as: v })} />
              </div>
              <RemoveButton what={`name ${i + 1}`}
                onClick={() => patch({ pronunciations: style.pronunciations.filter((_, j) => j !== i) })} />
            </div>
            <Errors id={id(`pronunciation-${i}-err`)} issues={problems} />
          </div>
        );
      })}
    </div>
  );
}

function ExampleEditor({
  lines,
  idBase,
  issues,
  onChange,
}: {
  lines: ExampleLine[];
  idBase: string;
  issues: Issue[];
  onChange: (lines: ExampleLine[]) => void;
}) {
  return (
    <ul className="space-y-2">
      {lines.map((line, i) => {
        const problems = issues.filter((issue) => issue.field === `example-${i}`);
        const lineId = `${idBase}-example-${i}`;
        return (
          <li key={i}>
            <div className="flex items-start gap-2">
              <select
                className={`${FIELD} mt-0 w-24 shrink-0`}
                aria-label={`Line ${i + 1}: who speaks`}
                value={line.speaker}
                onChange={(e) =>
                  onChange(lines.map((l, j) => (j === i ? { ...l, speaker: e.target.value as ExampleLine["speaker"] } : l)))
                }
              >
                <option value="caller">Caller</option>
                <option value="agent">Agent</option>
              </select>
              <input
                id={lineId}
                className={`${FIELD} mt-0 min-w-0`}
                aria-label={`Line ${i + 1}`}
                value={line.text}
                maxLength={500}
                aria-invalid={problems.length > 0 || undefined}
                aria-describedby={problems.length ? `${lineId}-err` : undefined}
                onChange={(e) => onChange(lines.map((l, j) => (j === i ? { ...l, text: e.target.value } : l)))}
              />
              <RemoveButton what={`line ${i + 1}`} onClick={() => onChange(lines.filter((_, j) => j !== i))} />
            </div>
            <Errors id={`${lineId}-err`} issues={problems} />
          </li>
        );
      })}
    </ul>
  );
}

/** A suggested step: the fields the builder's step editor opens with. */
export function SectionFields({
  section,
  idBase,
  issues,
  limits,
  language,
  onChange,
}: {
  section: Section;
  idBase: string;
  issues: Issue[];
  limits: Limits;
  language: string;
  onChange: (patch: Partial<Section>) => void;
}) {
  const on = (field: string) => issues.filter((i) => i.field === field);
  const id = (field: string) => `${idBase}-${field}`;
  const say = section.mode === "say";
  return (
    <div className="space-y-3">
      <Text id={id("name")} label="Step name" maxLength={limits.nameMax} value={section.name} issues={on("name")}
        onChange={(v) => onChange({ name: v })} />
      <Text id={id("instruction")} label={say ? "The exact words to say" : "What it does here"}
        hint={say ? `In ${language}, as callers should hear it.` : "In plain English. One or two sentences is plenty."}
        long value={section.instruction} issues={on("instruction")} onChange={(v) => onChange({ instruction: v })} />
      <Text id={id("sounds_like")} label="Example line" hint={`How this step sounds on the phone, in ${language}.`}
        maxLength={limits.soundsLikeMax} value={section.sounds_like} issues={on("sounds_like")}
        onChange={(v) => onChange({ sounds_like: v })} />
      {section.branches.map((branch, j) => (
        <Text key={j} id={id(`branch-${j}`)} label={`Way out ${j + 1}: when`} hint="In plain English." maxLength={300}
          value={branch.when} issues={on(`branch-${j}`)}
          onChange={(v) => onChange({ branches: section.branches.map((b, k) => (k === j ? { ...b, when: v } : b)) })} />
      ))}
    </div>
  );
}
