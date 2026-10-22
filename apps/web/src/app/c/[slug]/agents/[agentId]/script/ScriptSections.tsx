"use client";

/**
 * THE WHOLE-SCRIPT PARTS of a call script, around the call's sections (which are edited in
 * `SectionList`, `FlowCanvas` and `SectionEditor`).
 *
 * Each part answers one plain question an owner can answer about their own business: who
 * the agent is, what a good call achieves, how it opens, how it speaks, how it handles
 * push-back, what it may do, how it ends, how closely it follows the sections, and an
 * example call. Most of them are set once and rarely changed, so `ScriptParts` shows them
 * as a summary list whose rows open these bodies in place; the opening line and the
 * strictness choice stay on the page. Each part's element id is its anchor (`#policies`),
 * which Knowledge's "Fix in script" links to. They mirror `calevate_shared.call_script` section for section;
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

import { RoomCounter, roomLabel } from "../../panels/openingLineFix";

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

/** The two text controls a merge field can be inserted into. */
export type Focusable = HTMLInputElement | HTMLTextAreaElement;
type Track = (el: Focusable | null) => void;

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
  info,
  value,
  rows = 2,
  maxLength,
  placeholder,
  onChange,
  trackFocus,
  describedBy,
  invalid,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  /** The reasoning behind an ⓘ beside the label, so the hint stays one line. */
  info?: ReactNode;
  value: string;
  rows?: number;
  maxLength?: number;
  placeholder?: string;
  onChange: (v: string) => void;
  trackFocus: Track;
  /** The id of a line under the box that describes it, such as a counter. */
  describedBy?: string;
  invalid?: boolean;
  /** Shown under the box. */
  children?: ReactNode;
}) {
  return (
    <div>
      {info ? (
        <div className="flex items-center gap-1">
          <label className={FIELD_LABEL} htmlFor={id}>
            {label}
          </label>
          <InfoTip label={label} align="start">
            {info}
          </InfoTip>
        </div>
      ) : (
        <label className={FIELD_LABEL} htmlFor={id}>
          {label}
        </label>
      )}
      {hint && <span className={FIELD_HINT}>{hint}</span>}
      {rows === 1 ? (
        <input
          id={id}
          className={FIELD}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          aria-describedby={describedBy}
          aria-invalid={invalid}
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
          aria-describedby={describedBy}
          aria-invalid={invalid}
          onFocus={(e) => trackFocus(e.currentTarget)}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {children}
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
  trackFocus,
}: {
  script: CallScript;
  set: SetField;
  eg: ScriptExamples;
  trackFocus: Track;
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
        trackFocus={trackFocus}
      />
      <TextBox
        id="identity-text"
        label="Its role"
        value={script.identity}
        placeholder={`For example: ${eg.agentRole}`}
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
  eg,
  trackFocus,
}: {
  script: CallScript;
  set: SetField;
  direction: string;
  eg: ScriptExamples;
  trackFocus: Track;
}) {
  const calls = direction === "outbound" || direction === "both";
  return (
    <Section id="goal">
      <TextBox
        id="goal-text"
        label="The goal"
        value={script.goal}
        placeholder={`For example: ${eg.callGoal}`}
        onChange={(v) => set("goal", v)}
        trackFocus={trackFocus}
      />
      {calls && (
        <TextBox
          id="outbound-purpose"
          label="Why you are calling"
          hint="Said early on calls it places. Up to 300 letters."
          rows={1}
          maxLength={300}
          value={script.outbound_purpose}
          placeholder={`For example: ${eg.outboundPurpose}`}
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
  room,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: Track;
  /** How many characters the line may have after the notices switched on (D-846);
   *  undefined where nothing limits it. */
  room?: number;
}) {
  const over = room !== undefined && roomLabel(value, room).over;
  return (
    <Section id="opening">
      <TextBox
        id="opening-line"
        label="Opening line"
        hint="The first thing it says on every call."
        info="Any notices you have switched on are said just before this line, and together they have to be short enough to be said first."
        value={value}
        placeholder="For example: Namaskaram andi, cheppandi, em kavali?"
        onChange={onChange}
        trackFocus={trackFocus}
        describedBy={room !== undefined ? "opening-line-room" : undefined}
        invalid={over || undefined}
      >
        {room !== undefined && (
          <>
            <RoomCounter id="opening-line-room" text={value} room={room} />
            {over && (
              <p className="mt-1 text-xs text-ink-muted">
                Shorten it before you put it live, or it cannot be said first.
              </p>
            )}
          </>
        )}
      </TextBox>
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
  eg,
  trackFocus,
}: {
  style: SpeakingStyle;
  onChange: (style: SpeakingStyle) => void;
  context: ScriptContext | null;
  eg: ScriptExamples;
  trackFocus: Track;
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
                  className={`${FIELD} mt-0`}
                  aria-label={`Word ${i + 1}`}
                  value={word.word}
                  placeholder={eg.pronounceWord}
                  onFocus={(e) => trackFocus(e.currentTarget)}
                  onChange={(e) =>
                    setWords(style.pronunciations.map((w, j) => (j === i ? { ...w, word: e.target.value } : w)))
                  }
                />
                <input
                  className={`${FIELD} mt-0`}
                  aria-label={`Say word ${i + 1} as`}
                  value={word.say_as}
                  placeholder={eg.pronounceSayAs}
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
  eg,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  eg: ScriptExamples;
  trackFocus: Track;
}) {
  return (
    <Section id="ending">
      <TextBox
        id="ending-text"
        label="Ending"
        value={value}
        placeholder={`For example: ${eg.callEnding}`}
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
  direction,
  onInsert,
}: {
  standard: { key: string; label: string }[];
  custom: { key: string; label: string }[];
  /** The agent's calls: what fills a field differs, so the hint says which applies. */
  direction?: string;
  onInsert: (key: string) => void;
}) {
  const all = [...standard, ...custom.filter((c) => !standard.some((s) => s.key === c.key))];
  if (all.length === 0) return null;
  const answers = direction === "inbound" || direction === "both";
  const places = direction !== "inbound";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="flex items-center gap-1">
        <span className="text-meta text-ink-muted">Add a caller detail</span>
        <InfoTip label="these fields" align="start">
          It goes where your cursor was in the last box you typed in.
          {places && " On a call this agent places, it is filled from the lead."}
          {answers && " On a call it answers, it is filled only when the caller has called before."}
          {" "}When there is no value, it is left out and the sentence still reads.
        </InfoTip>
      </span>
      <div className="flex flex-wrap gap-2">
        {all.map((v) => (
          <button
            key={v.key}
            type="button"
            className="press inline-flex min-h-7 items-center gap-1 rounded-full border border-line px-2.5 text-meta text-ink hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
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
