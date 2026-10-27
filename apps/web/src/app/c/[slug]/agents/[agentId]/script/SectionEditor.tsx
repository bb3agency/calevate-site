"use client";

import { useId, useState } from "react";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";

import { Disclosure, FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON, formatCount } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import type { ScriptContext } from "@/lib/api/script";
import { sameLanguage, useBusinessSuggestions } from "@/lib/useVerticalExamples";

import { chars, issuesFor, sectionDetail, type Issue, type Limits, type Section } from "./scriptModel";
import { CleanedNote, usePlainText } from "./plainText";
import { languageName, targetOptions, thenLabel } from "./sectionParts";
import { SmallSteps } from "./SmallSteps";

/**
 * ONE STEP, EDITED — in place under its card in the list, or beside the flow picture on a
 * wide screen (a sheet on a narrower one). The same component in every place, writing
 * through the same `onChange`, which is what keeps the views one script.
 *
 * WHAT IS ON SHOW AND WHAT IS FOLDED (D-825). The three things every step has are in view:
 * its name, what the agent does there (or the exact words), and an example line in the
 * callers' language. The options most steps never need (exact words, where the call goes
 * next, details to find out, small steps (D-908), moving and deleting) are under "More
 * options". Its closed row
 * says what they are set to, and it opens by itself when one of them needs fixing, so
 * nothing set or wrong is hidden. The letters count appears only near the limit.
 */
