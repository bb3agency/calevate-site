"use client";

/**
 * A RUPEE AMOUNT a person types: a top-up, a spending cap, a rate on the admin rate card.
 *
 * Rewritten from uiarc's `money-input` idea (MIT, see ./LICENSE) for hard rule 7. Arc held
 * paise as a JS number and emitted `major` as a float, grouped in threes and defaulted to
 * USD; here the value IS a decimal string from end to end:
 *
 * - `value` / `onChange` carry the canonical string the API takes: "12500.00", "" when
 *   empty. Nothing is ever passed through `Number`.
 * - Limits (`min`, `max`) are strings too and are compared as whole paise in `BigInt`.
 * - The box groups the Indian way while you type (1,25,000) and keeps the caret where it
 *   was among the digits; the ₹ is a fixed affix, never part of the value.
 * - The limit message is said on leaving the box, not on every keystroke (form-design).
 *
 * `paise={false}` takes whole rupees only (a top-up pack, a cap); the default allows two
 * decimals. A per-minute rate with four decimals is not this field: it is a rate string
 * the operator types exactly and `formatRupeeRate` prints.
 */

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import clsx from "clsx";

import { FIELD_GROUP, FIELD_GROUP_AFFIX, FIELD_GROUP_INPUT, formatINR, formatWholeCount } from "@/components/ui";

import { Field } from "./field";

const MAX_WHOLE_DIGITS = 12;

/** Whole paise of a canonical or typed amount ("1,25,000.5" → 12500050n), or null. */
export function toPaise(amount: string): bigint | null {
  const text = amount.replace(/[,\s]/g, "");
  const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(text);
  if (!match) return null;
  const [, whole, fraction = ""] = match;
  return BigInt(whole) * BigInt(100) + BigInt(`${fraction}00`.slice(0, 2));
}

