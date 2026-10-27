"use client";

/**
 * THE PAUSE BEFORE AN AGENT REPLIES, AND HANGING UP WHEN IT HAS FINISHED (D-751) — two rows,
 * shared by an agent's Settings and the operator's console (an agent, and a client's
 * defaults), so every screen offers the same choices in the same words.
 *
 * On an agent's Settings a reader who may change every agent gets `scope`: the editor then
 * asks whether the change is for "Just this agent" or "All my agents" (founder, 27 Oct 2026:
 * one place for these settings, on the agent, rather than an account page beside it).
 *
 * Each row is a `SettingRow` summary (the value in force and where it comes from) with
 * "Change", which opens a compact editor and the shared save bar. "Use the default" is a
 * checkbox above the choice rather than one more option beside it: following the level above
 * is a different decision from picking a value, and as an option it sat next to the very
 * value it resolves to. Ticked, it saves `null`, so the value follows the level above rather
 * than freezing a copy of it. The server resolves every value; nothing here works out what
 * is in force.
 *
 * `OpeningWaitsRow` (D-871) is an agent's own switch with no default to follow, shown only
 * on an agent's Call handling.
 */

import { useState, type ReactNode } from "react";

import { type FeedbackStatus } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { SaveBar } from "@/components/console/saveBar";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { Slider } from "@/components/arc/slider";
import { FIELD_HINT, ProblemNotice, ToggleSwitch } from "@/components/ui";
import {
  PAUSE_PRESETS,
  STANDARD_OPENING_WAIT_MS,
  formatPause,
  pauseLabel,
  sourceLabel,
  type CallHandlingScope,
  type CallHandlingSource,
} from "@/lib/api/callHandling";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/** One sentence for both rows, because it is one promise. */
export const CALL_HANDLING_NEXT_CALL =
  "Applies from the next call. A call already in progress finishes as it started.";

/** The editor's column: narrow enough that a choice and its hint read as one unit. */
export const CALL_HANDLING_EDITOR = "max-w-md space-y-4";

interface RowProps<T> {
  idPrefix: string;
  /** In force now, and the level that chose it. */
  effective: T;
  source: CallHandlingSource;
  /** Overrides the words for `source`, for a reader who is not the account's owner, or to add
   * which agents do not follow an account default. */
  sourceHint?: ReactNode;
  /** This level's own value; `null` follows the level above. */
  own: T | null;
  /** The default and what it resolves to, "Calevate default: Quick (0.25 s)". */
  inheritLabel: string;
  canChange: boolean;
  /** This row's save, from the caller's `useActionFeedback`. */
  status: FeedbackStatus;
  error: Error | null;
  /** On an agent's Settings, for a reader who may change every agent: "All my agents". */
  scope?: ScopeOffer<string>;
  onSave: (next: T | null, done: () => void, scope: CallHandlingScope) => void;
}

/** The save bar's words and whether a save would do anything. "All my agents" always does:
 * it can make other agents follow a value this one already holds. */
function scopeSave(scope: CallHandlingScope, sameAsOwn: boolean, label: string) {
  return {
    changed: scope === "all" || !sameAsOwn,
    label: scope === "all" ? "Save for all agents" : label,
  };
}

/**
 * "All my agents" on offer for a row of an agent's Settings: how many other agents keep a
 * value of their own (which the save replaces), and what "use the default" means once the
 * change is for every agent: Calevate's, since the agents then share whatever is chosen.
 */
export interface ScopeOffer<I> {
  others: number;
  inherit: I;
}

const SCOPE_RADIO =
  "mt-0.5 h-4 w-4 shrink-0 border-line accent-brand-strong touch:h-5 touch:w-5";

/** Whom this change is for. Two visible choices with what each does underneath, rather than
 * a second button beside Save: which agents change is the decision, not a shortcut. */
