"use client";

/**
 * THE WHOLE-SCRIPT PARTS of a call script, around the call's sections (which are edited in
 * `SectionList`, `FlowCanvas` and `SectionEditor`).
 *
 * Each part answers one plain question an owner can answer about their own business: who
 * the agent is, what a good call achieves, how it opens, how it speaks, how it handles
 * push-back, what it may do, how it ends, how closely it follows the sections, and an
 * example call. Most of them are set once and rarely changed, so `ScriptParts` shows them
 * as a summary list whose rows open these bodies in place; how the call opens and the
 * strictness choice stay on the page. Each part's element id is its anchor (`#policies`),
 * which Knowledge's "Fix in script" links to. They mirror `calevate_shared.call_script` section for section;
 * the platform's own rules (how to speak on a phone, where facts are, call backs and
 * hand-over, the truthful answers) are composed around them and are not edited here.
 *
 * None of these reads the network: each takes a value and hands back the next one, so the
 * builder shell owns every write. Every text box keeps the script plain text
 * (`usePlainText`), by the same rule as the kit's `ScriptEditor`.
 */

import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { ScriptEditor, type ScriptVariableOption } from "@/components/arc/script-editor";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  QUIET_ICON_BUTTON,
  ToggleSwitch,
} from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
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
import type { VerticalExamples } from "@/lib/verticalExamples";

import { CleanedNote, usePlainText } from "./plainText";

/** The account's own examples these parts show as placeholders (`useVerticalExamples`, D-827). */
export type ScriptExamples = Pick<
  VerticalExamples,
  | "businessLine"
  | "agentRole"
  | "callGoal"
  | "outboundPurpose"
  | "callEnding"
  | "pronounceWord"
  | "pronounceSayAs"
>;

/**
 * The body of one part. Its heading is the row that opens it (`ScriptParts`), so the body
 * carries no title of its own, only at most one line of help. The id is the part's anchor
 * (`#policies`), which Knowledge's "Fix in script" links to.
 */
function Section({ id, hint, children }: { id: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div id={id} className="scroll-mt-24 space-y-3">
      {hint && <p className="text-meta text-ink-muted">{hint}</p>}
      {children}
    </div>
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
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  rows?: number;
  maxLength?: number;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  const plain = usePlainText();
  const change = (raw: string) => onChange(plain.take(raw));
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
          onChange={(e) => change(e.target.value)}
        />
      ) : (
        <textarea
          id={id}
          className={FIELD}
          rows={rows}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          onChange={(e) => change(e.target.value)}
        />
      )}
      <CleanedNote shown={plain.cleaned} />
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
  eg,
}: {
  script: CallScript;
  set: SetField;
  eg: ScriptExamples;
}) {
  return (
    <Section id="identity">
      <TextBox
        id="business-line"
        label="Your business in one line"
        hint="Up to 200 letters."
        placeholder={`For example: ${eg.businessLine}`}
        rows={1}
        maxLength={200}
        value={script.business_line}
        onChange={(v) => set("business_line", v)}
      />
      <TextBox
        id="identity-text"
        label="Its role"
        value={script.identity}
        placeholder={`For example: ${eg.agentRole}`}
        onChange={(v) => set("identity", v)}
      />
    </Section>
  );
}

export function GoalSection({
  script,
  set,
  eg,
}: {
  script: CallScript;
  set: SetField;
  eg: ScriptExamples;
}) {
  return (
    <Section id="goal">
      <TextBox
        id="goal-text"
        label="The goal"
        value={script.goal}
        placeholder={`For example: ${eg.callGoal}`}
        onChange={(v) => set("goal", v)}
      />
    </Section>
  );
}

/** Server limit on `outbound_purpose` (`call_script.py`; `scriptModel.validate` holds the autosave over it). */
export const OUTBOUND_PURPOSE_MAX = 300;

/** The caller details a script may name: the platform's standard ones and the client's own. */
export function scriptVariables(
  standard: { key: string; label: string }[],
  custom: { key: string; label: string; example?: string }[],
): ScriptVariableOption[] {
  // The preview says the client's own example value where they gave one, and otherwise
  // names the detail where the caller's value will be said.
  const own = custom.filter((c) => !standard.some((s) => s.key === c.key));
  return [
    ...standard.map((v) => ({ key: v.key, label: v.label, sample: v.label })),
    ...own.map((v) => ({ key: v.key, label: v.label, sample: v.example?.trim() || v.label })),
  ];
}

