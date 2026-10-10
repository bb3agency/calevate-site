"use client";

import { useId, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Clock,
  RotateCcw,
  ShieldAlert,
  TriangleAlert,
  Users,
} from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { cardRefusalSentences } from "@/lib/api/opsRateCard";
import {
  isLostUpdate,
  useRevertConfig,
  useSetConfig,
  type ConfigField,
  type ConfigValue,
  type ConfigWrite,
} from "@/lib/api/opsConfig";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { ConfigInput } from "./ConfigInput";
import {
  REASON_PRESETS,
  appliesCopy,
  confirmPhrase,
  displayValue,
  draftOf,
  optionFor,
  serverFieldMessage,
  settingState,
  validateDraft,
  valueOf,
} from "./configControl";
import { etagOf } from "./configField";

/** The server's minimum for a reason (`ConfigSetIn.reason`). */
const REASON_MIN = 3;

/**
 * Changing ONE setting: the new value in the control that fits it, a before → after
 * preview, the reason (it is the audit log), and Save.
 *
 * Confirmation is proportionate. A setting the server marks `high` risk (it can stop
 * calls, move money, lock people out or change what a caller is told) asks for the new
 * value to be typed back; every other setting is confirmed by the preview and one press.
 * Either way the request carries the server's step-up confirmation (`set_config:<key>` /
 * `revert_config:<key>`) and is audited — nothing the console decides weakens that.
 *
 * The write is conditional (`If-Match`) on the token the form opened against; a value that
 * moves underneath the operator stops the write until they choose, with no blind retry.
 */