export function SectionEditor({
  section,
  index,
  sections,
  context,
  limits,
  issues,
  readOnly,
  onChange,
  onMove,
  onDelete,
}: {
  section: Section;
  index: number;
  sections: Section[];
  context: ScriptContext | null;
  limits: Limits;
  issues: Issue[];
  readOnly: boolean;
  onChange: (patch: Partial<Section>) => void;
  onMove: (to: number) => void;
  onDelete: () => void;
}) {
  const uid = useId();
  const plain = usePlainText();
  const field = (name: string) => `${uid}-${name}`;
  const errors = (name: string) => issuesFor(issues, section.id, name);
  const used = chars(sectionDetail(section));
  const over = used > limits.detailMax;
  const nearLimit = used >= limits.detailMax * LETTERS_SHOWN_FROM;
  const language = languageName(context?.language);
  // The account's own suggestions (D-827): a step name and example line for this position,
  // shown only where the field is empty, and the line only when it is in the script's language.
  const ideas = useBusinessSuggestions();
  const idea = ideas.steps[index];
  const ideaLine = idea && sameLanguage(ideas.language, context?.language) ? idea.example_line : null;
  const options = targetOptions(sections, section.id, context);
  const say = section.mode === "say";
  const routeErrors =
    section.branches.some((_, i) => errors(`branch-${i}`).length > 0) || errors("otherwise").length > 0;
  const stepIssues = issuesFor(issues, section.id).filter((i) => i.field.startsWith("procedure"));
  const counted = section.procedure.length > 0 ? "counting the example line and the small steps note" : "counting the example line";

  const setBranch = (i: number, patch: Partial<Section["branches"][number]>) =>
    onChange({ branches: section.branches.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

  const describedBy = [nearLimit ? field("count") : null, errors("instruction").length ? field("instruction-err") : null]
    .filter(Boolean)
    .join(" ");

  return (
    <fieldset disabled={readOnly} className="min-w-0 space-y-5">
      <legend className="sr-only">Step {index + 1}</legend>
      <div>
        <label className={FIELD_LABEL} htmlFor={field("name")}>
          Step name
        </label>
        <input
          id={field("name")}
          className={FIELD}
          value={section.name}
          maxLength={limits.nameMax}
          placeholder={`For example: ${idea?.name ?? "Find out what they need"}`}
          aria-invalid={errors("name").length > 0 || undefined}
          aria-describedby={errors("name").length ? field("name-err") : undefined}
          onChange={(e) => onChange({ name: e.target.value })}
        />
        <FieldErrors id={field("name-err")} issues={errors("name")} />
      </div>

      <div>
        <label className={FIELD_LABEL} htmlFor={field("instruction")}>
          {say ? "The exact words to say" : "What it does here"}
        </label>
        <span className={FIELD_HINT}>
          {say ? `In ${language}, as callers should hear it.` : "In plain English. One or two sentences is plenty."}
        </span>
        <textarea
          id={field("instruction")}
          className={FIELD}
          rows={3}
          value={section.instruction}
          placeholder={
            say ? "For example: Mee peru cheppagalara?" : "For example: Ask what they are looking for and when they need it."
          }
          aria-invalid={errors("instruction").length > 0 || undefined}
          aria-describedby={describedBy || undefined}
          onChange={(e) => onChange({ instruction: plain.take(e.target.value) })}
        />
        {nearLimit && (
          <p id={field("count")} className={`mt-1 text-meta tabular-nums ${over ? "text-danger" : "text-ink-muted"}`}>
            {over
              ? `${formatCount(used - limits.detailMax)} letters over, ${counted}.`
              : `${formatCount(limits.detailMax - used)} letters left, ${counted}.`}
          </p>
        )}
        <FieldErrors id={field("instruction-err")} issues={errors("instruction").filter((i) => !i.message.includes("too long"))} />
      </div>

      <div>
        <label className={FIELD_LABEL} htmlFor={field("sounds")}>
          Example line
        </label>
        <span className={FIELD_HINT}>How this step sounds on the phone, in {language}.</span>
        <input
          id={field("sounds")}
          className={FIELD}
          value={section.sounds_like}
          maxLength={limits.soundsLikeMax}
          placeholder={ideaLine ? `For example: ${ideaLine}` : undefined}
          aria-invalid={errors("sounds_like").length > 0 || undefined}
          aria-describedby={errors("sounds_like").length ? field("sounds-err") : undefined}
          onChange={(e) => onChange({ sounds_like: plain.take(e.target.value) })}
        />
        <FieldErrors id={field("sounds-err")} issues={errors("sounds_like")} />
        <CleanedNote shown={plain.cleaned} />
      </div>

      <Disclosure
        variant="inline"
        headingLevel={4}
        title="More options"
        subtitle={optionsLine(section, sections, index, context)}
        defaultOpen={routeErrors || stepIssues.length > 0}
        className="border-t border-line"
      >
        <div className="space-y-5 pb-2 pt-2">
          <fieldset>
            <legend className={`${FIELD_LABEL} flex items-center gap-1`}>
              How should it handle this step?
              <InfoTip label="exact words" align="start">
                Only the opening line is said word for word every time. With exact words it keeps
                to your line as closely as it can, but it may change a word or two.
              </InfoTip>
            </legend>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <ModeOption
                name={field("mode")}
                checked={!say}
                title="Guide it"
                hint="Say what to do. It finds its own words."
                onPick={() => onChange({ mode: "guide" })}
              />
              <ModeOption
                name={field("mode")}
                checked={say}
                title="Say these exact words"
                hint="Write the line it should say."
                onPick={() => onChange({ mode: "say" })}
              />
            </div>
          </fieldset>

          <SmallSteps
            id={field("procedure")}
            steps={section.procedure}
            limits={limits}
            issues={stepIssues}
            onChange={(procedure) => onChange({ procedure })}
          />

          <CollectEditor
            id={field("collect")}
            values={section.collect}
            max={limits.maxCollect}
            suggestions={(context?.collect ?? []).map((c) => c.label)}
            ideas={ideas.callerDetails}
            onChange={(collect) => onChange({ collect })}
          />

          <fieldset className="space-y-3">
            <legend className={FIELD_LABEL}>Where the call goes next</legend>
            {section.branches.length > 0 && (
              <ul className="space-y-3">
                {section.branches.map((branch, i) => {
                  const errs = errors(`branch-${i}`);
                  return (
                    <li key={i} className="rounded-md border border-line p-3">
                      <div className="flex items-start gap-2">
                        <div className="min-w-0 flex-1 space-y-2">
                          <label className="block">
                            <span className="text-meta text-ink-muted">When</span>
                            <input
                              className={`${FIELD} mt-0.5`}
                              value={branch.when}
                              maxLength={300}
                              placeholder="they say they are not interested"
                              aria-invalid={errs.length > 0 || undefined}
                              onChange={(e) => setBranch(i, { when: e.target.value })}
                            />
                          </label>
                          <label className="block">
                            <span className="text-meta text-ink-muted">Go to</span>
                            <select
                              className={`${FIELD} mt-0.5`}
                              value={branch.target}
                              onChange={(e) => setBranch(i, { target: e.target.value })}
                            >
                              {!options.some((o) => o.value === branch.target) && (
                                <option value={branch.target}>Pick where it goes</option>
                              )}
                              {options.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <button
                          type="button"
                          className={QUIET_ICON_BUTTON}
                          aria-label={`Remove way out ${i + 1}`}
                          onClick={() => onChange({ branches: section.branches.filter((_, j) => j !== i) })}
                        >
                          <X aria-hidden className="h-4 w-4" />
                        </button>
                      </div>
                      <FieldErrors id={field(`branch-${i}-err`)} issues={errs} />
                    </li>
                  );
                })}
              </ul>
            )}
            {section.branches.length < limits.maxBranches ? (
              <button
                type="button"
                className={`${TEXT_ACTION} inline-flex items-center gap-1`}
                onClick={() =>
                  onChange({
                    branches: [...section.branches, { when: "", target: options[0]?.value ?? "end" }],
                  })
                }
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                Add a way out
              </button>
            ) : (
              <p className="text-meta text-ink-muted">
                {limits.maxBranches} ways out is the most one step can have.
              </p>
            )}
            <label className="block">
              <span className={FIELD_LABEL}>{section.branches.length ? "Otherwise" : "Then"}</span>
              <select
                className={FIELD}
                value={section.otherwise}
                aria-invalid={errors("otherwise").length > 0 || undefined}
                onChange={(e) => onChange({ otherwise: e.target.value })}
              >
                <option value="">
                  {sections[index + 1]
                    ? `The next step (${index + 2}. ${sections[index + 1].name.trim() || "Untitled step"})`
                    : "Wrap up the call"}
                </option>
                {options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <FieldErrors id={field("otherwise-err")} issues={errors("otherwise")} />
          </fieldset>

          {!readOnly && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-4">
              <button
                type="button"
                className={`${TEXT_ACTION} inline-flex items-center gap-1`}
                disabled={index === 0}
                onClick={() => onMove(index - 1)}
              >
                <ArrowUp aria-hidden className="h-3.5 w-3.5" />
                Move earlier
              </button>
              <button
                type="button"
                className={`${TEXT_ACTION} inline-flex items-center gap-1`}
                disabled={index === sections.length - 1}
                onClick={() => onMove(index + 1)}
              >
                <ArrowDown aria-hidden className="h-3.5 w-3.5" />
                Move later
              </button>
              <button type="button" className={`${TEXT_ACTION_DANGER} ml-auto`} onClick={onDelete}>
                Delete step
              </button>
            </div>
          )}
        </div>
      </Disclosure>
    </fieldset>
  );
}

/** A step's letters count shows from this share of its limit; below it there is nothing to watch. */
export const LETTERS_SHOWN_FROM = 0.8;

/** What "More options" holds now, said on its closed row (UX-DOCTRINE §3). */
export function optionsLine(
  section: Section,
  sections: Section[],
  index: number,
  context: ScriptContext | null,
): string {
  return [
    section.mode === "say" ? "Exact words" : "Guided",
    `then ${lowerFirst(thenLabel(sections, index, context))}`,
    section.branches.length > 0
      ? `${section.branches.length} other ${section.branches.length === 1 ? "way" : "ways"} out`
      : "",
    section.collect.length > 0 ? `finds out ${section.collect.join(", ")}` : "",
    section.procedure.length > 0
      ? `${section.procedure.length} small ${section.procedure.length === 1 ? "step" : "steps"}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "Wraps up the call" reads "then wraps up the call"; a step's own "2. Name" keeps its case. */
function lowerFirst(text: string): string {
  return /^d/.test(text) ? text : text.charAt(0).toLowerCase() + text.slice(1);
}

function ModeOption({
  name,
  checked,
  title,
  hint,
  onPick,
}: {
  name: string;
  checked: boolean;
  title: string;
  hint: string;
  onPick: () => void;
}) {
  return (
    <label
      className={`flex cursor-pointer gap-2 rounded-md border px-3 py-2.5 touch:min-h-11 ${
        checked ? "border-brand bg-brand/[0.06]" : "border-line hover:bg-ink/[0.03]"
      }`}
    >
      <input type="radio" name={name} checked={checked} onChange={onPick} className="mt-0.5" />
      <span>
        <span className="block text-body font-medium text-ink">{title}</span>
        <span className="block text-meta text-ink-muted">{hint}</span>
      </span>
    </label>
  );
}

function FieldErrors({ id, issues }: { id: string; issues: Issue[] }) {
  if (issues.length === 0) return null;
  return (
    <p id={id} className="mt-1 text-meta text-danger">
      {issues.map((i) => i.message).join(" ")}
    </p>
  );
}

function CollectEditor({
  id,
  values,
  max,
  suggestions,
  ideas,
  onChange,
}: {
  id: string;
  values: string[];
  max: number;
  suggestions: string[];
  /** The account's own caller-detail ideas (D-827), offered after its lead details. */
  ideas: readonly string[];
  onChange: (values: string[]) => void;
}) {
  const [typed, setTyped] = useState("");
  const has = (v: string) => values.some((x) => x.trim().toLowerCase() === v.trim().toLowerCase());
  const add = (v: string) => {
    const clean = v.trim().slice(0, 80);
    if (!clean || has(clean) || values.length >= max) return;
    onChange([...values, clean]);
    setTyped("");
  };
  const offered = suggestions.filter((s) => !has(s));
  const lead = new Set(suggestions.map((s) => s.trim().toLowerCase()));
  const extra = ideas.filter((s) => !has(s) && !lead.has(s.trim().toLowerCase()));
  return (
    <div>
      <label className={FIELD_LABEL} htmlFor={id}>
        Details to find out here
      </label>
      <span className={FIELD_HINT}>
        It asks for these before moving on. {values.length} of {max}.
      </span>
      {values.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {values.map((v) => (
            <li key={v} className="inline-flex items-center gap-1 rounded-full bg-ink/[0.06] py-0.5 pl-3 pr-1 text-meta text-ink">
              {v}
              <button
                type="button"
                className="inline-flex h-6 w-6 items-center justify-center rounded-full text-ink-muted hover:bg-ink/[0.08] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
                aria-label={`Remove ${v}`}
                onClick={() => onChange(values.filter((x) => x !== v))}
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {values.length < max && (
        <>
          <div className="mt-2 flex gap-2">
            <input
              id={id}
              className={`${FIELD} mt-0`}
              value={typed}
              maxLength={80}
              placeholder={`For example: ${ideas[0] ?? "best time to call back"}`}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  add(typed);
                }
              }}
            />
            <button type="button" className={TEXT_ACTION} disabled={!typed.trim()} onClick={() => add(typed)}>
              Add
            </button>
          </div>
          <ChipOffer heading="Your lead details:" items={offered} onAdd={add} />
          <ChipOffer heading="Ideas for your business:" items={extra} onAdd={add} />
        </>
      )}
    </div>
  );
}

function ChipOffer({ heading, items, onAdd }: { heading: string; items: readonly string[]; onAdd: (v: string) => void }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-2">
      <p className="text-meta text-ink-muted">{heading}</p>
      <ul className="mt-1 flex flex-wrap gap-1.5">
        {items.map((s) => (
          <li key={s}>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-meta text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              onClick={() => onAdd(s)}
            >
              <Plus aria-hidden className="h-3 w-3" />
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
