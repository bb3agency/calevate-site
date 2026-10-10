"use client";

/**
 * ONE SECTION, EDITED — the panel beside the canvas or the list on a desktop, a sheet on a
 * phone. The same component in both places, writing through the same `onChange`, which is
 * what keeps the two views one script.
 */

import { useId, useState } from "react";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON, formatCount } from "@/components/ui";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import type { ScriptContext } from "@/lib/api/script";

import { chars, issuesFor, sectionDetail, type Issue, type Limits, type Section } from "./scriptModel";
import { languageName, targetOptions } from "./sectionParts";

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
  const field = (name: string) => `${uid}-${name}`;
  const errors = (name: string) => issuesFor(issues, section.id, name);
  const used = chars(sectionDetail(section));
  const over = used > limits.detailMax;
  const language = languageName(context?.language);
  const options = targetOptions(sections, section.id, context);
  const say = section.mode === "say";

  const setBranch = (i: number, patch: Partial<Section["branches"][number]>) =>
    onChange({ branches: section.branches.map((b, j) => (j === i ? { ...b, ...patch } : b)) });

  return (
    <fieldset disabled={readOnly} className="min-w-0 space-y-5">
      <legend className="sr-only">Section {index + 1}</legend>
      <div>
        <label className={FIELD_LABEL} htmlFor={field("name")}>
          Section name
        </label>
        <input
          id={field("name")}
          className={FIELD}
          value={section.name}
          maxLength={limits.nameMax}
          placeholder="For example: Find out what they need"
          aria-invalid={errors("name").length > 0 || undefined}
          aria-describedby={errors("name").length ? field("name-err") : undefined}
          onChange={(e) => onChange({ name: e.target.value })}
        />
        <FieldErrors id={field("name-err")} issues={errors("name")} />
      </div>

      <fieldset>
        <legend className={FIELD_LABEL}>How should it handle this part?</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
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
        {say && (
          <p className="mt-2 text-meta text-ink-muted">
            Only the opening line is said word for word every time. Here it keeps to your words
            as closely as it can, but it may change a word or two.
          </p>
        )}
      </fieldset>

      <div>
        <label className={FIELD_LABEL} htmlFor={field("instruction")}>
          {say ? "The words to say" : "What to do here"}
        </label>
        <span className={FIELD_HINT}>
          {say ? `In ${language}, as callers should hear it.` : "In plain English. One or two sentences is plenty."}
        </span>
        <textarea
          id={field("instruction")}
          className={FIELD}
          rows={4}
          value={section.instruction}
          placeholder={
            say ? "For example: Mee peru cheppagalara?" : "For example: Ask what they are looking for and how many they need."
          }
          aria-invalid={errors("instruction").length > 0 || undefined}
          aria-describedby={`${field("count")}${errors("instruction").length ? ` ${field("instruction-err")}` : ""}`}
          onChange={(e) => onChange({ instruction: e.target.value })}
        />
        <p
          id={field("count")}
          className={`mt-1 text-meta tabular-nums ${over ? "text-danger" : "text-ink-faint"}`}
        >
          {over
            ? `${formatCount(used - limits.detailMax)} letters over. This box and the line below share ${formatCount(limits.detailMax)}.`
            : `${formatCount(limits.detailMax - used)} of ${formatCount(limits.detailMax)} letters left, shared with the line below.`}
        </p>
        <FieldErrors id={field("instruction-err")} issues={errors("instruction").filter((i) => !i.message.includes("too long"))} />
      </div>

      <div>
        <label className={FIELD_LABEL} htmlFor={field("sounds")}>
          Sounds like (optional)
        </label>
        <span className={FIELD_HINT}>One line in {language} showing how this part sounds on the phone.</span>
        <input
          id={field("sounds")}
          className={FIELD}
          value={section.sounds_like}
          maxLength={limits.soundsLikeMax}
          aria-invalid={errors("sounds_like").length > 0 || undefined}
          onChange={(e) => onChange({ sounds_like: e.target.value })}
        />
        <FieldErrors id={field("sounds-err")} issues={errors("sounds_like")} />
      </div>

      <CollectEditor
        id={field("collect")}
        values={section.collect}
        max={limits.maxCollect}
        suggestions={(context?.collect ?? []).map((c) => c.label)}
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
            {limits.maxBranches} ways out is the most one section can have.
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
                ? `The next section (${index + 2}. ${sections[index + 1].name.trim() || "Untitled section"})`
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
            Delete section
          </button>
        </div>
      )}
    </fieldset>
  );
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
  onChange,
}: {
  id: string;
  values: string[];
  max: number;
  suggestions: string[];
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
              placeholder="For example: delivery area"
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
          {offered.length > 0 && (
            <div className="mt-2">
              <p className="text-meta text-ink-muted">Your lead details:</p>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {offered.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-0.5 text-meta text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                      onClick={() => add(s)}
                    >
                      <Plus aria-hidden className="h-3 w-3" />
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
