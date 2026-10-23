"use client";

/**
 * ONE CHOICE FROM A FEW, IN A FORM, as a plain list of radios with a line of help each.
 * The size between the other two ways to choose one thing:
 *
 * - `SegmentedControl` — two to four options a word each can name, side by side.
 * - `RadioGroup` (this) — up to six options that need a short line to choose well, stacked.
 * - `ChoiceCard` — a few weighty options that each need a sentence or a logo.
 * - `Combobox` — many options, found by typing.
 *
 * Native radios in a `fieldset`, so arrow keys, one tab stop and "1 of 3, selected" come
 * from the browser. Ideas from uiarc's `radio-group` (MIT, see ./LICENSE); its Radix
 * primitive and sliding indicator are not needed for this.
 */

import { useId, type ReactNode } from "react";
import clsx from "clsx";

import { FieldMessage } from "@/components/formValidation";
import { FIELD_HINT, FIELD_LABEL } from "@/components/ui";

export type RadioOption = { value: string; label: ReactNode; hint?: ReactNode; disabled?: boolean };

export type RadioGroupProps = {
  /** The question, as the group's legend. */
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  options: RadioOption[];
  value: string | null;
  onChange: (value: string) => void;
  /** Lay the options in a row from `sm` up (only for short labels with no hints). */
  inline?: boolean;
  name?: string;
  disabled?: boolean;
  className?: string;
};

export function RadioGroup({
  label,
  hint,
  error,
  options,
  value,
  onChange,
  inline = false,
  name,
  disabled = false,
  className,
}: RadioGroupProps) {
  const uid = useId();
  const group = name ?? uid;
  const hintId = hint ? `${uid}-hint` : undefined;
  const errorId = error ? `${uid}-error` : undefined;
  return (
    <fieldset
      role="radiogroup"
      aria-labelledby={`${uid}-legend`}
      disabled={disabled}
      aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
      aria-invalid={error ? true : undefined}
      className={clsx("min-w-0", className)}
    >
      <legend id={`${uid}-legend`} className={FIELD_LABEL}>
        {label}
      </legend>
      {hint ? (
        <p id={hintId} className={FIELD_HINT}>
          {hint}
        </p>
      ) : null}
      <div className={clsx("mt-2 flex flex-col gap-1", inline && "sm:flex-row sm:flex-wrap sm:gap-x-5")}>
        {options.map((option) => {
          const optionHint = option.hint ? `${uid}-${option.value}-hint` : undefined;
          return (
            <label
              key={option.value}
              className={clsx(
                "flex min-h-9 cursor-pointer items-start gap-2.5 rounded-md py-1.5 touch:min-h-11",
                (option.disabled || disabled) && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="radio"
                name={group}
                value={option.value}
                checked={value === option.value}
                disabled={option.disabled}
                aria-describedby={optionHint}
                onChange={() => onChange(option.value)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-(--brand-strong) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
              />
              <span className="min-w-0">
                <span className="block text-sm text-ink">{option.label}</span>
                {option.hint ? (
                  <span id={optionHint} className="block text-xs text-ink-muted">
                    {option.hint}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>
      {error && errorId ? <FieldMessage id={errorId}>{error}</FieldMessage> : null}
    </fieldset>
  );
}
