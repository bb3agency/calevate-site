"use client";

import type { ReactNode } from "react";

import { CHOICE_OFF, CHOICE_ON } from "./choiceCard";

/**
 * A CHOICE DRAWN AS A CARD: a real radio or checkbox underneath, so a group is one tab stop,
 * arrow keys move between options and a screen reader says "selected".
 *
 * Use it only when each option needs a sentence to be chosen well: the five consent sources,
 * the two reasons to take a number off do-not-call, the two ways calls reach the agent. Two to
 * four options that a word each can name belong in `SegmentedControl` with a `FIELD_HINT`
 * line under it; cards for those add height and invite the next author to do the same.
 *
 * The input is `sr-only`, which removes the browser's own focus ring (WCAG 2.4.7, failure
 * F78), so the label draws one with `has-[:focus-visible]`, offset so "focused" and "chosen"
 * stay two readable rings. `tests/contrast.test.ts` reads this at the source.
 *
 * Pass `label` and `hint` for the usual two lines, or `children` for content of its own.
 */
export function ChoiceCard({
  type = "radio",
  name,
  value,
  checked,
  onChange,
  disabled = false,
  label,
  hint,
  icon,
  children,
}: {
  type?: "radio" | "checkbox";
  name: string;
  value: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: ReactNode;
  hint?: ReactNode;
  /** A logo or tile above the label, when it helps the option be recognised. */
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <label
      className={`press relative flex min-w-0 cursor-pointer gap-3 rounded-card border px-4 py-3.5 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60 ${
        checked ? CHOICE_ON : CHOICE_OFF
      }`}
    >
      <input
        type={type}
        className="sr-only"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span
        aria-hidden
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center border-[1.5px] ${
          type === "radio" ? "rounded-full" : "rounded-[5px]"
        } ${checked ? "border-brand-strong bg-brand-strong" : "border-ink/30"}`}
      >
        {checked ? (
          type === "radio" ? (
            <span className="h-2 w-2 rounded-full bg-white" />
          ) : (
            <svg viewBox="0 0 256 256" width="11" height="11" fill="none" className="text-white">
              <polyline points="216 72 104 184 48 128" stroke="currentColor" strokeWidth="28" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )
        ) : null}
      </span>
      <span className="min-w-0 flex-1">
        {icon ? <span className="mb-2 block">{icon}</span> : null}
        {label !== undefined ? <span className="block text-body font-semibold text-ink">{label}</span> : null}
        {hint !== undefined ? <span className="mt-0.5 block text-meta text-ink-muted">{hint}</span> : null}
        {children}
      </span>
    </label>
  );
}

export type ChoiceCardOption<T extends string> = {
  value: T;
  label: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
};

/**
 * A radio group of `ChoiceCard`s under one legend. `columns` is the grid from `sm` up; on a
 * phone the cards always stack, since a sentence per option does not fit two abreast at 375.
 */
export function ChoiceCards<T extends string>({
  legend,
  legendClassName = "text-meta font-semibold text-ink",
  description,
  name,
  value,
  options,
  onChange,
  disabled = false,
  columns = "",
}: {
  legend: ReactNode;
  /** `"sr-only"` when a heading above already asks the question. */
  legendClassName?: string;
  /** One line under the legend, read with the group by a screen reader. */
  description?: ReactNode;
  name: string;
  value: T | "" | null;
  options: readonly ChoiceCardOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  /** e.g. `"sm:grid-cols-2"`. */
  columns?: string;
}) {
  const describedBy = description ? `${name}-description` : undefined;
  return (
    <fieldset aria-describedby={describedBy} className="min-w-0">
      <legend className={legendClassName}>{legend}</legend>
      {description ? (
        <p id={describedBy} className="mt-1 text-meta text-ink-muted">
          {description}
        </p>
      ) : null}
      <div className={`mt-2 grid gap-2 ${columns}`}>
        {options.map((option) => (
          <ChoiceCard
            key={option.value}
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={disabled}
            onChange={(on) => {
              if (on) onChange(option.value);
            }}
            label={option.label}
            hint={option.hint}
            icon={option.icon}
          />
        ))}
      </div>
    </fieldset>
  );
}
