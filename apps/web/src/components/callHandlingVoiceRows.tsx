"use client";

/**
 * THE CLIENT'S VOICE SETTINGS (F3, F9): what the agent does when the caller goes quiet, the
 * lines it says while it looks something up, and a background sound. Three rows shared by an
 * agent's Call handling, the organisation's default and the operator's console, beside the
 * pause and hang-up rows (`callHandlingRows`), in the same pattern: a `SettingRow` summary of
 * the value in force and where it comes from, "Change" opening a compact editor and the save
 * bar.
 *
 * "Use the default" is a checkbox and saves `null`, so the value follows the level above. The
 * standard question and the standard lines are a choice of their own (saved as "" and []),
 * distinct from the default, because an organisation default may be the client's own words.
 * The server checks every range; the limits here come from its `bounds`, and each bounded
 * number is a slider between them, so a value the server would refuse cannot be entered.
 */

import type { UseMutationResult } from "@tanstack/react-query";
import { useState } from "react";

import {
  CALL_HANDLING_EDITOR,
  CALL_HANDLING_NEXT_CALL,
  DefaultCheckbox,
  SliderField,
} from "@/components/callHandlingRows";
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
  rowSource,
  type AgentCallHandling,
  type AgentCallHandlingIn,
  type Ambience,
  type CallHandlingBounds,
  type InheritedVoice,
} from "@/lib/api/callHandling";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

interface Common {
  idPrefix: string;
  /** "Set for this agent", "Your organisation default", "Calevate default", or mixed. */
  hint: string;
  bounds: CallHandlingBounds;
  /** What "use the default" resolves to, and whose default it is. */
  inherited: InheritedVoice;
  canChange: boolean;
  saving: boolean;
  error: Error | null;
}

function ChangeButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={TEXT_ACTION}>
      Change
    </button>
  );
}