export function ScopeChoice({
  id,
  scope,
  others,
  onChange,
}: {
  id: string;
  scope: CallHandlingScope;
  others: number;
  onChange: (scope: CallHandlingScope) => void;
}) {
  const allHint =
    others === 0
      ? "Every agent uses this, and so will new ones."
      : `Every agent uses this. ${others === 1 ? "1 agent that has its" : `${others} agents that have their`} own setting will change too.`;
  const choices: { value: CallHandlingScope; label: string; hint: string }[] = [
    { value: "agent", label: "Just this agent", hint: "Your other agents keep their setting." },
    { value: "all", label: "All my agents", hint: allHint },
  ];
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold text-ink">Use this for</legend>
      <div className="space-y-2">
        {choices.map((choice) => (
          <label key={choice.value} className="flex items-start gap-2 text-sm text-ink">
            <input
              type="radio"
              name={`${id}-scope`}
              value={choice.value}
              checked={scope === choice.value}
              onChange={() => onChange(choice.value)}
              aria-describedby={`${id}-scope-${choice.value}`}
              className={SCOPE_RADIO}
            />
            <span>
              {choice.label}
              <span id={`${id}-scope-${choice.value}`} className="block text-meta text-ink-muted">
                {choice.hint}
              </span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** "Use the Calevate default: Off". Ticked, the row saves `null`. */
export function DefaultCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-line accent-brand-strong touch:h-5 touch:w-5"
      />
      {label}
    </label>
  );
}

/**
 * A bounded number as a slider with its value read out beside the label. The bounds are the
 * server's, so the slider cannot hold a value the server would refuse, and the two ends of
 * the scale show the range before anyone tries to leave it.
 */
export function SliderField({
  id,
  label,
  value,
  valueText,
  min,
  max,
  step,
  scale,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  /** The value as people read it, shown beside the label and announced. */
  valueText: string;
  min: number;
  max: number;
  step: number;
  /** The words under each end of the track. */
  scale: [ReactNode, ReactNode];
  onChange: (value: number) => void;
}) {
  return (
    <Slider
      id={id}
      label={label}
      value={value}
      valueText={() => valueText}
      min={min}
      max={max}
      step={step}
      scale={scale}
      onChange={onChange}
    />
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * 50 ms: the presets (250, 500, 700) sit on it, it is the old seconds box's 0.05 step, and
 * across 0.2 to 3 s it gives a phone thumb about 56 stops, where 10 ms would give 280 stops
 * on a 300 px track and a drag could not land on a round value.
 */
const PAUSE_STEP_MS = 50;

/** The pause row's line on an agent that does not wait for silence. */
export const PAUSE_NOT_USED = "This agent hears when the caller has finished, so it waits for no pause.";

export function PauseRow({
  idPrefix,
  effective,
  source,
  sourceHint,
  own,
  inheritLabel,
  canChange,
  status,
  error,
  scope,
  onSave,
  minMs,
  maxMs,
  notUsed = false,
}: RowProps<number> & {
  minMs: number;
  maxMs: number;
  /** The agent's turns end when it hears the caller finish, so no pause is waited for
   * (`turn_silence_applies` false, D-903). The value is kept for a move back to silence. */
  notUsed?: boolean;
}) {
  const saving = status === "pending";
  // Unticking the default starts from this level's own value, else from the one in force,
  // which is the default's when this level has none.
  const initial = () => ({
    useDefault: own === null,
    ms: clamp(own ?? effective, minMs, maxMs),
    scope: "agent" as CallHandlingScope,
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const next: number | null = form.useDefault ? null : form.ms;
  const save = scopeSave(form.scope, next === own, "Save pause");
  const changed = editing && save.changed;
  useUnsavedGuard(changed);
  const defaultLabel = form.scope === "all" && scope ? scope.inherit : inheritLabel;
  const id = `${idPrefix}-pause`;
  const preset = PAUSE_PRESETS.find((p) => p.ms === form.ms);

  // From the saved value each time it opens, so a save made since is what it starts on.
  const close = () => {
    setEditing(false);
    setForm(initial());
  };

  return (
    <div>
      <SettingRow
        label="Pause before the agent replies"
        hint={notUsed ? PAUSE_NOT_USED : (sourceHint ?? sourceLabel(source))}
        info={
          <p>
            The quiet after the caller&apos;s last words before the agent replies. A short pause
            answers quickly but can cut in while someone is reading out a phone number. A longer
            one waits for them, and every reply comes that much later. It applies only to an
            agent that waits for silence; one that hears when the caller has finished does not
            use it.
          </p>
        }
        value={notUsed ? "Not used" : pauseLabel(effective)}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
              className={TEXT_ACTION}
            >
              Change
            </button>
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
              label={`Use the ${defaultLabel}`}
              checked={form.useDefault}
              onChange={(checked) => setForm((f) => ({ ...f, useDefault: checked }))}
            />
            {/* The presets are shortcuts onto the slider, not four segments with a "Custom" one
                that opens it: segments are equal width, so four sized to "Unhurried" overflow a
                375 px phone's column. A value off the presets leaves no segment selected. */}
            {!form.useDefault && (
              <>
                <div>
                  <SegmentedControl
                    label="Pause before the agent replies"
                    options={PAUSE_PRESETS.map((p) => ({ value: String(p.ms), label: p.label }))}
                    value={String(form.ms)}
                    onValueChange={(value) => setForm((f) => ({ ...f, ms: Number(value) }))}
                  />
                  <p className={FIELD_HINT}>
                    {preset ? preset.hint : "A pause of your own."}
                  </p>
                </div>
                <SliderField
                  id={`${id}-ms`}
                  label="Pause"
                  value={form.ms}
                  valueText={formatPause(form.ms)}
                  min={minMs}
                  max={maxMs}
                  step={PAUSE_STEP_MS}
                  scale={[formatPause(minMs), formatPause(maxMs)]}
                  onChange={(ms) => setForm((f) => ({ ...f, ms }))}
                />
              </>
            )}
            {scope && (
              <ScopeChoice
                id={id}
                scope={form.scope}
                others={scope.others}
                onChange={(picked) => setForm((f) => ({ ...f, scope: picked }))}
              />
            )}
          </div>
          {(changed || saving) && (
            <SaveBar
              label={save.label}
              status={status}
              onCancel={close}
              note={CALL_HANDLING_NEXT_CALL}
            />
          )}
          {!changed && !saving && (
            <button type="button" onClick={close} className={TEXT_ACTION}>
              Close
            </button>
          )}
        </form>
      )}
    </div>
  );
}

/** The trade-off, in plain words, for the ⓘ. */
const HANG_UP_INFO =
  "When the agent has finished, it puts the phone down instead of waiting for the caller " +
  "to. With this off, a finished call stays connected until the caller hangs up, and " +
  "every minute it stays connected is charged to your account.";

export function HangUpRow({
  idPrefix,
  effective,
  source,
  sourceHint,
  own,
  inheritLabel,
  canChange,
  status,
  error,
  scope,
  onSave,
}: RowProps<boolean>) {
  const saving = status === "pending";
  const initial = () => ({
    useDefault: own === null,
    on: own ?? effective,
    scope: "agent" as CallHandlingScope,
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const next: boolean | null = form.useDefault ? null : form.on;
  const save = scopeSave(form.scope, next === own, "Save");
  const changed = editing && save.changed;
  useUnsavedGuard(changed);
  const defaultLabel = form.scope === "all" && scope ? scope.inherit : inheritLabel;

  const close = () => {
    setEditing(false);
    setForm(initial());
  };

  return (
    <div>
      <SettingRow
        label="Hang up when the conversation ends"
        hint={sourceHint ?? sourceLabel(source)}
        info={<p>{HANG_UP_INFO}</p>}
        value={effective ? "On" : "Off"}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
              className={TEXT_ACTION}
            >
              Change
            </button>
          )
        }
      />
      {!effective && (
        <p data-notice="neutral" className="flex items-center gap-1 pb-3 text-meta text-ink-muted">
          Finished calls stay connected, and charged, until the caller hangs up.
          <InfoTip label="Calls left connected">
            <p>{HANG_UP_INFO}</p>
          </InfoTip>
        </p>
      )}
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
              label={`Use the ${defaultLabel}`}
              checked={form.useDefault}
              onChange={(checked) => setForm((f) => ({ ...f, useDefault: checked }))}
            />
            {!form.useDefault && (
              <ToggleSwitch
                label="Hang up when the agent has finished"
                hint={
                  form.on
                    ? "The agent puts the phone down when it has finished."
                    : "The call stays connected, and charged, until the caller hangs up."
                }
                checked={form.on}
                onChange={(on) => setForm((f) => ({ ...f, on }))}
              />
            )}
            {scope && (
              <ScopeChoice
                id={`${idPrefix}-hang-up`}
                scope={form.scope}
                others={scope.others}
                onChange={(picked) => setForm((f) => ({ ...f, scope: picked }))}
              />
            )}
          </div>
          {(changed || saving) && (
            <SaveBar
              label={save.label}
              status={status}
              onCancel={close}
              note={CALL_HANDLING_NEXT_CALL}
            />
          )}
          {!changed && !saving && (
            <button type="button" onClick={close} className={TEXT_ACTION}>
              Close
            </button>
          )}
        </form>
      )}
    </div>
  );
}

/** The row's one plain line (D-871), with the silence it waits through (D-901). */
export function openingWaitsLine(waitMs: number = STANDARD_OPENING_WAIT_MS): string {
  return (
    "Your agent speaks right after the first words of the person who picks up, or after " +
    `${formatPause(waitMs)} if they stay silent.`
  );
}
const OPENING_SPEAKS_LINE = "Your agent speaks as soon as the call connects.";

const OPENING_WAITS_INFO =
  "On, the agent lets the person who picks up speak first and opens right after their first " +
  "words, so it does not talk over their hello. A plain hello is not answered a second time. " +
  "If they say nothing, it opens after the wait set below. This suits an agent that calls " +
  "people. Off, the agent speaks the moment the call connects, which suits people calling " +
  "your business.";

/**
 * Whether the agent's first words wait for the person's hello (D-871). The agent's own
 * setting with no organisation default, so unlike the rows above there is no "use the
 * default" choice: the editor is the switch alone.
 */
export function OpeningWaitsRow({
  on,
  waitMs,
  canChange,
  status,
  error,
  onSave,
}: {
  on: boolean;
  /** The silence it waits through before opening anyway; the platform's four seconds if unset. */
  waitMs?: number;
  canChange: boolean;
  /** This row's save, from the caller's `useActionFeedback`. */
  status: FeedbackStatus;
  error: Error | null;
  onSave: (next: boolean, done: () => void) => void;
}) {
  const saving = status === "pending";
  const [editing, setEditing] = useState(false);
  const [next, setNext] = useState(on);
  const changed = editing && next !== on;
  useUnsavedGuard(changed);

  // From the saved value each time it opens, so a save made since is what it starts on.
  const close = () => {
    setEditing(false);
    setNext(on);
  };

  return (
    <div>
      <SettingRow
        label="Wait for them to say hello"
        // The line describes the value in force, so an agent switched off never reads as
        // one that waits.
        hint={on ? openingWaitsLine(waitMs) : OPENING_SPEAKS_LINE}
        info={<p>{OPENING_WAITS_INFO}</p>}
        value={on ? "On" : "Off"}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                setNext(on);
                setEditing(true);
              }}
              className={TEXT_ACTION}
            >
              Change
            </button>
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
            <ToggleSwitch
              label="Wait for them to say hello"
              hint={next ? openingWaitsLine(waitMs) : OPENING_SPEAKS_LINE}
              checked={next}
              onChange={setNext}
            />
          </div>
          {(changed || saving) && (
            <SaveBar label="Save" status={status} onCancel={close} note={CALL_HANDLING_NEXT_CALL} />
          )}
          {!changed && !saving && (
            <button type="button" onClick={close} className={TEXT_ACTION}>
              Close
            </button>
          )}
        </form>
      )}
    </div>
  );
}

