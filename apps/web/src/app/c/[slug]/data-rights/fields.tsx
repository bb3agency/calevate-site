"use client";

import { type ReactNode } from "react";

import { FIELD_HINT, FIELD_LABEL } from "@/components/ui";

/**
 * A form control with a PERSISTENT visible label, and a hint the control is described by.
 *
 * Both halves matter and only one of them is checkable by machine. axe accepts a
 * `placeholder` as an accessible name (tests/a11y.ts says so out loud), so a placeholder
 * "label" passes the gate and still disappears the moment someone starts typing — which
 * is WCAG 3.3.2's whole complaint, and on this screen the vanished text is the difference
 * between the export field and the erasure field. The hint sits OUTSIDE the label element
 * and is linked with `aria-describedby`, so the control's NAME stays two or three words
 * instead of a paragraph a screen reader has to read out before every keystroke.
 */
export function Field({
  id,
  label,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className ?? "max-w-sm"}>
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children}
      {hint && (
        <span id={`${id}-hint`} className={FIELD_HINT}>
          {hint}
        </span>
      )}
    </div>
  );
}

/** One counted figure, as a `<dl>` term and its value. */
export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}
