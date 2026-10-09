"use client";

import type { ReactNode } from "react";
import { Plus, Trash2 } from "lucide-react";

import { FIELD_HINT, FIELD_LABEL, SECONDARY_BUTTON_SM } from "@/components/ui";

/**
 * One labelled control with its hint and its error WIRED to it (`aria-describedby`,
 * `aria-invalid`), so a screen reader announces the refusal while tabbing rather than
 * leaving the reader to find it.
 */
export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: true }) => ReactNode;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        ...(error ? { "aria-invalid": true as const } : {}),
      })}
      {hint && (
        <span id={hintId} className={FIELD_HINT}>
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} className="mt-1 block text-xs font-medium text-danger">
          {error}
        </span>
      )}
    </div>
  );
}

/**
 * A list of rows of the same shape — branches, services, people — with Add and Remove.
 *
 * Rows are keyed by index, which is safe here: every value lives in the draft and is passed
 * down, so a row holds no state of its own for React to mis-associate after a removal.
 */
export function RowList<T>({
  noun,
  rows,
  blank,
  addLabel,
  empty,
  disabled,
  columns = 2,
  onChange,
  children,
}: {
  /** What one row is, for the Remove button's name: "branch", "service". */
  noun: string;
  rows: T[];
  blank: () => T;
  addLabel: string;
  /** What an empty list says. Never blank: "none yet" is an answer. */
  empty: string;
  disabled: boolean;
  columns?: 1 | 2 | 3;
  onChange: (rows: T[]) => void;
  children: (row: T, index: number, patch: (change: Partial<T>) => void) => ReactNode;
}) {
  const grid = columns === 3 ? "sm:grid-cols-3" : columns === 2 ? "sm:grid-cols-2" : "";
  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-sm text-ink-muted">{empty}</p>}
      {rows.map((row, index) => (
        <div key={index} className="relative rounded-card border border-line p-3 pr-11">
          <button
            type="button"
            aria-label={`Remove ${noun} ${index + 1}`}
            disabled={disabled}
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
            className="press absolute right-1.5 top-1.5 inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-faint enabled:hover:bg-ink/[0.05] enabled:hover:text-danger disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </button>
          <div className={`grid gap-3 ${grid}`}>
            {children(row, index, (change) =>
              onChange(rows.map((current, i) => (i === index ? { ...current, ...change } : current))),
            )}
          </div>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange([...rows, blank()])}
        className={SECONDARY_BUTTON_SM}
      >
        <Plus aria-hidden className="h-3.5 w-3.5" />
        {addLabel}
      </button>
    </div>
  );
}
