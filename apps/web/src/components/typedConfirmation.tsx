"use client";

import { useId, type ReactNode } from "react";

import { FIELD, FIELD_HINT, FIELD_LABEL } from "@/components/ui";

/**
 * "Type X to confirm" — the human half of a step-up confirmation, and the ONE control for
 * it in both consoles.
 *
 * There were three: `ui.tsx::TypedConfirmation` (case-insensitive, a binding line), the
 * ops console's `TypeToConfirm` (exact, monospace), and a hand-rolled label-and-input
 * copied into a dozen panels. Each drifted on something a person notices — whether the
 * label names the phrase, whether the hint is announced, whether a match shows — so they
 * are one component now, and the two matching rules are a prop rather than two modules.
 *
 * ## What a typed confirmation is for
 *
 * It exists so a consequential action cannot be sent by a reflex click. That works only
 * while the phrase NAMES THE THING BEING DONE: a fixed word becomes muscle memory by the
 * third use, which is the reflex the control interrupts. So prefer a phrase that is
 * specific — a tier, a name, a count — and that changes when the target changes.
 *
 * ## Why it is not the API's header string
 *
 * The header (`X-Confirm-Action`) is a WIRE value the API builds and validates
 * (`apps/api/core/stepup`), and it may never carry an email address because headers land
 * in access logs (hard rule 6). This is what a person reads and types. Nothing here can
 * weaken the server's check; the worst a bug in this file can do is refuse a legitimate
 * operator.
 *
 * ## Two matching rules, chosen by the caller
 *
 * - `loose` (default): trimmed and case-insensitive. The phrase is a proof of attention,
 *   not a spelling test, and a confirmation that rejects "remove" for "REMOVE" teaches
 *   people to paste instead of read.
 * - `exact`: byte-for-byte. For a phrase that is itself an identifier the action is filed
 *   under (a provider's scrub reference, a lot id), where a near-miss names a different
 *   record, and for the ops levers whose word is part of their documented contract.
 */
export type ConfirmMatch = "loose" | "exact";

export function confirmationMatches(
  typed: string,
  phrase: string,
  match: ConfirmMatch = "loose",
): boolean {
  if (match === "exact") return typed === phrase;
  return typed.trim().toLowerCase() === phrase.trim().toLowerCase();
}

export interface TypedConfirmationProps {
  /** What the person must type. */
  phrase: string;
  value: string;
  onChange: (next: string) => void;
  /** One line on WHY this phrase, or what typing it commits to. Announced with the field. */
  hint?: ReactNode;
  disabled?: boolean;
  match?: ConfirmMatch;
  /**
   * The label, when the phrase itself should not be printed in it ("Type the lot id to
   * confirm" — the id is on screen already and is too long to read twice).
   */
  label?: string;
  /** Shown in an empty field. Defaults to the phrase when the label prints it. */
  placeholder?: string;
  /** `numeric` when the phrase is a count, so a phone offers its number pad. */
  inputMode?: "text" | "numeric";
  id?: string;
}

export function TypedConfirmation({
  phrase,
  value,
  onChange,
  hint,
  disabled,
  match = "loose",
  label,
  placeholder,
  inputMode,
  id,
}: TypedConfirmationProps) {
  const generated = useId();
  const inputId = id ?? generated;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const matched = value !== "" && phrase !== "" && confirmationMatches(value, phrase, match);
  return (
    <div>
      <label htmlFor={inputId} className={FIELD_LABEL}>
        {label ?? (
          <>
            Type <span className="font-mono font-semibold text-ink">{phrase}</span> to confirm
          </>
        )}
      </label>
      <input
        id={inputId}
        type="text"
        inputMode={inputMode}
        value={value}
        disabled={disabled}
        placeholder={placeholder ?? (label ? undefined : phrase)}
        aria-describedby={hintId}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize={phrase === phrase.toUpperCase() ? "characters" : "off"}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
        className={`${FIELD} font-mono ${matched ? "border-brand" : ""}`}
      />
      {hint ? (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}
