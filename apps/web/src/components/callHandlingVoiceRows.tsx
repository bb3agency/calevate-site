"use client";

/**
 * THE CLIENT'S VOICE SETTINGS (F3, F9): what the agent does when the caller goes quiet, the
 * lines it says while it looks something up, and a background sound. Three rows shared by an
 * agent's Settings and the operator's console (an agent, and a client's defaults), beside the
 * pause and hang-up rows (`callHandlingRows`), in the same pattern: a `SettingRow` summary of
 * the value in force and where it comes from, "Change" opening a compact editor and the save
 * bar, and on an agent's Settings the "Just this agent" / "All my agents" choice.
 *
 * "Use the default" is a checkbox and saves `null`, so the value follows the level above. The
 * standard question and the standard lines are a choice of their own (saved as "" and []),
 * distinct from the default, because an organisation default may be the client's own words.
 * The server checks every range; the limits here come from its `bounds`, and each bounded
 * number is a slider between them, so a value the server would refuse cannot be entered.
 */

import { useState, type ReactNode } from "react";

import {
  CALL_HANDLING_EDITOR,
  CALL_HANDLING_NEXT_CALL,
  DefaultCheckbox,
  ScopeChoice,
  SliderField,
  type ScopeOffer,
} from "@/components/callHandlingRows";
import { type FeedbackStatus } from "@/components/arc/feedback";
import { SaveBar } from "@/components/console/saveBar";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { FieldMessage } from "@/components/formValidation";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import {
  AMBIENCE_LABELS,
  ambienceSummary,
  fillerSummary,
  formatSeconds,
  silenceSummary,
  timesLabel,
  inheritedVoice,
  platformVoice,
  rowSource,
  type AgentCallHandling,
  type AgentCallHandlingIn,
  type Ambience,
  type CallHandlingBounds,
  type CallHandlingScope,
  type InheritedVoice,
} from "@/lib/api/callHandling";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

interface Common {
  idPrefix: string;
  /** "Set for this agent", "Your organisation default", "Calevate default", or mixed; on an
   * account default, also the agents that do not follow it. */
  hint: ReactNode;
  bounds: CallHandlingBounds;
  /** What "use the default" resolves to, and whose default it is. */
  inherited: InheritedVoice;
  canChange: boolean;
  /** This row's save, from the caller's `useActionFeedback`. */
  status: FeedbackStatus;
  error: Error | null;
  /** On an agent's Settings, for a reader who may change every agent: "All my agents". */
  scope?: ScopeOffer<InheritedVoice>;
}

/** The scope choice at the foot of an editor, when "All my agents" is on offer. */
function ScopeField({
  id,
  offer,
  scope,
  onChange,
}: {
  id: string;
  offer: ScopeOffer<InheritedVoice> | undefined;
  scope: CallHandlingScope;
  onChange: (scope: CallHandlingScope) => void;
}) {
  if (!offer) return null;
  return (
    <div className={CALL_HANDLING_EDITOR}>
      <ScopeChoice id={id} scope={scope} others={offer.others} onChange={onChange} />
    </div>
  );
}

/** What "use the default" means for the scope picked: for every agent, Calevate's. */
function inheritedFor(
  scope: CallHandlingScope,
  offer: ScopeOffer<InheritedVoice> | undefined,
  agent: InheritedVoice,
): InheritedVoice {
  return scope === "all" && offer ? offer.inherit : agent;
}

const ALL_AGENTS_SAVE = "Save for all agents";

function ChangeButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={TEXT_ACTION}>
      Change
    </button>
  );
}

