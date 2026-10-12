"use client";

/**
 * THE CLIENT'S VOICE SETTINGS (F3, F9): what the agent does when the caller goes quiet, the
 * lines it says while it looks something up, and a background sound. Three rows shared by an
 * agent's Call handling, the organisation's default and the operator's console, beside the
 * pause and hang-up rows (`callHandlingRows`), in the same pattern: a `SettingRow` summary of
 * the value in force and where it comes from, "Change" opening choice cards and the save bar.
 *
 * "Use the default" saves `null`, so the value follows the level above. The standard question
 * and the standard lines are a choice of their own (saved as "" and []), distinct from the
 * default, because an organisation default may be the client's own words. The server checks
 * every range; the limits shown here come from its `bounds`.
 */

import type { UseMutationResult } from "@tanstack/react-query";
import { useState } from "react";

import { CALL_HANDLING_NEXT_CALL, CallHandlingCard } from "@/components/callHandlingRows";
import { SaveBar } from "@/components/console/saveBar";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { FieldMessage } from "@/components/formValidation";
import { FIELD, FIELD_INLINE, ProblemNotice } from "@/components/ui";
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

function wholeIn(raw: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(raw.trim())) return null;
  const value = Number(raw);
  return value >= min && value <= max ? value : null;
}

// --- if the caller goes quiet ------------------------------------------------------------

export interface SilenceValues {
  nudge_after_seconds: number | null;
  nudge_count: number | null;
  nudge_phrase: string | null;
  end_after_silence_seconds: number | null;
}

type AskChoice = "inherit" | "never" | "after";
type PhraseChoice = "inherit" | "standard" | "own";

