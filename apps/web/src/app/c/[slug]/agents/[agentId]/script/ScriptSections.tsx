"use client";

/**
 * THE WHOLE-SCRIPT PARTS of a call script, around the call's sections (which are edited in
 * `SectionList`, `FlowCanvas` and `SectionEditor`).
 *
 * Each part answers one plain question an owner can answer about their own business: who
 * the agent is, what a good call achieves, how it opens, how it speaks, how it handles
 * push-back, what it may do, how it ends, how closely it follows the sections, and an
 * example call. Each part's element id is its anchor (`#policies`), which Knowledge's
 * "Fix in script" links to. They mirror `calevate_shared.call_script` section for section;
 * the platform's own rules (how to speak on a phone, where facts are, call backs and
 * hand-over, the truthful answers) are composed around them and are not edited here.
 *
 * None of these reads the network: each takes a value and hands back the next one, so the
 * builder shell owns every write. Every text control takes `trackFocus`, which records the
 * last field the author touched so a merge field lands at their cursor.
 */

import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON_SM,
  ToggleSwitch,
} from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import type {
  CallScript,
  CodeMix,
  ExampleLine,
  Objection,
  Pronunciation,
  ScriptContext,
  ScriptPolicies,
  SpeakingStyle,
} from "@/lib/api/script";

/** The two text controls a merge field can be inserted into. */
export type Focusable = HTMLInputElement | HTMLTextAreaElement;
type Track = (el: Focusable | null) => void;

/** One guided section: a question as its heading, one line of help, then the controls.
 *  Sections are separated by a rule rather than boxed, so nothing nests inside a card. */