function Footer({
  changed,
  status,
  label,
  disabled,
  onClose,
}: {
  changed: boolean;
  status: FeedbackStatus;
  label: string;
  disabled?: boolean;
  onClose: () => void;
}) {
  if (changed || status === "pending") {
    return (
      <SaveBar
        label={label}
        status={status}
        disabled={disabled}
        onCancel={onClose}
        note={CALL_HANDLING_NEXT_CALL}
      />
    );
  }
  return (
    <button type="button" onClick={onClose} className={TEXT_ACTION}>
      Close
    </button>
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** A group of one editor, named by a visible legend. */
const LEGEND = "mb-2 text-sm font-semibold text-ink";

// --- if the caller goes quiet ------------------------------------------------------------

export interface SilenceValues {
  nudge_after_seconds: number | null;
  nudge_count: number | null;
  nudge_phrase: string | null;
  end_after_silence_seconds: number | null;
}

type AskPick = "after" | "never";
type PhrasePick = "standard" | "own";

const SILENCE_INFO =
  "When the caller says nothing for a while, the agent asks whether they are still there. " +
  "If the silence goes on, it puts the phone down, so a call nobody is on does not keep " +
  "running and being charged.";

/**
 * The waits are whole seconds, step 1: the Calevate default of 8 s is on no coarser grid that
 * starts at the 5 s minimum, and every whole second the server accepts stays reachable (arrow
 * keys move one at a time). The count is 1 to 5, so it is five segments, one tap each, rather
 * than a slider with five stops or a stepper that hides the other four values.
 */
export function SilenceRow({
  idPrefix,
  hint,
  bounds,
  inherited: agentInherited,
  canChange,
  status,
  error,
  scope,
  own,
  effective,
  onSave,
}: Common & {
  own: SilenceValues;
  effective: { nudge_after_seconds: number; nudge_count: number; nudge_phrase: string; end_after_silence_seconds: number };
  onSave: (next: SilenceValues, done: () => void, scope: CallHandlingScope) => void;
}) {
  // Unticking a default starts from that default's value, so nothing moves until changed.
  const initial = () => {
    const after = own.nudge_after_seconds ?? agentInherited.nudge_after_seconds;
    const phrase = own.nudge_phrase ?? agentInherited.nudge_phrase;
    const afterSeed = after > 0 ? after : effective.nudge_after_seconds || bounds.platform_nudge_after_seconds;
    return {
      askDefault: own.nudge_after_seconds === null,
      ask: (after === 0 ? "never" : "after") as AskPick,
      after: clamp(afterSeed, bounds.nudge_after_min_s, bounds.nudge_after_max_s),
      // `null` until the owner picks a number, so an untouched count keeps following.
      count: own.nudge_count,
      phraseDefault: own.nudge_phrase === null,
      phrase: (phrase === "" ? "standard" : "own") as PhrasePick,
      words: phrase,
      hangUpDefault: own.end_after_silence_seconds === null,
      hangUp: clamp(
        own.end_after_silence_seconds ?? agentInherited.end_after_silence_seconds,
        bounds.end_after_silence_min_s,
        bounds.end_after_silence_max_s,
      ),
      scope: "agent" as CallHandlingScope,
    };
  };
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const set = (patch: Partial<ReturnType<typeof initial>>) => setForm((f) => ({ ...f, ...patch }));

  const words = form.words.trim();
  const wordsValid = words.length > 0 && words.length <= bounds.nudge_phrase_max_chars;
  const ownWords = !form.phraseDefault && form.phrase === "own";
  const valid = !ownWords || wordsValid;
  const next: SilenceValues = {
    nudge_after_seconds: form.askDefault ? null : form.ask === "never" ? 0 : form.after,
    nudge_count: form.count,
    nudge_phrase: form.phraseDefault ? null : form.phrase === "standard" ? "" : words,
    end_after_silence_seconds: form.hangUpDefault ? null : form.hangUp,
  };
  const changed =
    editing &&
    (form.scope === "all" ||
      next.nudge_after_seconds !== own.nudge_after_seconds ||
      next.nudge_count !== own.nudge_count ||
      next.nudge_phrase !== own.nudge_phrase ||
      next.end_after_silence_seconds !== own.end_after_silence_seconds);
  useUnsavedGuard(changed);
  const inherited = inheritedFor(form.scope, scope, agentInherited);
  const id = `${idPrefix}-silence`;
  const close = () => {
    setEditing(false);
    setForm(initial());
  };
  const inheritedAsk =
    inherited.nudge_after_seconds === 0 ? "never asks" : `asks after ${formatSeconds(inherited.nudge_after_seconds)}`;
  const asks = form.askDefault ? inherited.nudge_after_seconds !== 0 : form.ask === "after";
  const count = form.count ?? inherited.nudge_count;

  return (
    <div>
      <SettingRow
        label="If the caller goes quiet"
        hint={hint}
        info={<p>{SILENCE_INFO}</p>}
        value={silenceSummary(
          effective.nudge_after_seconds,
          effective.nudge_count,
          effective.end_after_silence_seconds,
        )}
        action={
          editing || !canChange ? undefined : (
            <ChangeButton
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
            />
          )
        }
      />
      {effective.nudge_phrase !== "" && (
        <p className="pb-3 text-meta text-ink-muted">Asks in your own words.</p>
      )}
      {error && <ProblemNotice error={error} />}
      {editing && (
        <form
          className="settings-enter space-y-5 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid) return;
            onSave(next, () => setEditing(false), form.scope);
          }}
        >
          <fieldset className={CALL_HANDLING_EDITOR}>
            <legend className={LEGEND}>Ask whether they are still there</legend>
            <DefaultCheckbox
              label={`Use the ${inherited.from.nudge_after_seconds}: ${inheritedAsk}`}
              checked={form.askDefault}
              onChange={(checked) => set({ askDefault: checked })}
            />
            {!form.askDefault && (
              <div>
                <SegmentedControl
                  label="When to ask"
                  options={[
                    { value: "after", label: "After a set time" },
                    { value: "never", label: "Never ask" },
                  ]}
                  value={form.ask}
                  onValueChange={(value) => set({ ask: value as AskPick })}
                />
                {form.ask === "never" && (
                  <p className={FIELD_HINT}>The agent waits without asking.</p>
                )}
              </div>
            )}
            {!form.askDefault && form.ask === "after" && (
              <>
                <SliderField
                  id={`${id}-after`}
                  label="Quiet before asking"
                  value={form.after}
                  valueText={formatSeconds(form.after)}
                  min={bounds.nudge_after_min_s}
                  max={bounds.nudge_after_max_s}
                  step={1}
                  scale={[formatSeconds(bounds.nudge_after_min_s), formatSeconds(bounds.nudge_after_max_s)]}
                  onChange={(after) => set({ after })}
                />
                <div>
                  <p className={FIELD_LABEL} aria-hidden>
                    How many times
                  </p>
                  <SegmentedControl
                    label="How many times"
                    className="mt-1.5"
                    options={Array.from(
                      { length: bounds.nudge_count_max - bounds.nudge_count_min + 1 },
                      (_, i) => {
                        const n = bounds.nudge_count_min + i;
                        return { value: String(n), label: String(n) };
                      },
                    )}
                    value={String(count)}
                    onValueChange={(value) => set({ count: Number(value) })}
                  />
                  <p className={FIELD_HINT}>{`Asks ${timesLabel(count)}, then hangs up if the silence goes on.`}</p>
                </div>
              </>
            )}
          </fieldset>
          {asks && (
            <fieldset className={CALL_HANDLING_EDITOR}>
              <legend className={LEGEND}>What the agent asks</legend>
              <DefaultCheckbox
                label={`Use the ${inherited.from.nudge_phrase}: ${inherited.nudge_phrase === "" ? "the standard question" : "your own words"}`}
                checked={form.phraseDefault}
                onChange={(checked) => set({ phraseDefault: checked })}
              />
              {!form.phraseDefault && (
                <div>
                  <SegmentedControl
                    label="What the agent asks"
                    options={[
                      { value: "standard", label: "Standard question" },
                      { value: "own", label: "Our own words" },
                    ]}
                    value={form.phrase}
                    onValueChange={(value) => set({ phrase: value as PhrasePick })}
                  />
                  {form.phrase === "standard" && (
                    <p className={FIELD_HINT}>Asked in the caller&apos;s language.</p>
                  )}
                </div>
              )}
              {ownWords && (
                <div className="flex flex-col gap-1">
                  <label htmlFor={`${id}-words`} className={FIELD_LABEL}>
                    The question
                  </label>
                  <input
                    id={`${id}-words`}
                    type="text"
                    maxLength={bounds.nudge_phrase_max_chars}
                    value={form.words}
                    onChange={(event) => set({ words: event.target.value })}
                    placeholder="Hello, are you still there?"
                    className={FIELD}
                    aria-invalid={!wordsValid ? true : undefined}
                    aria-describedby={`${id}-words-count`}
                  />
                  <span id={`${id}-words-count`} className="text-xs text-ink-muted tabular-nums">
                    {`${words.length} of ${bounds.nudge_phrase_max_chars} characters`}
                  </span>
                </div>
              )}
            </fieldset>
          )}
          <fieldset className={CALL_HANDLING_EDITOR}>
            <legend className={LEGEND}>Hang up after silence</legend>
            <DefaultCheckbox
              label={`Use the ${inherited.from.end_after_silence_seconds}: hangs up after ${formatSeconds(inherited.end_after_silence_seconds)}`}
              checked={form.hangUpDefault}
              onChange={(checked) => set({ hangUpDefault: checked })}
            />
            {!form.hangUpDefault && (
              <SliderField
                id={`${id}-hang-up`}
                label="Silence before hanging up"
                value={form.hangUp}
                valueText={formatSeconds(form.hangUp)}
                min={bounds.end_after_silence_min_s}
                max={bounds.end_after_silence_max_s}
                step={1}
                scale={[
                  formatSeconds(bounds.end_after_silence_min_s),
                  formatSeconds(bounds.end_after_silence_max_s),
                ]}
                onChange={(hangUp) => set({ hangUp })}
              />
            )}
          </fieldset>
          <ScopeField id={id} offer={scope} scope={form.scope} onChange={(picked) => set({ scope: picked })} />
          <Footer
            changed={changed}
            status={status}
            label={form.scope === "all" ? ALL_AGENTS_SAVE : "Save"}
            disabled={!valid}
            onClose={close}
          />
        </form>
      )}
    </div>
  );
}