const SILENCE_INFO =
  "When the caller says nothing for a while, the agent asks whether they are still there. " +
  "If the silence goes on, it puts the phone down, so a call nobody is on does not keep " +
  "running and being charged.";

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
  const initial = () => ({
    ask: (own.nudge_after_seconds === null ? "inherit" : own.nudge_after_seconds === 0 ? "never" : "after") as AskChoice,
    after: String(own.nudge_after_seconds && own.nudge_after_seconds > 0 ? own.nudge_after_seconds : effective.nudge_after_seconds || bounds.platform_nudge_after_seconds),
    count: own.nudge_count === null ? "inherit" : String(own.nudge_count),
    phrase: (own.nudge_phrase === null ? "inherit" : own.nudge_phrase === "" ? "standard" : "own") as PhraseChoice,
    words: own.nudge_phrase ?? "",
    hangUp: own.end_after_silence_seconds === null ? "" : String(own.end_after_silence_seconds),
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));

  const afterValue = wholeIn(form.after, bounds.nudge_after_min_s, bounds.nudge_after_max_s);
  const hangUpValue =
    form.hangUp.trim() === ""
      ? null
      : wholeIn(form.hangUp, bounds.end_after_silence_min_s, bounds.end_after_silence_max_s);
  const words = form.words.trim();
  const wordsValid = words.length > 0 && words.length <= bounds.nudge_phrase_max_chars;
  const valid =
    (form.ask !== "after" || afterValue !== null) &&
    (form.hangUp.trim() === "" || hangUpValue !== null) &&
    (form.phrase !== "own" || wordsValid);
  const next: SilenceValues = {
    nudge_after_seconds: form.ask === "inherit" ? null : form.ask === "never" ? 0 : afterValue,
    nudge_count: form.count === "inherit" ? null : Number(form.count),
    nudge_phrase: form.phrase === "inherit" ? null : form.phrase === "standard" ? "" : words,
    end_after_silence_seconds: hangUpValue,
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
          className="settings-enter space-y-4 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid) return;
            onSave(next, () => setEditing(false));
          }}
        >
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-ink">Ask whether they are still there</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              <CallHandlingCard
                name={`${id}-ask`}
                checked={form.ask === "inherit"}
                onSelect={() => set({ ask: "inherit" })}
                label={`${inherited.from.nudge_after_seconds} (${inheritedAsk})`}
              />
              <CallHandlingCard
                name={`${id}-ask`}
                checked={form.ask === "after"}
                onSelect={() => set({ ask: "after" })}
                label="After a set time"
                hint={`${bounds.nudge_after_min_s} to ${bounds.nudge_after_max_s} seconds of quiet.`}
              />
              <CallHandlingCard
                name={`${id}-ask`}
                checked={form.ask === "never"}
                onSelect={() => set({ ask: "never" })}
                label="Never ask"
                hint="The agent waits without asking."
              />
            </div>
          </fieldset>
          {form.ask === "after" && (
            <div className="flex flex-wrap gap-4">
              <div className="flex flex-col gap-1">
                <label htmlFor={`${id}-after`} className="text-xs text-ink-muted">
                  Seconds of quiet before asking
                </label>
                <input
                  id={`${id}-after`}
                  type="number"
                  inputMode="numeric"
                  min={bounds.nudge_after_min_s}
                  max={bounds.nudge_after_max_s}
                  value={form.after}
                  onChange={(event) => set({ after: event.target.value })}
                  className={`w-28 tabular-nums ${FIELD_INLINE}`}
                  aria-invalid={afterValue === null ? true : undefined}
                  aria-describedby={afterValue === null ? `${id}-after-error` : undefined}
                />
                {afterValue === null && (
                  <FieldMessage id={`${id}-after-error`}>
                    {`Enter ${bounds.nudge_after_min_s} to ${bounds.nudge_after_max_s} seconds.`}
                  </FieldMessage>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={`${id}-count`} className="text-xs text-ink-muted">
                  How many times
                </label>
                <select
                  id={`${id}-count`}
                  value={form.count}
                  onChange={(event) => set({ count: event.target.value })}
                  className={FIELD_INLINE}
                >
                  <option value="inherit">{`${inherited.from.nudge_count} (${timesLabel(inherited.nudge_count)})`}</option>
                  {Array.from(
                    { length: bounds.nudge_count_max - bounds.nudge_count_min + 1 },
                    (_, i) => bounds.nudge_count_min + i,
                  ).map((n) => (
                    <option key={n} value={String(n)}>
                      {timesLabel(n)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
          {form.ask !== "never" && (
            <fieldset>
              <legend className="mb-2 text-sm font-semibold text-ink">What the agent asks</legend>
              <div className="grid gap-2 sm:grid-cols-3">
                <CallHandlingCard
                  name={`${id}-phrase`}
                  checked={form.phrase === "inherit"}
                  onSelect={() => set({ phrase: "inherit" })}
                  label={inherited.from.nudge_phrase}
                  hint={inherited.nudge_phrase === "" ? "The standard question." : "Your organisation's words."}
                />
                <CallHandlingCard
                  name={`${id}-phrase`}
                  checked={form.phrase === "standard"}
                  onSelect={() => set({ phrase: "standard" })}
                  label="The standard question"
                  hint="Asked in the caller's language."
                />
                <CallHandlingCard
                  name={`${id}-phrase`}
                  checked={form.phrase === "own"}
                  onSelect={() => set({ phrase: "own" })}
                  label="In our own words"
                />
              </div>
              {form.phrase === "own" && (
                <div className="mt-2 flex flex-col gap-1">
                  <label htmlFor={`${id}-words`} className="text-xs text-ink-muted">
                    {`The question, up to ${bounds.nudge_phrase_max_chars} characters`}
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
                    {`${words.length} of ${bounds.nudge_phrase_max_chars}`}
                  </span>
                </div>
              )}
            </fieldset>
          )}
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-hang-up`} className="text-xs text-ink-muted">
              {`Hang up after this many seconds of silence (empty: ${inherited.from.end_after_silence_seconds}, ${formatSeconds(inherited.end_after_silence_seconds)})`}
            </label>
            <input
              id={`${id}-hang-up`}
              type="number"
              inputMode="numeric"
              min={bounds.end_after_silence_min_s}
              max={bounds.end_after_silence_max_s}
              value={form.hangUp}
              onChange={(event) => set({ hangUp: event.target.value })}
              className={`w-28 tabular-nums ${FIELD_INLINE}`}
              aria-invalid={form.hangUp.trim() !== "" && hangUpValue === null ? true : undefined}
              aria-describedby={
                form.hangUp.trim() !== "" && hangUpValue === null ? `${id}-hang-up-error` : undefined
              }
            />
            {form.hangUp.trim() !== "" && hangUpValue === null && (
              <FieldMessage id={`${id}-hang-up-error`}>
                {`Enter ${bounds.end_after_silence_min_s} to ${bounds.end_after_silence_max_s} seconds, or leave it empty.`}
              </FieldMessage>
            )}
          </div>
          <Footer changed={changed} saving={saving} label="Save" disabled={!valid} onClose={close} />
        </form>
      )}
    </div>
  );
}

// --- lines said while the agent looks something up ------------------------------------------

type LinesChoice = "inherit" | "standard" | "own";

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
  const initial = () => ({
    choice: (own === null ? "inherit" : own.length === 0 ? "standard" : "own") as LinesChoice,
    text: (own ?? []).join("\n"),
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const lines = form.text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  const tooMany = lines.length > bounds.filler_lines_max;
  const tooLong = lines.find((line) => line.length > bounds.filler_line_max_chars);
  const valid = form.choice !== "own" || (lines.length > 0 && !tooMany && tooLong === undefined);
  const next: string[] | null =
    form.choice === "inherit" ? null : form.choice === "standard" ? [] : lines;
  const changed = editing && JSON.stringify(next) !== JSON.stringify(own);
  useUnsavedGuard(changed);
  const id = `${idPrefix}-filler`;
  const close = () => {
    setEditing(false);
    setForm(initial());
  };

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
          <fieldset>
            <legend className="sr-only">Lines the agent says while it looks something up</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              <CallHandlingCard
                name={id}
                checked={form.choice === "inherit"}
                onSelect={() => setForm((f) => ({ ...f, choice: "inherit" }))}
                label={inherited.from.filler_lines}
                hint={fillerSummary(inherited.filler_lines)}
              />
              <CallHandlingCard
                name={id}
                checked={form.choice === "standard"}
                onSelect={() => setForm((f) => ({ ...f, choice: "standard" }))}
                label="The standard lines"
                hint="In the caller's language."
              />
              <CallHandlingCard
                name={id}
                checked={form.choice === "own"}
                onSelect={() => setForm((f) => ({ ...f, choice: "own" }))}
                label="Our own lines"
              />
            </div>
          </fieldset>
          {form.choice === "own" && (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${id}-lines`} className="text-xs text-ink-muted">
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
    volume: String(own.ambience_volume_pct ?? effective.ambience_volume_pct),
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const audible = form.choice === "office" || form.choice === "office-quiet";
  const volume = wholeIn(form.volume, bounds.ambience_volume_min_pct, bounds.ambience_volume_max_pct);
  const valid = !audible || volume !== null;
  const next: SoundValues =
    form.choice === "inherit"
      ? { ambience: null, ambience_volume_pct: null }
      : { ambience: form.choice, ambience_volume_pct: audible ? volume : own.ambience_volume_pct };
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
            if (!valid) return;
            onSave(next, () => setEditing(false));
          }}
        >
          <fieldset>
            <legend className="sr-only">Background sound</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              <CallHandlingCard
                name={id}
                checked={form.choice === "inherit"}
                onSelect={() => setForm((f) => ({ ...f, choice: "inherit" }))}
                label={`${inherited.from.ambience} (${ambienceSummary(inherited.ambience, inherited.ambience_volume_pct)})`}
              />
              {bounds.ambiences.map((ambience) => (
                <CallHandlingCard
                  key={ambience}
                  name={id}
                  checked={form.choice === ambience}
                  onSelect={() => setForm((f) => ({ ...f, choice: ambience }))}
                  label={AMBIENCE_LABELS[ambience]}
                />
              ))}
            </div>
          </fieldset>
          {audible && (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${id}-volume`} className="text-xs text-ink-muted">
                {`Volume, ${bounds.ambience_volume_min_pct} to ${bounds.ambience_volume_max_pct}%`}
              </label>
              <input
                id={`${id}-volume`}
                type="number"
                inputMode="numeric"
                min={bounds.ambience_volume_min_pct}
                max={bounds.ambience_volume_max_pct}
                value={form.volume}
                onChange={(event) => setForm((f) => ({ ...f, volume: event.target.value }))}
                className={`w-28 tabular-nums ${FIELD_INLINE}`}
                aria-invalid={volume === null ? true : undefined}
                aria-describedby={volume === null ? `${id}-volume-error` : undefined}
              />
              {volume === null && (
                <FieldMessage id={`${id}-volume-error`}>
                  {`Enter ${bounds.ambience_volume_min_pct} to ${bounds.ambience_volume_max_pct}.`}
                </FieldMessage>
              )}
            </div>
          )}
          <Footer changed={changed} saving={saving} label="Save sound" disabled={!valid} onClose={close} />
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