const OPENING_WAIT_LINE = "If nobody speaks, your agent opens after this.";

const OPENING_WAIT_INFO =
  "A short wait opens sooner when the person stays quiet, but can talk over a slow hello. " +
  "A long wait gives them time to answer, and leaves a silence before the agent speaks.";

/**
 * How long a waiting opening waits through silence (D-901), shown under "Wait for them to say
 * hello" while that is on and the platform offers the setting. Inherits like the pause: the
 * agent's own, the value the agents share, or Calevate's.
 */
export function OpeningWaitRow({
  idPrefix,
  effective,
  source,
  own,
  inheritLabel,
  canChange,
  status,
  error,
  scope,
  onSave,
  minMs,
  maxMs,
  stepMs,
}: RowProps<number> & { minMs: number; maxMs: number; stepMs: number }) {
  const saving = status === "pending";
  const initial = () => ({
    useDefault: own === null,
    ms: clamp(own ?? effective, minMs, maxMs),
    scope: "agent" as CallHandlingScope,
  });
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(initial);
  const next: number | null = form.useDefault ? null : form.ms;
  const save = scopeSave(form.scope, next === own, "Save wait");
  const changed = editing && save.changed;
  useUnsavedGuard(changed);
  const defaultLabel = form.scope === "all" && scope ? scope.inherit : inheritLabel;
  const id = `${idPrefix}-opening-wait`;

  const close = () => {
    setEditing(false);
    setForm(initial());
  };

  return (
    <div>
      <SettingRow
        label="How long to wait for hello"
        hint={`${OPENING_WAIT_LINE} ${sourceLabel(source)}.`}
        info={<p>{OPENING_WAIT_INFO}</p>}
        value={formatPause(effective)}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                setForm(initial());
                setEditing(true);
              }}
              className={TEXT_ACTION}
            >
              Change
            </button>
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
              label={`Use the ${defaultLabel}`}
              checked={form.useDefault}
              onChange={(checked) => setForm((f) => ({ ...f, useDefault: checked }))}
            />
            {!form.useDefault && (
              <SliderField
                id={`${id}-ms`}
                label="Wait"
                value={form.ms}
                valueText={formatPause(form.ms)}
                min={minMs}
                max={maxMs}
                step={stepMs}
                scale={[formatPause(minMs), formatPause(maxMs)]}
                onChange={(ms) => setForm((f) => ({ ...f, ms }))}
              />
            )}
            {scope && (
              <ScopeChoice
                id={id}
                scope={form.scope}
                others={scope.others}
                onChange={(picked) => setForm((f) => ({ ...f, scope: picked }))}
              />
            )}
          </div>
          {(changed || saving) && (
            <SaveBar
              label={save.label}
              status={status}
              onCancel={close}
              note={CALL_HANDLING_NEXT_CALL}
            />
          )}
          {!changed && !saving && (
            <button type="button" onClick={close} className={TEXT_ACTION}>
              Close
            </button>
          )}
        </form>
      )}
    </div>
  );
}