function Footer({
  changed,
  saving,
  label,
  disabled,
  onClose,
}: {
  changed: boolean;
  saving: boolean;
  label: string;
  disabled?: boolean;
  onClose: () => void;
}) {
  if (changed || saving) {
    return (
      <SaveBar
        label={label}
        saving={saving}
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
  inherited,
  canChange,
  saving,
  error,
  own,
  effective,
  onSave,
}: Common & {
  own: SilenceValues;
  effective: { nudge_after_seconds: number; nudge_count: number; nudge_phrase: string; end_after_silence_seconds: number };
  onSave: (next: SilenceValues, done: () => void) => void;
}) {
  // Unticking a default starts from that default's value, so nothing moves until changed.
  const initial = () => {
    const after = own.nudge_after_seconds ?? inherited.nudge_after_seconds;
    const phrase = own.nudge_phrase ?? inherited.nudge_phrase;
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
        own.end_after_silence_seconds ?? inherited.end_after_silence_seconds,
        bounds.end_after_silence_min_s,
        bounds.end_after_silence_max_s,
      ),
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
    (next.nudge_after_seconds !== own.nudge_after_seconds ||
      next.nudge_count !== own.nudge_count ||
      next.nudge_phrase !== own.nudge_phrase ||
      next.end_after_silence_seconds !== own.end_after_silence_seconds);
  useUnsavedGuard(changed);
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
            onSave(next, () => setEditing(false));
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
                label={`Use the ${inherited.from.nudge_phrase}: ${inherited.nudge_phrase === "" ? "the standard question" : "your organisation's words"}`}
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
          <Footer changed={changed} saving={saving} label="Save" disabled={!valid} onClose={close} />
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
  inherited,
  canChange,
  saving,
  error,
  own,
  effective,
  onSave,
}: Common & {
  own: string[] | null;
  effective: string[];
  onSave: (next: string[] | null, done: () => void) => void;
}) {
  const initial = () => {
    const base = own ?? inherited.filler_lines;
    return {
      useDefault: own === null,
      pick: (base.length === 0 ? "standard" : "own") as LinesPick,
      text: base.join("\n"),
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
  const changed = editing && JSON.stringify(next) !== JSON.stringify(own);
  useUnsavedGuard(changed);
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
            onSave(next, () => setEditing(false));
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
          <Footer changed={changed} saving={saving} label="Save lines" disabled={!valid} onClose={close} />
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
  off: "Silence behind the agent's voice, so the line goes quiet between replies.",
  "office-quiet": "A soft office sound behind the voice, so the line never drops to dead silence.",
  office: "A fuller office sound behind the voice.",
};

export function BackgroundSoundRow({
  idPrefix,
  hint,
  bounds,
  inherited,
  canChange,
  saving,
  error,
  own,
  effective,
  onSave,
}: Common & {
  own: SoundValues;
  effective: { ambience: Ambience; ambience_volume_pct: number };
  onSave: (next: SoundValues, done: () => void) => void;
}) {
  const initial = () => ({
    choice: (own.ambience ?? "inherit") as SoundChoice,
    volume: clamp(
      own.ambience_volume_pct ?? effective.ambience_volume_pct,
      bounds.ambience_volume_min_pct,
      bounds.ambience_volume_max_pct,
    ),
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const audible = form.choice === "office" || form.choice === "office-quiet";
  const next: SoundValues =
    form.choice === "inherit"
      ? { ambience: null, ambience_volume_pct: null }
      : { ambience: form.choice, ambience_volume_pct: audible ? form.volume : own.ambience_volume_pct };
  const changed =
    editing && (next.ambience !== own.ambience || next.ambience_volume_pct !== own.ambience_volume_pct);
  useUnsavedGuard(changed);
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
            onSave(next, () => setEditing(false));
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
          <Footer changed={changed} saving={saving} label="Save sound" onClose={close} />
        </form>
      )}
    </div>
  );
}

// --- one agent's three rows ------------------------------------------------------------------

type VoiceRow = "silence" | "filler" | "sound";

/** The three rows for one agent, from its call handling read; used by the client's Call
 * handling and the operator's console, each with its own save. */
export function AgentVoiceRows({
  idPrefix,
  data,
  canChange,
  save,
}: {
  idPrefix: string;
  data: AgentCallHandling;
  canChange: boolean;
  save: UseMutationResult<AgentCallHandling, Error, AgentCallHandlingIn>;
}) {
  const [row, setRow] = useState<VoiceRow | null>(null);
  const inherited = inheritedVoice(data);
  const send = (which: VoiceRow, payload: AgentCallHandlingIn, done: () => void) => {
    setRow(which);
    save.mutate(payload, { onSuccess: done });
  };
  const busy = (which: VoiceRow) => save.isPending && row === which;
  const failed = (which: VoiceRow) => (row === which ? save.error : null);
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
        saving={busy("silence")}
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
        onSave={(next, done) => send("silence", next, done)}
      />
      <FillerLinesRow
        idPrefix={idPrefix}
        hint={rowSource([data.filler_lines_source])}
        bounds={data.bounds}
        inherited={inherited}
        canChange={canChange}
        saving={busy("filler")}
        error={failed("filler")}
        own={data.filler_lines}
        effective={data.filler_lines_effective}
        onSave={(next, done) => send("filler", { filler_lines: next }, done)}
      />
      <BackgroundSoundRow
        idPrefix={idPrefix}
        hint={rowSource([data.ambience_source, data.ambience_volume_pct_source])}
        bounds={data.bounds}
        inherited={inherited}
        canChange={canChange}
        saving={busy("sound")}
        error={failed("sound")}
        own={{ ambience: data.ambience, ambience_volume_pct: data.ambience_volume_pct }}
        effective={{
          ambience: data.ambience_effective,
          ambience_volume_pct: data.ambience_volume_pct_effective,
        }}
        onSave={(next, done) => send("sound", next, done)}
      />
    </>
  );
}