// --- lines said while the agent looks something up ------------------------------------------

type LinesPick = "standard" | "own";

export function FillerLinesRow({
  idPrefix,
  hint,
  bounds,
  inherited: agentInherited,
  canChange,
  status,
  error,
  scope,
  own,
  effective,
  onSave,
}: Common & {
  own: string[] | null;
  effective: string[];
  onSave: (next: string[] | null, done: () => void, scope: CallHandlingScope) => void;
}) {
  const initial = () => {
    const base = own ?? agentInherited.filler_lines;
    return {
      useDefault: own === null,
      pick: (base.length === 0 ? "standard" : "own") as LinesPick,
      text: base.join("\n"),
      scope: "agent" as CallHandlingScope,
    };
  };
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const lines = form.text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  const ownLines = !form.useDefault && form.pick === "own";
  const tooMany = lines.length > bounds.filler_lines_max;
  const tooLong = lines.find((line) => line.length > bounds.filler_line_max_chars);
  const valid = !ownLines || (lines.length > 0 && !tooMany && tooLong === undefined);
  const next: string[] | null = form.useDefault ? null : form.pick === "standard" ? [] : lines;
  const changed =
    editing && (form.scope === "all" || JSON.stringify(next) !== JSON.stringify(own));
  useUnsavedGuard(changed);
  const inherited = inheritedFor(form.scope, scope, agentInherited);
  const id = `${idPrefix}-filler`;
  const close = () => {
    setEditing(false);
    setForm(initial());
  };
  const inheritedSummary = fillerSummary(inherited.filler_lines);

  return (
    <div>
      <SettingRow
        label="Lines the agent says while it looks something up"
        hint={hint}
        info={
          <p>
            While the agent checks something, such as a detail about your business, it
            says a short line so the caller is not left in silence. Use the standard lines, in
            the caller&apos;s language, or write your own.
          </p>
        }
        value={fillerSummary(effective)}
        action={
          editing || !canChange ? undefined : (
            <ChangeButton
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
            />
          )
        }
      />
      {error && <ProblemNotice error={error} />}
      {editing && (
        <form
          className="settings-enter space-y-3 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid) return;
            onSave(next, () => setEditing(false), form.scope);
          }}
        >
          <div className={CALL_HANDLING_EDITOR}>
            <DefaultCheckbox
              label={`Use the ${inherited.from.filler_lines}: ${inheritedSummary.charAt(0).toLowerCase()}${inheritedSummary.slice(1)}`}
              checked={form.useDefault}
              onChange={(checked) => setForm((f) => ({ ...f, useDefault: checked }))}
            />
            {!form.useDefault && (
              <div>
                <SegmentedControl
                  label="Lines the agent says while it looks something up"
                  options={[
                    { value: "standard", label: "Standard lines" },
                    { value: "own", label: "Our own lines" },
                  ]}
                  value={form.pick}
                  onValueChange={(value) => setForm((f) => ({ ...f, pick: value as LinesPick }))}
                />
                {form.pick === "standard" && (
                  <p className={FIELD_HINT}>Short lines in the caller&apos;s language.</p>
                )}
              </div>
            )}
            {ownLines && (
              <div className="flex flex-col gap-1">
                <label htmlFor={`${id}-lines`} className={FIELD_LABEL}>
                  {`One line per row: up to ${bounds.filler_lines_max} lines of ${bounds.filler_line_max_chars} characters`}
                </label>
                <textarea
                  id={`${id}-lines`}
                  rows={Math.min(Math.max(lines.length + 1, 3), bounds.filler_lines_max)}
                  value={form.text}
                  onChange={(event) => setForm((f) => ({ ...f, text: event.target.value }))}
                  placeholder={"One moment please.\nLet me check that for you."}
                  className={FIELD}
                  aria-invalid={!valid ? true : undefined}
                  aria-describedby={`${id}-lines-help`}
                />
                <span id={`${id}-lines-help`} className="text-xs text-ink-muted tabular-nums">
                  {`${lines.length} of ${bounds.filler_lines_max} lines`}
                </span>
                {tooMany && (
                  <FieldMessage id={`${id}-lines-many`}>
                    {`Keep ${bounds.filler_lines_max} lines or fewer.`}
                  </FieldMessage>
                )}
                {tooLong !== undefined && (
                  <FieldMessage id={`${id}-lines-long`}>
                    {`Each line can be up to ${bounds.filler_line_max_chars} characters.`}
                  </FieldMessage>
                )}
              </div>
            )}
          </div>
          <ScopeField
            id={id}
            offer={scope}
            scope={form.scope}
            onChange={(picked) => setForm((f) => ({ ...f, scope: picked }))}
          />
          <Footer
            changed={changed}
            status={status}
            label={form.scope === "all" ? ALL_AGENTS_SAVE : "Save lines"}
            disabled={!valid}
            onClose={close}
          />
        </form>
      )}
    </div>
  );
}