export function ConfigForm({
  field,
  basis,
  onDone,
  onWritten,
}: {
  field: ConfigField;
  /** The token this form opened against — non-null by construction (see `ConfigRow`). */
  basis: string;
  onDone: () => void;
  onWritten: (write: ConfigWrite) => void;
}) {
  const save = useSetConfig();
  const revert = useRevertConfig();
  const ids = useId();
  const inputId = `${ids}-value`;
  const errorId = `${ids}-error`;
  const reasonId = `${ids}-reason`;

  const [mode, setMode] = useState<"set" | "revert">("set");
  const [draft, setDraft] = useState(draftOf(field, field.value));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [triedSave, setTriedSave] = useState(false);
  /** The draft the server last refused, so its words are shown only beside that draft. */
  const [refusedDraft, setRefusedDraft] = useState<string | null>(null);
  /**
   * The ENTITY-TAG this edit was decided against, moved only by an explicit choice in
   * `ValueMoved`. The token and not the value: a peer who sets 88 → 91 → 88 leaves the
   * value identical and the revision two higher, and the server refuses that write (412).
   */
  const [basisTag, setBasisTag] = useState(basis);
  /** The server refused a conditional write; cleared only by an operator's choice. */
  const [refused, setRefused] = useState(false);

  const reverting = mode === "revert";
  const next: ConfigValue = reverting ? field.default : valueOf(field, draft);
  // A revert always has something to do: it removes the stored row, even one equal to the default.
  const changed = reverting || JSON.stringify(next) !== JSON.stringify(field.value);
  useUnsavedGuard((!reverting && changed) || reason.trim() !== "" || confirm !== "");

  const conflicted = (etagOf(field) ?? "") !== basisTag || refused;
  const high = field.control.risk === "high";
  const phrase = confirmPhrase(field, next);
  const confirmed = !high || confirmationMatches(confirm, phrase);
  const typedProblem = reverting ? null : validateDraft(field, draft);
  const serverProblem =
    refusedDraft === draft
      ? serverFieldMessage(field, save.error instanceof ApiProblem ? save.error : null)
      : null;
  const valueProblem = typedProblem ?? serverProblem;
  const reasonProblem = reason.trim().length >= REASON_MIN ? null : "Say why, in a few words.";
  const pending = save.isPending || revert.isPending;
  const ready =
    !conflicted &&
    !pending &&
    changed &&
    confirmed &&
    (reverting || (typedProblem === null && reasonProblem === null));
  // `null` for every other failure, which keeps `WriteFailure` the ONE renderer for those.
  const cardRefusals = cardRefusalSentences(save.error);
  const unavailable =
    !reverting && typeof next === "string" ? (optionFor(field, next)?.unavailable_reason ?? null) : null;
  const applies = appliesCopy(field);
  const canRevert = field.source === "db" && field.has_default;

  /** Continue from a stated current value: re-base the precondition, re-arm the confirm. */
  const rebase = (nextDraft: string) => {
    setDraft(nextDraft);
    setBasisTag(etagOf(field) ?? "");
    setRefused(false);
    setConfirm("");
  };
  const onFailure = (error: Error) => {
    if (isLostUpdate(error)) setRefused(true);
    setRefusedDraft(draft);
  };

  const submit = () => {
    setTriedSave(true);
    if (!ready) return;
    if (reverting) {
      revert.mutate(
        { key: field.key, ifMatch: basisTag },
        { onSuccess: (write) => onWritten(write), onError: onFailure },
      );
      return;
    }
    save.mutate(
      { key: field.key, value: next, reason: reason.trim(), ifMatch: basisTag },
      {
        onSuccess: (write) => {
          setReason("");
          setConfirm("");
          onWritten(write);
        },
        onError: onFailure,
      },
    );
  };

  const showValueProblem = valueProblem !== null && (triedSave || draft !== draftOf(field, field.value) || serverProblem !== null);

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {/* The conflict comes FIRST: it decides whether anything below may be sent. */}
      {conflicted && (
        <ValueMoved
          field={field}
          refused={refused}
          serverSaid={save.error?.message ?? revert.error?.message ?? null}
          onTakeTheirs={() => rebase(draftOf(field, field.value))}
          onKeepMine={() => rebase(draft)}
          onDiscard={onDone}
        />
      )}

      {/* Nothing was written when this appears: the card check runs before the row lands. */}
      {!refused && cardRefusals !== null && (
        <NoticeBox
          tone="stop"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="The rate card was refused — nothing was saved"
        >
          <p className="mt-1">
            Calevate will not record a card that sells a minute for less than it costs, or one
            whose rates stop falling as the packs get bigger.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {cardRefusals.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
        </NoticeBox>
      )}
      {!refused && cardRefusals === null && save.error && serverProblem === null && (
        <WriteFailure error={save.error} actionLabel="Save" />
      )}
      {!refused && revert.error && <WriteFailure error={revert.error} actionLabel="Revert to default" />}

      <p className="text-body text-ink-muted">
        Now: <span className="font-semibold text-ink">{displayValue(field, field.value)}</span>{" "}
        <span className="text-meta">({settingState(field).label})</span>
      </p>

      {reverting ? (
        <div className="space-y-2 border-l-2 border-line py-1 pl-3 text-body">
          <p className="text-ink">
            Going back to the default:{" "}
            <span className="font-semibold">{displayValue(field, field.default)}</span>.
          </p>
          <button type="button" onClick={() => setMode("set")} className={SECONDARY_BUTTON_SM}>
            Choose a value instead
          </button>
        </div>
      ) : (
        <div>
          <ConfigInput
            field={field}
            draft={draft}
            onChange={setDraft}
            inputId={inputId}
            describedBy={showValueProblem ? errorId : undefined}
            invalid={showValueProblem}
          />
          {showValueProblem && (
            <p id={errorId} role="alert" className="mt-1.5 text-meta font-medium text-danger">
              {valueProblem}
            </p>
          )}
        </div>
      )}

      {/* Saving is allowed: a tier may be pointed at a model before its key or price lands. */}
      {unavailable && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="Clients cannot be given this model yet"
        >
          <p className="mt-1">{unavailable}</p>
        </NoticeBox>
      )}

      {changed && (
        <div aria-live="polite" className="border-l-2 border-line py-1 pl-3">
          <p className={FIELD_LABEL}>{reverting ? "What reverting does" : "What changes"}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-body">
            <span className="min-w-0 break-words text-ink-muted line-through decoration-ink-faint [overflow-wrap:anywhere]">
              {displayValue(field, field.value)}
            </span>
            <ArrowRight aria-label="becomes" className="h-4 w-4 shrink-0 text-ink-muted" />
            <span className="min-w-0 break-words font-semibold text-ink [overflow-wrap:anywhere]">
              {displayValue(field, next)}
            </span>
          </div>
        </div>
      )}

      {/* WHAT SAVING WILL AND WILL NOT DO, in the same form as the button that does it. */}
      {applies.applies === "live" && !field.caveat ? (
        <p className="flex items-start gap-1.5 text-meta text-ink-muted">
          <CheckCircle2 aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            <span className="font-medium text-ink">{applies.label}.</span> {applies.sentence}
          </span>
        </p>
      ) : (
        <NoticeBox
          tone={applies.tone === "ok" ? "neutral" : applies.tone}
          icon={<Clock aria-hidden className="h-5 w-5" />}
          title={applies.label}
        >
          <p className="mt-1">{applies.sentence}</p>
        </NoticeBox>
      )}

      {high && field.control.risk_reason && (
        <NoticeBox
          tone="warn"
          icon={<ShieldAlert aria-hidden className="h-5 w-5" />}
          title="This setting needs care"
        >
          <p className="mt-1">{field.control.risk_reason}</p>
        </NoticeBox>
      )}

      {reverting ? (
        <p className={FIELD_HINT}>The audit log records this as a return to the default.</p>
      ) : (
        <div>
          <label htmlFor={reasonId} className={FIELD_LABEL}>
            Why are you changing it?
          </label>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {REASON_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                aria-pressed={reason === preset}
                onClick={() => setReason(preset)}
                className={SECONDARY_BUTTON_SM}
              >
                {reason === preset && <Check aria-hidden className="h-3.5 w-3.5 text-brand" />}
                {preset}
              </button>
            ))}
          </div>
          <input
            id={reasonId}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={500}
            placeholder="Or write your own, e.g. Q3 price change approved by the founder"
            aria-invalid={(triedSave && reasonProblem !== null) || undefined}
            aria-describedby={`${reasonId}-hint`}
            className={`${FIELD} mt-2`}
          />
          <span id={`${reasonId}-hint`} className={FIELD_HINT}>
            {triedSave && reasonProblem ? reasonProblem : "Kept with the change in the audit log."}
          </span>
        </div>
      )}

      {high && changed && (
        <TypedConfirmation
          id={`confirm-config-${field.key}`}
          phrase={phrase}
          value={confirm}
          onChange={setConfirm}
          hint="Typing the new value is a second look at exactly what will apply."
        />
      )}

      <div className="sticky bottom-0 -mx-4 -mb-4 flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:-mx-5 sm:px-5 sm:pb-3">
        <button type="submit" disabled={!ready} className={PRIMARY_BUTTON}>
          {reverting ? <RotateCcw aria-hidden className="h-4 w-4" /> : <CheckCircle2 aria-hidden className="h-4 w-4" />}
          {pending ? "Saving…" : reverting ? "Revert to default" : "Save change"}
        </button>
        {canRevert && !reverting && (
          <button
            type="button"
            onClick={() => {
              setMode("revert");
              setConfirm("");
            }}
            className={SECONDARY_BUTTON}
          >
            Use the default
          </button>
        )}
        <p className="w-full text-meta text-ink-muted sm:ml-auto sm:w-auto">
          {conflicted
            ? "Held until you choose above."
            : !changed
              ? "Nothing to save yet."
              : !reverting && typedProblem !== null
                ? "Fix the value above to save."
                : !reverting && reasonProblem !== null
                  ? "Add a reason to save."
                  : high && !confirmed
                    ? "Type the new value to confirm."
                    : null}
        </p>
      </div>
    </form>
  );
}

