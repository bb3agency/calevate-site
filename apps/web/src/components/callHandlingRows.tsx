"use client";

/**
 * THE PAUSE BEFORE AN AGENT REPLIES, AND HANGING UP WHEN IT HAS FINISHED (D-751) — two rows,
 * shared by an agent's Call handling and the organisation's default, so the two screens
 * offer the same choices in the same words.
 *
 * Each row is a `SettingRow` summary (the value in force and where it comes from) with
 * "Change", which opens choice cards and the shared save bar. "Use the default" is a card of
 * its own: it saves `null`, so the value follows the level above rather than freezing a copy
 * of it. The server resolves every value; nothing here works out what is in force.
 */

import { CheckCircle2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { InfoTip } from "@/components/console/infoTip";
import { SaveBar } from "@/components/console/saveBar";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { FieldMessage } from "@/components/formValidation";
import { FIELD_INLINE, ProblemNotice } from "@/components/ui";
import {
  PAUSE_PRESETS,
  formatPause,
  pauseLabel,
  sourceLabel,
  type CallHandlingSource,
} from "@/lib/api/callHandling";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/** One sentence for both rows, because it is one promise. */
export const CALL_HANDLING_NEXT_CALL =
  "Applies from the next call. A call already in progress finishes as it started.";

interface RowProps<T> {
  idPrefix: string;
  /** In force now, and the level that chose it. */
  effective: T;
  source: CallHandlingSource;
  /** This level's own value; `null` follows the level above. */
  own: T | null;
  /** The card that saves `null`, naming what that resolves to. */
  inheritLabel: string;
  canChange: boolean;
  saving: boolean;
  error: Error | null;
  onSave: (next: T | null, done: () => void) => void;
}

export function CallHandlingCard({
  name,
  checked,
  onSelect,
  label,
  hint,
  children,
}: {
  name: string;
  checked: boolean;
  onSelect: () => void;
  label: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <label className={`${CHOICE_CARD} ${checked ? CHOICE_ON : CHOICE_OFF}`}>
      <input type="radio" name={name} className="sr-only" checked={checked} onChange={onSelect} />
      {checked && (
        <CheckCircle2 aria-hidden className="absolute right-2 top-2 h-4 w-4 text-brand-strong" />
      )}
      <span className="block pr-6 text-sm font-semibold text-ink">{label}</span>
      {hint ? <span className="mt-0.5 block text-xs text-ink-muted">{hint}</span> : null}
      {children}
    </label>
  );
}

type PauseChoice = "inherit" | "custom" | `${number}`;

function initialPause(own: number | null): PauseChoice {
  if (own === null) return "inherit";
  return PAUSE_PRESETS.some((p) => p.ms === own) ? (String(own) as PauseChoice) : "custom";
}

export function PauseRow({
  idPrefix,
  effective,
  source,
  own,
  inheritLabel,
  canChange,
  saving,
  error,
  onSave,
  minMs,
  maxMs,
}: RowProps<number> & { minMs: number; maxMs: number }) {
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<PauseChoice>(initialPause(own));
  const [custom, setCustom] = useState(own === null ? "" : String(own / 1000));
  const customMs = Math.round(Number(custom) * 1000);
  const customValid = custom.trim() !== "" && Number.isFinite(customMs) && customMs >= minMs && customMs <= maxMs;
  const next: number | null =
    choice === "inherit" ? null : choice === "custom" ? (customValid ? customMs : NaN) : Number(choice);
  const changed = editing && (next === null ? own !== null : next !== own);
  useUnsavedGuard(changed);
  const name = `${idPrefix}-pause`;
  const customId = `${idPrefix}-pause-seconds`;

  // From the saved value each time it opens, so a save made since is what it starts on.
  const reset = () => {
    setChoice(initialPause(own));
    setCustom(own === null ? "" : String(own / 1000));
  };
  const close = () => {
    setEditing(false);
    reset();
  };

  return (
    <div>
      <SettingRow
        label="Pause before the agent replies"
        hint={sourceLabel(source)}
        info={
          <p>
            How long the caller must be quiet before the agent decides they have finished
            and replies. A short pause answers quickly but can cut in while someone is
            reading out a phone number. A longer one waits for them, and every reply comes
            that much later.
          </p>
        }
        value={pauseLabel(effective)}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                reset();
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
            if (next !== null && Number.isNaN(next)) return;
            onSave(next, () => setEditing(false));
          }}
        >
          <fieldset>
            <legend className="sr-only">Pause before the agent replies</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              <CallHandlingCard
                name={name}
                checked={choice === "inherit"}
                onSelect={() => setChoice("inherit")}
                label={inheritLabel}
              />
              {PAUSE_PRESETS.map((preset) => (
                <CallHandlingCard
                  key={preset.ms}
                  name={name}
                  checked={choice === String(preset.ms)}
                  onSelect={() => setChoice(String(preset.ms) as PauseChoice)}
                  label={`${preset.label} (${formatPause(preset.ms)})`}
                  hint={preset.hint}
                />
              ))}
              <CallHandlingCard
                name={name}
                checked={choice === "custom"}
                onSelect={() => setChoice("custom")}
                label="Custom"
                hint={`Between ${formatPause(minMs)} and ${formatPause(maxMs)}.`}
              />
            </div>
          </fieldset>
          {choice === "custom" && (
            <div className="flex flex-col gap-1">
              <label htmlFor={customId} className="text-xs text-ink-muted">
                Seconds
              </label>
              <input
                id={customId}
                type="number"
                inputMode="decimal"
                step={0.05}
                min={minMs / 1000}
                max={maxMs / 1000}
                value={custom}
                onChange={(event) => setCustom(event.target.value)}
                className={`w-32 tabular-nums ${FIELD_INLINE}`}
                aria-invalid={custom !== "" && !customValid ? true : undefined}
                aria-describedby={custom !== "" && !customValid ? `${customId}-error` : undefined}
              />
              {custom !== "" && !customValid ? (
                <FieldMessage id={`${customId}-error`}>
                  {`Enter a pause between ${formatPause(minMs)} and ${formatPause(maxMs)}.`}
                </FieldMessage>
              ) : null}
            </div>
          )}
          {(changed || saving) && (
            <SaveBar
              label="Save pause"
              saving={saving}
              disabled={next !== null && Number.isNaN(next)}
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

type HangUpChoice = "inherit" | "on" | "off";

function initialHangUp(own: boolean | null): HangUpChoice {
  return own === null ? "inherit" : own ? "on" : "off";
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
  own,
  inheritLabel,
  canChange,
  saving,
  error,
  onSave,
}: RowProps<boolean>) {
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<HangUpChoice>(initialHangUp(own));
  const next: boolean | null = choice === "inherit" ? null : choice === "on";
  const changed = editing && next !== own;
  useUnsavedGuard(changed);
  const name = `${idPrefix}-hang-up`;

  const reset = () => setChoice(initialHangUp(own));
  const close = () => {
    setEditing(false);
    reset();
  };

  return (
    <div>
      <SettingRow
        label="Hang up when the conversation ends"
        hint={sourceLabel(source)}
        info={<p>{HANG_UP_INFO}</p>}
        value={effective ? "On" : "Off"}
        action={
          editing || !canChange ? undefined : (
            <button
              type="button"
              onClick={() => {
                reset();
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
            onSave(next, () => setEditing(false));
          }}
        >
          <fieldset>
            <legend className="sr-only">Hang up when the conversation ends</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              <CallHandlingCard
                name={name}
                checked={choice === "inherit"}
                onSelect={() => setChoice("inherit")}
                label={inheritLabel}
              />
              <CallHandlingCard
                name={name}
                checked={choice === "on"}
                onSelect={() => setChoice("on")}
                label="On"
                hint="The agent puts the phone down when it has finished."
              />
              <CallHandlingCard
                name={name}
                checked={choice === "off"}
                onSelect={() => setChoice("off")}
                label="Off"
                hint="The call stays connected, and charged, until the caller hangs up."
              />
            </div>
          </fieldset>
          {(changed || saving) && (
            <SaveBar
              label="Save"
              saving={saving}
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
