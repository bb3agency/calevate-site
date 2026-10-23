"use client";

/**
 * A SMALL BOUNDED COUNT: calls at the same time (1-10), a call cap in seconds, retries.
 * A spinbutton with minus and plus, arrow keys (Shift for a big step), PageUp/PageDown and
 * Home/End, and typing that is applied when the person leaves the box or presses Enter.
 * Adapted from uiarc's `number-field` (MIT, see ./LICENSE): the rolling digits, strain
 * kick and label scrubbing are dropped, steppers are 44px on touch, digits are grouped the
 * Indian way (en-IN) and every string is a prop.
 *
 * NEVER FOR MONEY. The value is a JS number, which is exact for counts and wrong for
 * rupees (hard rule 7); money is `MoneyInput`, which holds a decimal string.
 */

import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Minus, Plus } from "lucide-react";
import clsx from "clsx";

import { FIELD_GROUP } from "@/components/ui";

import { Field } from "./field";

export type NumberFieldProps = {
  label: string;
  hint?: string;
  error?: string | null;
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  /** Shift+Arrow and PageUp/PageDown. Default ten steps. */
  largeStep?: number;
  /** A unit after the number, shown and spoken: "seconds", "calls". */
  unit?: string;
  /** Allow clearing the box to "no value". */
  optional?: boolean;
  decreaseLabel?: (label: string) => string;
  increaseLabel?: (label: string) => string;
  /** Said under the box when typing went past a limit and was pulled back. */
  clampedMessage?: (limit: string) => string;
  disabled?: boolean;
  className?: string;
};

function decimalsOf(step: number): number {
  const text = String(step);
  const dot = text.indexOf(".");
  return dot < 0 ? 0 : text.length - dot - 1;
}

export function NumberField({
  label,
  hint,
  error,
  value,
  onChange,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  step = 1,
  largeStep = step * 10,
  unit,
  optional = false,
  decreaseLabel = (what) => `Decrease ${what}`,
  increaseLabel = (what) => `Increase ${what}`,
  clampedMessage = (limit) => `Kept to ${limit}, the limit here.`,
  disabled = false,
  className,
}: NumberFieldProps) {
  const decimals = decimalsOf(step);
  const format = useMemo(
    () => new Intl.NumberFormat("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
    [decimals],
  );
  const shown = value === null ? "" : format.format(value);
  const [draft, setDraft] = useState(shown);
  const [typing, setTyping] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    if (!typing) setDraft(shown);
  }, [shown, typing]);

  // Snap to the step grid from `min`, round away float noise, then hold inside the limits.
  const settle = (raw: number): number => {
    const snapped = min + Math.round((raw - min) / step) * step;
    const rounded = Number(snapped.toFixed(decimals));
    return Math.min(max, Math.max(min, rounded));
  };
  const nudge = (by: number) => {
    if (disabled) return;
    const next = settle((value ?? min) + by);
    setNote(null);
    setTyping(false);
    if (next !== value) onChange(next);
  };
  const commitDraft = () => {
    setTyping(false);
    const text = draft.replace(/[,\s]/g, "");
    if (text === "") {
      if (optional) onChange(null);
      else setDraft(shown);
      return;
    }
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) {
      setDraft(shown);
      return;
    }
    const next = settle(parsed);
    setNote(next !== parsed && (parsed > max || parsed < min) ? clampedMessage(format.format(next)) : null);
    if (next !== value) onChange(next);
    setDraft(format.format(next));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const big = event.shiftKey ? largeStep : step;
    const actions: Record<string, () => void> = {
      ArrowUp: () => nudge(big),
      ArrowDown: () => nudge(-big),
      PageUp: () => nudge(largeStep),
      PageDown: () => nudge(-largeStep),
      Home: () => min !== undefined && nudge(min - (value ?? min)),
      End: () => max !== Number.MAX_SAFE_INTEGER && nudge(max - (value ?? min)),
      Enter: commitDraft,
    };
    const run = actions[event.key];
    if (run) {
      event.preventDefault();
      run();
    } else if (event.key === "Escape" && typing) {
      event.preventDefault();
      setTyping(false);
      setDraft(shown);
    }
  };

  const atMin = value !== null && value <= min;
  const atMax = value !== null && value >= max;
  const stepper =
    "grid w-9 shrink-0 place-items-center text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand aria-disabled:cursor-not-allowed aria-disabled:text-ink-faint aria-disabled:hover:bg-transparent touch:w-11";
  return (
    <Field label={label} hint={hint} error={error ?? note} className={className}>
      {(control) => (
        <div className={clsx(FIELD_GROUP, "mt-1 w-full max-w-56", disabled && "bg-surface-muted")}>
          <button
            type="button"
            tabIndex={-1}
            aria-label={decreaseLabel(label)}
            aria-controls={control.id}
            aria-disabled={atMin || disabled || undefined}
            onClick={() => !atMin && nudge(-step)}
            className={clsx(stepper, "border-r border-line")}
          >
            <Minus aria-hidden className="h-4 w-4" />
          </button>
          <input
            {...control}
            role="spinbutton"
            inputMode={decimals > 0 || min < 0 ? "decimal" : "numeric"}
            aria-valuenow={value ?? undefined}
            aria-valuemin={min}
            aria-valuemax={max === Number.MAX_SAFE_INTEGER ? undefined : max}
            aria-valuetext={value === null ? undefined : `${format.format(value)}${unit ? ` ${unit}` : ""}`}
            disabled={disabled}
            value={draft}
            onChange={(event) => {
              setTyping(true);
              setNote(null);
              setDraft(event.target.value);
            }}
            onBlur={commitDraft}
            onKeyDown={onKeyDown}
            className="min-w-0 flex-1 border-0 bg-transparent px-2 py-1.5 text-center text-sm tabular-nums text-ink outline-none focus:outline-none disabled:text-ink-faint"
          />
          {unit ? (
            <span aria-hidden className="flex items-center pr-2 text-sm text-ink-muted">
              {unit}
            </span>
          ) : null}
          <button
            type="button"
            tabIndex={-1}
            aria-label={increaseLabel(label)}
            aria-controls={control.id}
            aria-disabled={atMax || disabled || undefined}
            onClick={() => !atMax && nudge(step)}
            className={clsx(stepper, "border-l border-line")}
          >
            <Plus aria-hidden className="h-4 w-4" />
          </button>
        </div>
      )}
    </Field>
  );
}