/**
 * The value moved underneath this edit — the two-operators case, stated and stopped. Three
 * choices and no "retry": these are scalars with no merge, and a re-send against a changed
 * value is last-write-wins. Either continuing choice re-bases the precondition and clears
 * the confirmation, so the next save is still conditional and still deliberate.
 */
function ValueMoved({
  field,
  refused,
  serverSaid,
  onTakeTheirs,
  onKeepMine,
  onDiscard,
}: {
  field: ConfigField;
  refused: boolean;
  serverSaid: string | null;
  onTakeTheirs: () => void;
  onKeepMine: () => void;
  onDiscard: () => void;
}) {
  return (
    <NoticeBox
      tone="stop"
      icon={<Users aria-hidden className="h-5 w-5" />}
      title={
        refused
          ? "Someone changed this setting first — nothing was saved"
          : "Someone changed this setting while you had it open"
      }
    >
      <p className="mt-1">
        {refused
          ? "Someone else changed this setting between the value you were shown and the moment you pressed Save."
          : "Someone else changed this setting since you opened this form. Nothing you chose has been sent."}
      </p>
      {refused && serverSaid && <p className="mt-1">The server said: {serverSaid}</p>}
      <p className="mt-2">
        It is now <span className="font-semibold">{displayValue(field, field.value)}</span> (
        {settingState(field).label}).
        {field.note && <> Their reason: &ldquo;{field.note}&rdquo;</>}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={onTakeTheirs} className={SECONDARY_BUTTON}>
          Use their value
        </button>
        <button type="button" onClick={onKeepMine} className={SECONDARY_BUTTON}>
          Keep mine and replace theirs
        </button>
        <button type="button" onClick={onDiscard} className={SECONDARY_BUTTON}>
          Discard my change
        </button>
      </div>
    </NoticeBox>
  );
}