/** When a caller detail has a value on a call, which depends on who places the call. */
export function variablesNote(direction?: string): string {
  const places = direction !== "inbound";
  const answers = direction === "inbound" || direction === "both";
  return [
    places ? "On a call this agent places, a caller detail is filled from the lead." : "",
    answers ? "On a call it answers, it is filled only when the caller has called before." : "",
    "When there is no value, it is left out and the sentence still reads.",
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * HOW THE CALL OPENS: the words said verbatim at the start of a call, in the kit's
 * `ScriptEditor` — the opening line and, on an agent that places calls, why it is calling.
 * Each has its budget: the opening line the room the server measured after the notices
 * switched on (D-846, `greeting_budget.opening_room`), the reason its 300 characters. Over
 * budget is marked and holds nothing back here: the autosave keeps it, and the server's
 * own checks decide at "Put it live".
 *
 * The parts that are instructions to the agent rather than words it says (the goal, the
 * ending, each step) stay where they are; a "how it will sound" preview of an instruction
 * would show words no caller hears.
 */
export function OpeningEditor({
  script,
  set,
  direction,
  room,
  standardVariables,
  eg,
  previewAction,
}: {
  script: CallScript;
  set: SetField;
  direction?: string;
  /** Characters the opening line may have after the notices switched on; undefined while unknown. */
  room?: number;
  standardVariables: { key: string; label: string }[];
  eg: ScriptExamples;
  previewAction?: ReactNode;
}) {
  const calls = direction === "outbound" || direction === "both";
  const sections = [
    {
      id: "opening_line",
      title: "Opening line",
      hint: "The first thing it says on every call, straight after any notices you switched on, so it has to fit the room they leave.",
      value: script.opening_line,
      maxChars: room,
      placeholder: "For example: Namaskaram andi, cheppandi, em kavali?",
      rows: 2,
    },
    ...(calls
      ? [
          {
            id: "outbound_purpose",
            title: "Why you are calling",
            hint: "Said early on calls it places.",
            value: script.outbound_purpose,
            maxChars: OUTBOUND_PURPOSE_MAX,
            placeholder: `For example: ${eg.outboundPurpose}`,
            rows: 2,
          },
        ]
      : []),
  ];
  return (
    <section id="opening" aria-labelledby="opening-heading" className="scroll-mt-24 space-y-3">
      <div className="flex items-center gap-1">
        <h3 id="opening-heading" className="text-heading text-ink">
          How the call opens
        </h3>
        <InfoTip label="caller details" align="start">
          {variablesNote(direction)}
        </InfoTip>
      </div>
      <ScriptEditor
        sections={sections}
        onChange={(id, value) => set(id === "outbound_purpose" ? "outbound_purpose" : "opening_line", value)}
        variables={scriptVariables(standardVariables, script.variables)}
        previewAction={previewAction}
        strings={{
          left: (n) => `${n} ${n === "1" ? "character" : "characters"} left`,
          over: (n) => `${n} ${n === "1" ? "character" : "characters"} too long`,
          previewEmpty: "Write the opening line to see how the call starts.",
        }}
      />
    </section>
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
  eg,
}: {
  style: SpeakingStyle;
  onChange: (style: SpeakingStyle) => void;
  context: ScriptContext | null;
  eg: ScriptExamples;
}) {
  const patch = (next: Partial<SpeakingStyle>) => onChange({ ...style, ...next });
  const setWords = (words: Pronunciation[]) => patch({ pronunciations: words });
  return (
    <Section
      id="style"
      hint={
        context?.register_name
          ? `It speaks ${context.register_name}, the way people talk on the phone.`
          : "It speaks the way people talk on the phone."
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
      />
      <TextBox
        id="address-form"
        label="How it addresses callers"
        rows={1}
        maxLength={200}
        value={style.address_form}
        placeholder="For example: andi and garu, never by first name"
        onChange={(v) => patch({ address_form: v })}
      />
      <fieldset>
        <legend className={FIELD_LABEL}>English words in its speech</legend>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
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
      />
      <div>
        <span className={FIELD_LABEL}>Names and how to say them</span>
        <span className={FIELD_HINT}>
          Products, places or people, and exactly what to call them on a call, such as a product&apos;s name in
          your callers&apos; language. The agent never translates a name itself.
        </span>
        {style.pronunciations.length > 0 && (
          <ul className="mt-2 space-y-2">
            {style.pronunciations.map((word, i) => (
              <li key={i} className="flex items-start gap-2">
                <input
                  className={`${FIELD} mt-0 min-w-0`}
                  aria-label={`Word ${i + 1}`}
                  value={word.word}
                  placeholder={eg.pronounceWord}
                  onChange={(e) =>
                    setWords(style.pronunciations.map((w, j) => (j === i ? { ...w, word: e.target.value } : w)))
                  }
                />
                <input
                  className={`${FIELD} mt-0 min-w-0`}
                  aria-label={`Say word ${i + 1} as`}
                  value={word.say_as}
                  placeholder={eg.pronounceSayAs}
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
}: {
  objections: Objection[];
  onChange: (objections: Objection[]) => void;
}) {
  const plain = usePlainText();
  const update = (i: number, next: Partial<Objection>) =>
    onChange(objections.map((o, j) => (j === i ? { ...o, ...next } : o)));
  return (
    <Section id="objections" hint="What callers say when they hesitate, and how to answer.">
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
                  onChange={(e) => update(i, { objection: plain.take(e.target.value) })}
                />
                <textarea
                  className={`${FIELD} mt-0`}
                  rows={2}
                  aria-label={`Objection ${i + 1}: how to answer`}
                  value={o.response}
                  placeholder="Say what makes it worth the price. If they still say no, accept it."
                  onChange={(e) => update(i, { response: plain.take(e.target.value) })}
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
      <CleanedNote shown={plain.cleaned} />
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
        hint="Only prices it finds in what you taught it. When off, it says the team will share them."
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
  eg,
}: {
  value: string;
  onChange: (v: string) => void;
  eg: ScriptExamples;
}) {
  return (
    <Section id="ending">
      <TextBox
        id="ending-text"
        label="Ending"
        value={value}
        placeholder={`For example: ${eg.callEnding}`}
        onChange={onChange}
      />
    </Section>
  );
}

export function ExampleSection({
  lines,
  needsReview,
  onChange,
}: {
  lines: ExampleLine[];
  needsReview: boolean;
  onChange: (lines: ExampleLine[], stillNeedsReview: boolean) => void;
}) {
  // Any edit by the owner is their own reading of it, so the review flag clears.
  const edit = (next: ExampleLine[]) => onChange(next, false);
  const plain = usePlainText();
  return (
    <Section id="example" hint="A few lines in your callers' language. It copies the style, never the facts.">
      {needsReview && lines.length > 0 && (
        <NoticeBox
          tone="warn"
          title="Written by AI, waiting for a native speaker"
          info="Read it aloud. Change any line that does not sound like your callers; once you edit it, it counts as yours."
        />
      )}
      {lines.length > 0 && (
        <ul className="space-y-2">
          {lines.map((line, i) => (
            <li key={i} className="flex items-start gap-2">
              <select
                className={`${FIELD} mt-0 max-w-28 shrink-0`}
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
                className={`${FIELD} mt-0 min-w-0`}
                aria-label={`Line ${i + 1}`}
                value={line.text}
                maxLength={500}
                onChange={(e) => edit(lines.map((l, j) => (j === i ? { ...l, text: plain.take(e.target.value) } : l)))}
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
      <CleanedNote shown={plain.cleaned} />
      <AddButton
        label="Add a line"
        onClick={() =>
          edit([...lines, { speaker: lines.at(-1)?.speaker === "caller" ? "agent" : "caller", text: "" }])
        }
      />
    </Section>
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
      label: "Use the steps as a guide",
      hint: "It follows your order but goes where the caller takes the call, and skips what is already done.",
    },
    {
      value: "strict" as const,
      label: "Follow the steps closely",
      hint: "It goes through them in order and keeps to your exact-words lines as closely as it can.",
    },
  ];
  // One line on the page; what each choice does is behind the ⓘ, because an owner picks
  // this once and the labels already say the difference.
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <span className="flex items-center gap-1">
        <span id="adherence-label" className="text-body font-medium text-ink">
          How closely it follows them
        </span>
        <InfoTip label="how closely it follows the steps" align="start">
          {options.map((option) => (
            <p key={option.value}>
              <span className="font-medium text-ink">{option.label}:</span> {option.hint}
            </p>
          ))}
        </InfoTip>
      </span>
      <div role="radiogroup" aria-labelledby="adherence-label" className="flex flex-wrap gap-x-4">
        {options.map((option) => (
          <label key={option.value} className="flex cursor-pointer items-center gap-2 text-body text-ink touch:min-h-11">
            <input
              type="radio"
              name="adherence"
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}
