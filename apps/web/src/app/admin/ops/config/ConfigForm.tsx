"use client";

import { useState } from "react";
import { RotateCcw, Save, TriangleAlert, Users } from "lucide-react";

import { WriteFailure } from "@/app/admin/writeFailure";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { useFormValidation } from "@/components/formValidation";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  SECONDARY_BUTTON,
} from "@/components/ui";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import { cardRefusalSentences } from "@/lib/api/opsRateCard";
import {
  isLostUpdate,
  useRevertConfig,
  useSetConfig,
  type ConfigField,
  type ConfigWrite,
} from "@/lib/api/opsConfig";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import {
  AppliesNotice,
  appliesVerdict,
  display,
  draftOf,
  etagOf,
  parseDraft,
  provenance,
  selectChoices,
} from "./configField";

/**
 * Changing ONE setting: new value, reason, the key typed back, then Save.
 *
 * The word typed is sent as `X-Confirm-Action` and names the KEY, so a confirmation made for
 * one setting cannot be replayed against another. The write is conditional (`If-Match`) on
 * the token the form opened against; a poll that moves the token underneath the operator
 * stops the write until they choose, and there is no retry — re-sending the same body
 * against a moved value is last-write-wins with a confirmation step.
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
  // Seeded from the value in force, so a change is an edit rather than a retype.
  const [draft, setDraft] = useState(draftOf(field.value));
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  /**
   * The ENTITY-TAG this edit was decided against, moved only by an explicit choice in
   * `ValueMoved`. The token and not the value: a peer who sets 88 → 91 → 88 leaves the
   * value identical and the revision two higher, and the server refuses that write (412).
   */
  const [basisTag, setBasisTag] = useState(basis);
  /** The server refused a conditional write; cleared only by an operator's choice. */
  const [refused, setRefused] = useState(false);

  useUnsavedGuard(draft !== draftOf(field.value) || reason.trim() !== "" || confirm !== "");

  const word = field.key.toUpperCase();
  // A field that LOSES its token between two reads has, as far as this form can tell,
  // moved — the safe reading, and the one that stops the write.
  const conflicted = (etagOf(field) ?? "") !== basisTag || refused;
  const valid = useFormValidation();
  const ready = confirmationMatches(confirm, word, "exact") && !conflicted;
  const verdict = appliesVerdict(field);
  // `null` for every other failure, which keeps `WriteFailure` the ONE renderer for those.
  const cardRefusals = cardRefusalSentences(save.error);
  const choices = field.kind === "enum" ? selectChoices(field) : [];
  const unavailable = choices.find((choice) => choice.value === draft)?.unavailable ?? null;

  /** Continue from a stated current value: re-base the precondition, re-arm the typing. */
  const rebase = (nextDraft: string) => {
    setDraft(nextDraft);
    setBasisTag(etagOf(field) ?? "");
    setRefused(false);
    setConfirm("");
  };

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={valid.onSubmit(() => {
        // Belt and braces with the button's `disabled`: Enter in a text input submits.
        if (!ready || save.isPending) return;
        save.mutate(
          { key: field.key, value: parseDraft(field, draft), reason: reason.trim(), ifMatch: basisTag },
          {
            onSuccess: (write) => {
              setReason("");
              setConfirm("");
              onWritten(write);
            },
            // ONLY the flag: `rebase` is the one place the confirmation is cleared.
            onError: (error) => {
              if (isLostUpdate(error)) setRefused(true);
            },
          },
        );
      })}
    >
      {/* The conflict comes FIRST: it decides whether anything below may be sent. */}
      {conflicted && (
        <ValueMoved
          field={field}
          refused={refused}
          serverSaid={save.error?.message ?? revert.error?.message ?? null}
          onTakeTheirs={() => rebase(draftOf(field.value))}
          onKeepMine={() => rebase(draft)}
          onDiscard={onDone}
        />
      )}

      {/* The card refusal in the server's own sentences, one line per refusal. Nothing was
          written when this appears: the card check runs before the row lands. */}
      {!refused && cardRefusals !== null && (
        <NoticeBox
          tone="stop"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="The rate card was refused — nothing was saved"
        >
          <p className="mt-1">
            Calevate will not record a card that sells a minute for less than it costs, or
            one whose rates stop falling as the packs get bigger. Neither the price nor the
            card moved.
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {cardRefusals.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs">
            The card is a committed catalogue, so correcting it is a code change and a
            deploy — there is no cell to retype here.
          </p>
        </NoticeBox>
      )}

      {!refused && cardRefusals === null && save.error && (
        <WriteFailure error={save.error} actionLabel="Save" />
      )}
      {!refused && revert.error && <WriteFailure error={revert.error} actionLabel="Revert to default" />}

      <label className="block">
        <span className={FIELD_LABEL}>New value</span>
        {field.kind === "enum" ? (
          <select value={draft} onChange={(e) => setDraft(e.target.value)} className={FIELD}>
            {choices.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.text}
              </option>
            ))}
          </select>
        ) : field.kind === "boolean" ? (
          <select value={draft} onChange={(e) => setDraft(e.target.value)} className={FIELD}>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            // `text` even for decimals: a `number` input hands back a float, and
            // `usd_inr_rate` must reach the API as the exact string typed (hard rule 7).
            inputMode={field.kind === "integer" ? "numeric" : "text"}
            className={`${FIELD} font-mono`}
          />
        )}
        <span className={FIELD_HINT}>
          {field.has_default ? (
            <>
              Built-in default: <MonoValue>{display(field.default)}</MonoValue>.
            </>
          ) : (
            <>This setting has no built-in default, so it cannot be reverted.</>
          )}{" "}
          Checked against the same rules the platform uses when it starts, so a value that
          would break it is refused here.
        </span>
      </label>

      {/* Saving is allowed: the validator accepts it, and a tier may be pointed at a model
          before its key or price lands. What it means for clients is said here. */}
      {unavailable && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="Clients cannot be given this model yet"
        >
          <p className="mt-1">{unavailable}</p>
        </NoticeBox>
      )}

      <label className="block">
        <span className={FIELD_LABEL}>Reason</span>
        <input
          {...valid.field("reason", "Say why this value is changing.")}
          required
          minLength={3}
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. 'Q3 price change, approved in #pricing'"
          className={FIELD}
        />
        {valid.error("reason")}
        <span className={FIELD_HINT}>Saved with the change and in the audit log.</span>
      </label>

      <TypedConfirmation
        match="exact"
        id={`confirm-config-${field.key}`}
        phrase={word}
        value={confirm}
        onChange={setConfirm}
        hint="This confirms your change and is tied to this setting, so it can't be used to change a different one."
      />

      {/* WHAT SAVING WILL AND WILL NOT DO, immediately above the button that does it. */}
      <AppliesNotice verdict={verdict} />

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={!ready || save.isPending} className={PRIMARY_BUTTON}>
          <Save aria-hidden className="h-4 w-4" />
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {/* Offered only where there is something to revert TO and FROM. It carries its own
            confirmation string on the wire, so the word above does not authorise it. */}
        {field.source === "db" && field.has_default && (
          <button
            type="button"
            disabled={!confirmationMatches(confirm, word, "exact") || conflicted || revert.isPending}
            onClick={() =>
              revert.mutate(
                { key: field.key, ifMatch: basisTag },
                {
                  onSuccess: (write) => {
                    setConfirm("");
                    onWritten(write);
                  },
                  onError: (error) => {
                    if (isLostUpdate(error)) setRefused(true);
                  },
                },
              )
            }
            className={SECONDARY_BUTTON}
          >
            <RotateCcw aria-hidden className="h-4 w-4" />
            {revert.isPending ? "Reverting…" : "Revert to default"}
          </button>
        )}
      </div>

      {/* Why a control is dead, where the control is. */}
      {conflicted ? (
        <p className="text-xs text-ink-muted">
          Saving and reverting are both held until you choose above — nothing will be sent
          against a value that has already changed.
        </p>
      ) : (
        !confirmationMatches(confirm, word, "exact") &&
        field.source === "db" &&
        field.has_default && (
          <p className="text-xs text-ink-muted">
            Type <MonoValue>{word}</MonoValue> above to enable both buttons — reverting is
            confirmed the same way.
          </p>
        )
      )}
    </form>
  );
}

/**
 * The value moved underneath this edit — the two-operators case, stated and stopped. Three
 * choices and no "retry": these are scalars with no merge, and a re-send against a changed
 * value is last-write-wins. Either continuing choice re-bases the precondition and clears the
 * typed word, so the next save is still conditional and still deliberate.
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
          ? "Nothing was saved. Someone else changed this setting between the value you " +
            "were shown and the moment you pressed Save."
          : "Someone else changed this setting since you opened this form. Nothing you " +
            "typed has been sent."}
      </p>
      {/* The server's words inside this box rather than in a second red one above it. */}
      {refused && serverSaid && <p className="mt-1 text-xs">The server said: {serverSaid}</p>}
      <p className="mt-2">
        It is now <MonoValue className="font-semibold">{display(field.value)}</MonoValue>,{" "}
        {provenance(field)}.
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
      <p className="mt-2 text-xs">
        Either of the first two puts you back in the form with the confirmation cleared, so
        the next save is a fresh decision made against the value above.
      </p>
    </NoticeBox>
  );
}