// --- background sound --------------------------------------------------------------------

export interface SoundValues {
  ambience: Ambience | null;
  ambience_volume_pct: number | null;
}

type SoundChoice = "inherit" | Ambience;

/** Quietest first, so the control reads as a scale. */
const SOUND_ORDER: readonly Ambience[] = ["off", "office-quiet", "office"];

const SOUND_HINTS: Record<Ambience, string> = {
  off: "Silence behind the voice. Quiet between replies.",
  "office-quiet": "A soft office sound, so the line is never dead.",
  office: "A fuller office sound behind the voice.",
};

export function BackgroundSoundRow({
  idPrefix,
  hint,
  bounds,
  inherited: agentInherited,
  canChange,
  status,
  error,
  scope,
  own,
  effective,
  onSave,
}: Common & {
  own: SoundValues;
  effective: { ambience: Ambience; ambience_volume_pct: number };
  onSave: (next: SoundValues, done: () => void, scope: CallHandlingScope) => void;
}) {
  const initial = () => ({
    choice: (own.ambience ?? "inherit") as SoundChoice,
    volume: clamp(
      own.ambience_volume_pct ?? effective.ambience_volume_pct,
      bounds.ambience_volume_min_pct,
      bounds.ambience_volume_max_pct,
    ),
    scope: "agent" as CallHandlingScope,
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const audible = form.choice === "office" || form.choice === "office-quiet";
  const next: SoundValues =
    form.choice === "inherit"
      ? { ambience: null, ambience_volume_pct: null }
      : { ambience: form.choice, ambience_volume_pct: audible ? form.volume : own.ambience_volume_pct };
  const changed =
    editing &&
    (form.scope === "all" ||
      next.ambience !== own.ambience ||
      next.ambience_volume_pct !== own.ambience_volume_pct);
  useUnsavedGuard(changed);
  const inherited = inheritedFor(form.scope, scope, agentInherited);
  const id = `${idPrefix}-sound`;
  const close = () => {
    setEditing(false);
    setForm(initial());
  };

  return (
    <div>
      <SettingRow
        label="Background sound"
        hint={hint}
        info={
          <p>
            A quiet office sound behind the agent&apos;s voice, so the call sounds like it comes
            from a busy front desk. Off by default.
          </p>
        }
        value={ambienceSummary(effective.ambience, effective.ambience_volume_pct)}
        action={
          editing || !canChange ? undefined : (
            <ChangeButton
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
            />
          )
        }
      />
      {error && <ProblemNotice error={error} />}
      {editing && (
        <form
          className="settings-enter space-y-3 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            onSave(next, () => setEditing(false), form.scope);
          }}
        >
          <div className={CALL_HANDLING_EDITOR}>
            <DefaultCheckbox
              label={`Use the ${inherited.from.ambience}: ${ambienceSummary(inherited.ambience, inherited.ambience_volume_pct)}`}
              checked={form.choice === "inherit"}
              onChange={(checked) =>
                setForm((f) => ({ ...f, choice: checked ? "inherit" : inherited.ambience }))
              }
            />
            {form.choice !== "inherit" && (
              <div>
                <SegmentedControl
                  label="Background sound"
                  options={SOUND_ORDER.filter((a) => bounds.ambiences.includes(a)).map((a) => ({
                    value: a,
                    label: AMBIENCE_LABELS[a],
                  }))}
                  value={form.choice}
                  onValueChange={(value) => setForm((f) => ({ ...f, choice: value as Ambience }))}
                />
                <p className={FIELD_HINT}>{SOUND_HINTS[form.choice]}</p>
              </div>
            )}
            {audible && (
              <SliderField
                id={`${id}-volume`}
                label="Volume"
                value={form.volume}
                valueText={`${form.volume}%`}
                min={bounds.ambience_volume_min_pct}
                max={bounds.ambience_volume_max_pct}
                step={1}
                scale={["Faint", "As loud as the voice"]}
                onChange={(volume) => setForm((f) => ({ ...f, volume }))}
              />
            )}
          </div>
          <ScopeField
            id={id}
            offer={scope}
            scope={form.scope}
            onChange={(picked) => setForm((f) => ({ ...f, scope: picked }))}
          />
          <Footer
            changed={changed}
            status={status}
            label={form.scope === "all" ? ALL_AGENTS_SAVE : "Save sound"}
            onClose={close}
          />
        </form>
      )}
    </div>
  );
}