/** −1, 0 or 1, exactly, for two amounts written as decimal strings. */
export function compareMoney(a: string, b: string): -1 | 0 | 1 {
  const left = toPaise(a);
  const right = toPaise(b);
  if (left === null || right === null) throw new Error("compareMoney: not an amount");
  return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * The canonical string for what was typed: "125000" → "125000.00", "12.5" → "12.50".
 * `""` for an empty box; `null` for text that is not an amount.
 */
export function canonicalMoney(typed: string, paise = true): string | null {
  const text = typed.replace(/[,\s]/g, "");
  if (text === "") return "";
  const match = paise ? /^(\d+)(?:\.(\d{0,2}))?$/.exec(text) : /^(\d+)$/.exec(text);
  if (!match) return null;
  const whole = match[1].replace(/^0+(?=\d)/, "");
  return paise ? `${whole}.${`${match[2] ?? ""}00`.slice(0, 2)}` : `${whole}.00`;
}

/** The box's text for what was typed: the whole part grouped 1,25,000, the fraction as typed. */
export function groupTyped(typed: string): string {
  const text = typed.replace(/[,\s]/g, "");
  const dot = text.indexOf(".");
  const whole = (dot < 0 ? text : text.slice(0, dot)).replace(/^0+(?=\d)/, "");
  const grouped = whole === "" ? "" : formatWholeCount(whole);
  return dot < 0 ? grouped : `${grouped || "0"}.${text.slice(dot + 1)}`;
}

/** What the box shows for a canonical value when it is not being edited. */
function displayOf(value: string, paise: boolean): string {
  if (value === "") return "";
  const [whole = "0", fraction = "00"] = value.split(".");
  const grouped = formatWholeCount(whole);
  return paise && fraction !== "00" ? `${grouped}.${fraction}` : grouped;
}

export type MoneyInputProps = {
  label: string;
  hideLabel?: boolean;
  hint?: string;
  /** A refusal from the form or the server; the field's own range message shows otherwise. */
  error?: string | null;
  /** Canonical decimal string ("12500.00"), or "" for none. */
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  /** Allow two decimals. False for whole rupees. */
  paise?: boolean;
  /** Amounts offered as one-tap choices beside the box, as canonical strings. */
  quickAmounts?: string[];
  quickAmountsLabel?: string;
  belowMinMessage?: (min: string) => string;
  aboveMaxMessage?: (max: string) => string;
  disabled?: boolean;
  required?: boolean;
  name?: string;
  className?: string;
};

export function MoneyInput({
  label,
  hideLabel,
  hint,
  error,
  value,
  onChange,
  min,
  max,
  paise = true,
  quickAmounts,
  quickAmountsLabel = "Common amounts",
  belowMinMessage = (limit) => `Enter at least ${formatINR(limit)}.`,
  aboveMaxMessage = (limit) => `Enter at most ${formatINR(limit)}.`,
  disabled = false,
  required,
  name,
  className,
}: MoneyInputProps) {
  const input = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const [draft, setDraft] = useState(() => displayOf(value, paise));
  const [focused, setFocused] = useState(false);
  const [rangeProblem, setRangeProblem] = useState<string | null>(null);

  // A value set from outside (a quick amount, a reset) replaces the box when not typing.
  useEffect(() => {
    if (!focused) setDraft(displayOf(value, paise));
  }, [value, paise, focused]);

  // Put the caret back after the same number of digits it followed before regrouping.
  useEffect(() => {
    const el = input.current;
    if (caret.current === null || !el) return;
    let digits = caret.current;
    let at = 0;
    while (at < draft.length && digits > 0) {
      if (/[\d.]/.test(draft[at])) digits -= 1;
      at += 1;
    }
    el.setSelectionRange(at, at);
    caret.current = null;
  }, [draft]);

  const rangeCheck = (canonical: string) => {
    if (canonical === "") return null;
    if (min !== undefined && compareMoney(canonical, min) < 0) return belowMinMessage(min);
    if (max !== undefined && compareMoney(canonical, max) > 0) return aboveMaxMessage(max);
    return null;
  };

  const onType = (event: ChangeEvent<HTMLInputElement>) => {
    const typed = event.target.value;
    const bare = typed.replace(/[,\s]/g, "");
    // Refuse the keystroke rather than accept text that is not an amount.
    const shape = paise ? /^\d*(?:\.\d{0,2})?$/ : /^\d*$/;
    const whole = bare.split(".")[0] ?? "";
    if (!shape.test(bare) || whole.length > MAX_WHOLE_DIGITS) return;
    const before = typed.slice(0, event.target.selectionStart ?? typed.length);
    caret.current = before.replace(/[^\d.]/g, "").length;
    setDraft(groupTyped(bare));
    setRangeProblem(null);
    const canonical = canonicalMoney(bare, paise);
    if (canonical !== null && canonical !== value) onChange(canonical);
  };

  const shownError = error ?? rangeProblem;
  return (
    <Field label={label} hideLabel={hideLabel} hint={hint} error={shownError} className={className}>
      {(control) => (
        <div className="mt-1 space-y-2">
          <div className={clsx(FIELD_GROUP, "w-full max-w-64", disabled && "bg-surface-muted")}>
            <span aria-hidden className={FIELD_GROUP_AFFIX}>
              ₹
            </span>
            <input
              {...control}
              ref={input}
              type="text"
              inputMode={paise ? "decimal" : "numeric"}
              autoComplete="off"
              name={name}
              required={required}
              disabled={disabled}
              value={draft}
              onChange={onType}
              onFocus={() => setFocused(true)}
              onBlur={() => {
                setFocused(false);
                setRangeProblem(rangeCheck(value));
              }}
              className={clsx(FIELD_GROUP_INPUT, "pl-10 tabular-nums disabled:text-ink-faint")}
            />
          </div>
          {quickAmounts && quickAmounts.length > 0 ? (
            <div role="group" aria-label={quickAmountsLabel} className="flex flex-wrap gap-2">
              {quickAmounts.map((amount) => {
                const on = value !== "" && compareMoney(value, amount) === 0;
                return (
                  <button
                    key={amount}
                    type="button"
                    aria-pressed={on}
                    disabled={disabled}
                    onClick={() => {
                      onChange(amount);
                      setRangeProblem(rangeCheck(amount));
                    }}
                    className={clsx(
                      "press rounded-full border px-3 py-1 text-meta font-medium tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11",
                      on ? "border-ink bg-ink/[0.06] text-ink" : "border-line bg-surface text-ink-muted hover:bg-ink/[0.04]",
                    )}
                  >
                    {formatINR(amount)}
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      )}
    </Field>
  );
}