function Section({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="scroll-mt-24 border-t border-line pt-6 first:border-t-0 first:pt-0">
      <h4 id={`${id}-heading`} className="text-sm font-semibold text-ink">
        {title}
      </h4>
      {hint && <p className="mt-1 text-sm text-ink-muted">{hint}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function TextBox({
  id,
  label,
  hint,
  value,
  rows = 2,
  maxLength,
  placeholder,
  onChange,
  trackFocus,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  rows?: number;
  maxLength?: number;
  placeholder?: string;
  onChange: (v: string) => void;
  trackFocus: Track;
}) {
  return (
    <div>
      <label className={FIELD_LABEL} htmlFor={id}>
        {label}
      </label>
      {hint && <span className={FIELD_HINT}>{hint}</span>}
      {rows === 1 ? (
        <input
          id={id}
          className={FIELD}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          onFocus={(e) => trackFocus(e.currentTarget)}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <textarea
          id={id}
          className={FIELD}
          rows={rows}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          onFocus={(e) => trackFocus(e.currentTarget)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}

/** Reorder and remove buttons for one row of a list. */
function RowControls({
  what,
  index,
  count,
  onMove,
  onRemove,
}: {
  what: string;
  index: number;
  count: number;
  onMove?: (from: number, to: number) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="flex shrink-0 gap-1">
      {onMove && (
        <>
          <button
            type="button"
            className={QUIET_ICON_BUTTON}
            aria-label={`Move ${what} ${index + 1} up`}
            disabled={index === 0}
            onClick={() => onMove(index, index - 1)}
          >
            <ArrowUp aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            className={QUIET_ICON_BUTTON}
            aria-label={`Move ${what} ${index + 1} down`}
            disabled={index === count - 1}
            onClick={() => onMove(index, index + 1)}
          >
            <ArrowDown aria-hidden className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      <button
        type="button"
        className={QUIET_ICON_BUTTON}
        aria-label={`Remove ${what} ${index + 1}`}
        onClick={() => onRemove(index)}
      >
        <Trash2 aria-hidden className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className={`${TEXT_ACTION} inline-flex items-center gap-1`} onClick={onClick}>
      <Plus aria-hidden className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

// --- the sections ---------------------------------------------------------------------

type SetField = <K extends keyof CallScript>(key: K, value: CallScript[K]) => void;

export function IdentitySection({
  script,
  set,
  trackFocus,
}: {
  script: CallScript;
  set: SetField;
  trackFocus: Track;
}) {
  return (
    <Section id="identity" title="Who is the agent?" hint="Who it works for and the job it does on the phone.">
      <TextBox
        id="business-line"
        label="Your business in one line"
        hint="Up to 200 characters. For example: an organic produce shop in Kukatpally."
        rows={1}
        maxLength={200}
        value={script.business_line}
        onChange={(v) => set("business_line", v)}
        trackFocus={trackFocus}
      />
      <TextBox
        id="identity-text"
        label="Its role"
        value={script.identity}
        placeholder="For example: You answer the phone for the shop. You help callers find what they need and take their order."
        onChange={(v) => set("identity", v)}
        trackFocus={trackFocus}
      />
    </Section>
  );
}

export function GoalSection({
  script,
  set,
  direction,
  trackFocus,
}: {
  script: CallScript;
  set: SetField;
  direction: string;
  trackFocus: Track;
}) {
  const calls = direction === "outbound" || direction === "both";
  return (
    <Section id="goal" title="What should a good call achieve?">
      <TextBox
        id="goal-text"
        label="The goal"
        value={script.goal}
        placeholder="For example: Answer their question and, if they want to buy, take the order and the delivery area."
        onChange={(v) => set("goal", v)}
        trackFocus={trackFocus}
      />
      {calls && (
        <TextBox
          id="outbound-purpose"
          label="Why you are calling"
          hint="One sentence the agent says early on a call it places. Up to 300 characters."
          rows={1}
          maxLength={300}
          value={script.outbound_purpose}
          placeholder="For example: You asked about our cold-pressed oils last week, so I am calling to help you order."
          onChange={(v) => set("outbound_purpose", v)}
          trackFocus={trackFocus}
        />
      )}
    </Section>
  );
}

export function OpeningSection({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: Track;
}) {
  return (
    <Section
      id="opening"
      title="How does it open?"
      hint="The greeting it starts every call with. If you have switched on the AI or recording notice, that is said just before it."
    >
      <TextBox
        id="opening-line"
        label="Opening line"
        value={value}
        placeholder="For example: Namaskaram andi, cheppandi, em kavali?"
        onChange={onChange}
        trackFocus={trackFocus}
      />
    </Section>
  );
}

const CODE_MIX_OPTIONS: { value: CodeMix; label: string; hint: string }[] = [
  { value: "light", label: "Mostly local", hint: "English only where people have no other word." },
  { value: "natural", label: "Everyday mix", hint: "The English words people use every day." },
  { value: "heavy", label: "Lots of English", hint: "Like young city callers." },
];

export function StyleSection({
  style,
  onChange,
  context,
  trackFocus,
}: {
  style: SpeakingStyle;
  onChange: (style: SpeakingStyle) => void;
  context: ScriptContext | null;
  trackFocus: Track;
}) {
  const patch = (next: Partial<SpeakingStyle>) => onChange({ ...style, ...next });
  const setWords = (words: Pronunciation[]) => patch({ pronunciations: words });
  return (
    <Section
      id="style"
      title="How does it speak?"
      hint={
        context?.register_name
          ? `It speaks ${context.register_name}, the way people talk on the phone, not textbook language.`
          : "It speaks the way people talk on the phone, not textbook language."
      }
    >
      <TextBox
        id="tone"
        label="Tone"
        rows={1}
        maxLength={300}
        value={style.tone}
        placeholder="For example: warm, calm and quick"
        onChange={(v) => patch({ tone: v })}
        trackFocus={trackFocus}
      />
      <TextBox
        id="address-form"
        label="How it addresses callers"
        rows={1}
        maxLength={200}
        value={style.address_form}
        placeholder="For example: andi and garu, never by first name"
        onChange={(v) => patch({ address_form: v })}
        trackFocus={trackFocus}
      />
      <fieldset>
        <legend className={FIELD_LABEL}>English words in its speech</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {CODE_MIX_OPTIONS.map((option) => (
            <label
              key={option.value}
              className={`flex cursor-pointer flex-col rounded-md border px-3 py-2 text-sm ${
                style.code_mix === option.value ? "border-brand bg-brand/[0.06]" : "border-line"
              }`}
            >
              <span className="flex items-center gap-2 font-medium text-ink">
                <input
                  type="radio"
                  name="code-mix"
                  value={option.value}
                  checked={style.code_mix === option.value}
                  onChange={() => patch({ code_mix: option.value })}
                />
                {option.label}
              </span>
              <span className="mt-0.5 text-xs text-ink-muted">{option.hint}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <TextBox
        id="sample-phrases"
        label="Phrases it can use"
        hint="One per line, in your callers' language. It varies them rather than repeating one."
        rows={3}
        value={style.sample_phrases.join("\n")}
        onChange={(v) => patch({ sample_phrases: v.split("\n") })}
        trackFocus={trackFocus}
      />
      <div>
        <span className={FIELD_LABEL}>Words it might say wrongly</span>
        <span className={FIELD_HINT}>Names of products, places or people, and how to say them.</span>
        {style.pronunciations.length > 0 && (
          <ul className="mt-2 space-y-2">
            {style.pronunciations.map((word, i) => (
              <li key={i} className="flex items-start gap-2">
                <input
                  className={`${FIELD} mt-0`}
                  aria-label={`Word ${i + 1}`}
                  value={word.word}
                  placeholder="Kukatpally"
                  onFocus={(e) => trackFocus(e.currentTarget)}
                  onChange={(e) =>
                    setWords(style.pronunciations.map((w, j) => (j === i ? { ...w, word: e.target.value } : w)))
                  }
                />
                <input
                  className={`${FIELD} mt-0`}
                  aria-label={`Say word ${i + 1} as`}
                  value={word.say_as}
                  placeholder="Koo-kut-pul-lee"
                  onFocus={(e) => trackFocus(e.currentTarget)}
                  onChange={(e) =>
                    setWords(style.pronunciations.map((w, j) => (j === i ? { ...w, say_as: e.target.value } : w)))
                  }
                />
                <RowControls
                  what="word"
                  index={i}
                  count={style.pronunciations.length}
                  onRemove={(index) => setWords(style.pronunciations.filter((_, j) => j !== index))}
                />
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2">
          <AddButton label="Add a word" onClick={() => setWords([...style.pronunciations, { word: "", say_as: "" }])} />
        </div>
      </div>
    </Section>
  );
}

export function ObjectionsSection({
  objections,
  onChange,
  trackFocus,
}: {
  objections: Objection[];
  onChange: (objections: Objection[]) => void;
  trackFocus: Track;
}) {
  const update = (i: number, next: Partial<Objection>) =>
    onChange(objections.map((o, j) => (j === i ? { ...o, ...next } : o)));
  return (
    <Section
      id="objections"
      title="When callers push back"
      hint="What callers say when they hesitate, and how the agent should answer, in your own words."
    >
      {objections.length > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {objections.map((o, i) => (
            <li key={i} className="flex items-start gap-2 py-3">
              <div className="flex-1 space-y-2">
                <input
                  className={`${FIELD} mt-0`}
                  aria-label={`Objection ${i + 1}: what they say`}
                  value={o.objection}
                  maxLength={300}
                  placeholder="It is too expensive."
                  onFocus={(e) => trackFocus(e.currentTarget)}
                  onChange={(e) => update(i, { objection: e.target.value })}
                />
                <textarea
                  className={`${FIELD} mt-0`}
                  rows={2}
                  aria-label={`Objection ${i + 1}: how to answer`}
                  value={o.response}
                  placeholder="Say what makes it worth the price. If they still say no, accept it."
                  onFocus={(e) => trackFocus(e.currentTarget)}
                  onChange={(e) => update(i, { response: e.target.value })}
                />
              </div>
              <RowControls
                what="objection"
                index={i}
                count={objections.length}
                onRemove={(index) => onChange(objections.filter((_, j) => j !== index))}
              />
            </li>
          ))}
        </ul>
      )}
      <AddButton
        label="Add a push-back"
        onClick={() => onChange([...objections, { objection: "", response: "" }])}
      />
    </Section>
  );
}

export function PoliciesSection({
  policies,
  onChange,
  context,
}: {
  policies: ScriptPolicies;
  onChange: (policies: ScriptPolicies) => void;
  context: ScriptContext | null;
}) {
  const trial = context !== null && !context.call_backs_available;
  return (
    <Section
      id="policies"
      title="What may it do?"
      hint="Stop-calling requests are always recorded, and the agent always answers truthfully whether it is an AI."
    >
      <ToggleSwitch
        label="Offer a call back when it cannot help"
        hint={
          trial
            ? "During your free trial the agent never offers a call back, because none can be placed. It says the business will get back to them instead."
            : "When off, it says the business will get back to them."
        }
        checked={policies.offer_call_backs && !trial}
        disabled={trial}
        onChange={(next) => onChange({ ...policies, offer_call_backs: next })}
      />
      <ToggleSwitch
        label="Tell callers prices"
        hint="Only prices it finds in your knowledge or quick facts. When off, it says the team will share them."
        checked={policies.share_prices}
        onChange={(next) => onChange({ ...policies, share_prices: next })}
      />
      <ToggleSwitch
        label="Take bookings and orders"
        hint="When off, it notes what they want and when it suits them."
        checked={policies.take_bookings}
        onChange={(next) => onChange({ ...policies, take_bookings: next })}
      />
      <p className="text-sm text-ink-muted">
        {context?.hand_over_enabled
          ? "Handing a caller to a person is on. It happens only when they ask for a person and someone is on duty."
          : "Handing a caller to a person is off. When a caller asks for one, the agent says nobody is free right now."}
      </p>
    </Section>
  );
}

export function EndingSection({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: Track;
}) {
  return (
    <Section id="ending" title="How does it end the call?">
      <TextBox
        id="ending-text"
        label="Ending"
        value={value}
        placeholder="For example: Confirm the order and the delivery area, thank them by name and say goodbye."
        onChange={onChange}
        trackFocus={trackFocus}
      />
    </Section>
  );
}

export function ExampleSection({
  lines,
  needsReview,
  onChange,
  trackFocus,
}: {
  lines: ExampleLine[];
  needsReview: boolean;
  onChange: (lines: ExampleLine[], stillNeedsReview: boolean) => void;
  trackFocus: Track;
}) {
  // Any edit by the owner is their own reading of it, so the review flag clears.
  const edit = (next: ExampleLine[]) => onChange(next, false);
  return (
    <Section
      id="example"
      title="An example call"
      hint="A few lines in your callers' language that show how a good call sounds. The agent copies the style, never the facts in it."
    >
      {needsReview && lines.length > 0 && (
        <NoticeBox tone="warn" title="Written by AI, waiting for a native speaker">
          <p className="mt-1 text-meta">
            Read it aloud. Change any line that does not sound like your callers; once you
            edit it, it counts as yours.
          </p>
        </NoticeBox>
      )}
      {lines.length > 0 && (
        <ul className="space-y-2">
          {lines.map((line, i) => (
            <li key={i} className="flex items-start gap-2">
              <select
                className={`${FIELD} mt-0 w-28 shrink-0`}
                aria-label={`Line ${i + 1}: who speaks`}
                value={line.speaker}
                onChange={(e) =>
                  edit(lines.map((l, j) => (j === i ? { ...l, speaker: e.target.value as ExampleLine["speaker"] } : l)))
                }
              >
                <option value="caller">Caller</option>
                <option value="agent">Agent</option>
              </select>
              <input
                className={`${FIELD} mt-0`}
                aria-label={`Line ${i + 1}`}
                value={line.text}
                maxLength={500}
                onFocus={(e) => trackFocus(e.currentTarget)}
                onChange={(e) => edit(lines.map((l, j) => (j === i ? { ...l, text: e.target.value } : l)))}
              />
              <RowControls
                what="line"
                index={i}
                count={lines.length}
                onRemove={(index) => edit(lines.filter((_, j) => j !== index))}
              />
            </li>
          ))}
        </ul>
      )}
      <AddButton
        label="Add a line"
        onClick={() =>
          edit([...lines, { speaker: lines.at(-1)?.speaker === "caller" ? "agent" : "caller", text: "" }])
        }
      />
    </Section>
  );
}

export function VariableBar({
  standard,
  custom,
  onInsert,
}: {
  standard: { key: string; label: string }[];
  custom: { key: string; label: string }[];
  onInsert: (key: string) => void;
}) {
  const all = [...standard, ...custom.filter((c) => !standard.some((s) => s.key === c.key))];
  return (
    <div>
      <span className={FIELD_LABEL}>Insert a merge field</span>
      <span className={FIELD_HINT}>
        Click a field to drop it where your cursor is. It is filled in from the lead when the
        call is placed; if there is no value, it simply disappears.
      </span>
      <div className="mt-2 flex flex-wrap gap-2">
        {all.map((v) => (
          <button
            key={v.key}
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => onInsert(v.key)}
          >
            <Plus aria-hidden className="h-3 w-3" />
            {v.label}
          </button>
        ))}
      </div>
    </div>
  );
}


export function StrictnessSection({
  value,
  onChange,
}: {
  value: "flexible" | "strict";
  onChange: (value: "flexible" | "strict") => void;
}) {
  const options = [
    {
      value: "flexible" as const,
      label: "Use the sections as a guide",
      hint: "It follows your order but goes where the caller takes the call, and skips what is already done.",
    },
    {
      value: "strict" as const,
      label: "Follow the sections closely",
      hint: "It goes through them in order and keeps to your exact-words lines as closely as it can.",
    },
  ];
  return (
    <fieldset>
      <legend className="text-sm font-semibold text-ink">How closely should it follow the sections?</legend>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {options.map((option) => (
          <label
            key={option.value}
            className={`flex cursor-pointer gap-2 rounded-md border px-3 py-2.5 touch:min-h-11 ${
              value === option.value ? "border-brand bg-brand/[0.06]" : "border-line hover:bg-ink/[0.03]"
            }`}
          >
            <input
              type="radio"
              name="adherence"
              className="mt-0.5"
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span>
              <span className="block text-body font-medium text-ink">{option.label}</span>
              <span className="block text-meta text-ink-muted">{option.hint}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