// --- one agent's three rows ------------------------------------------------------------------

export type VoiceRow = "silence" | "filler" | "sound";

/** The three rows for one agent, from its call handling read; used by the client's agent
 * Settings and the operator's console, each with its own save. */
export function AgentVoiceRows({
  idPrefix,
  data,
  canChange,
  onSave,
  error,
  status,
  others,
}: {
  idPrefix: string;
  data: AgentCallHandling;
  canChange: boolean;
  onSave: (payload: AgentCallHandlingIn, done: () => void, scope: CallHandlingScope) => void;
  /** The last save's refusal, shown on the row that saved. */
  error: Error | null;
  /** The caller's `useActionFeedback` status, shown on the row that saved. */
  status: FeedbackStatus;
  /** Per row, the other agents with their own value; given only when "All my agents" is on
   * offer to this reader. */
  others?: Record<VoiceRow, number>;
}) {
  const [row, setRow] = useState<VoiceRow | null>(null);
  const inherited = inheritedVoice(data);
  const calevate = platformVoice(data.bounds);
  const offer = (which: VoiceRow): ScopeOffer<InheritedVoice> | undefined =>
    others ? { others: others[which], inherit: calevate } : undefined;
  const send = (
    which: VoiceRow,
    payload: AgentCallHandlingIn,
    done: () => void,
    scope: CallHandlingScope,
  ) => {
    setRow(which);
    onSave(payload, done, scope);
  };
  const rowStatus = (which: VoiceRow): FeedbackStatus => (row === which ? status : "idle");
  const failed = (which: VoiceRow) => (row === which ? error : null);
  return (
    <>
      <SilenceRow
        idPrefix={idPrefix}
        hint={rowSource([
          data.nudge_after_seconds_source,
          data.nudge_count_source,
          data.nudge_phrase_source,
          data.end_after_silence_seconds_source,
        ])}
        bounds={data.bounds}
        inherited={inherited}
        canChange={canChange}
        status={rowStatus("silence")}
        error={failed("silence")}
        own={{
          nudge_after_seconds: data.nudge_after_seconds,
          nudge_count: data.nudge_count,
          nudge_phrase: data.nudge_phrase,
          end_after_silence_seconds: data.end_after_silence_seconds,
        }}
        effective={{
          nudge_after_seconds: data.nudge_after_seconds_effective,
          nudge_count: data.nudge_count_effective,
          nudge_phrase: data.nudge_phrase_effective,
          end_after_silence_seconds: data.end_after_silence_seconds_effective,
        }}
        scope={offer("silence")}
        onSave={(next, done, scope) => send("silence", next, done, scope)}
      />
      <FillerLinesRow
        idPrefix={idPrefix}
        hint={rowSource([data.filler_lines_source])}
        bounds={data.bounds}
        inherited={inherited}
        canChange={canChange}
        status={rowStatus("filler")}
        error={failed("filler")}
        own={data.filler_lines}
        effective={data.filler_lines_effective}
        scope={offer("filler")}
        onSave={(next, done, scope) => send("filler", { filler_lines: next }, done, scope)}
      />
      <BackgroundSoundRow
        idPrefix={idPrefix}
        hint={rowSource([data.ambience_source, data.ambience_volume_pct_source])}
        bounds={data.bounds}
        inherited={inherited}
        canChange={canChange}
        status={rowStatus("sound")}
        error={failed("sound")}
        own={{ ambience: data.ambience, ambience_volume_pct: data.ambience_volume_pct }}
        effective={{
          ambience: data.ambience_effective,
          ambience_volume_pct: data.ambience_volume_pct_effective,
        }}
        scope={offer("sound")}
        onSave={(next, done, scope) => send("sound", next, done, scope)}
      />
    </>
  );
}
