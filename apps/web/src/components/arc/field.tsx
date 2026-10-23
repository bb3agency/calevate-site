"use client";

/**
 * The frame every kit input sits in: a visible label above, an optional hint under it,
 * the control, and the field's error message under the control.
 *
 * The control is rendered by a render prop that receives the ids and ARIA it must carry,
 * so the wiring is written once: `aria-describedby` lists the hint and the error,
 * `aria-invalid` is set while there is an error, and the error is drawn by
 * `FieldMessage` (components/formValidation.tsx), the one way a field-level refusal is
 * shown in this app. A form using `useFormValidation` passes `validation.message(name)`
 * as `error`.
 *
 * Label above, always (form-design): a placeholder is not a label and disappears on input.
 */

import { useId, type ReactNode } from "react";
import clsx from "clsx";

import { FieldMessage } from "@/components/formValidation";
import { FIELD, FIELD_HINT, FIELD_LABEL } from "@/components/ui";

export type FieldControlProps = {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
};

export type FieldProps = {
  /** The visible label. */
  label: ReactNode;
  /** Keep the label for assistive tech only (a search box whose purpose the screen shows). */
  hideLabel?: boolean;
  /** One line of help under the label, read with the control. */
  hint?: ReactNode;
  /** The refusal for this field, in words that say how to fix it. */
  error?: string | null;
  /** Fixed id for the control; one is generated when omitted. */
  id?: string;
  className?: string;
  children: (control: FieldControlProps) => ReactNode;
};

export function Field({ label, hideLabel = false, hint, error, id, className, children }: FieldProps) {
  const generated = useId();
  const controlId = id ?? `${generated}-control`;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={clsx("min-w-0", className)}>
      <label htmlFor={controlId} className={hideLabel ? "sr-only" : FIELD_LABEL}>
        {label}
      </label>
      {hint ? (
        <span id={hintId} className={clsx(FIELD_HINT, "mt-0.5")}>
          {hint}
        </span>
      ) : null}
      {children({
        id: controlId,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
      })}
      {error && errorId ? <FieldMessage id={errorId}>{error}</FieldMessage> : null}
    </div>
  );
}

/** `FIELD` without its top margin, for a control inside a positioned wrapper that carries the gap (so affixes and icons line up with the box). */
export const FIELD_FLUSH = FIELD.replace(/^mt-1 /, "");
