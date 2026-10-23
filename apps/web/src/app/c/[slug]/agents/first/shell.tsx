"use client";

import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, Check } from "lucide-react";

import { PRIMARY_BUTTON_LG } from "@/components/ui";

/**
 * ONE STEP OF "MEET YOUR AGENT": its question as the heading, what it needs, and its one
 * primary action.
 *
 * On a phone the action sits in a bar pinned to the bottom, in the thumb's reach, padded for
 * the home indicator (`env(safe-area-inset-bottom)`); the content keeps room under it so the
 * last field is never hidden. From `lg` up the bar is part of the column and sticks to the
 * bottom of the window, so on a laptop screen the action is in view even when the step runs
 * a little longer than the screen.
 *
 * Each step is a form, so Enter in a field is the primary action. Moving to a step puts focus
 * on its heading, so a keyboard or screen-reader user starts at the question.
 */
export function StepScreen({
  title,
  hint,
  children,
  primary,
  onSubmit,
  pending = false,
  disabled = false,
  onBack,
  aside,
  eyebrow,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  /** The consequence as a verb: "Build my agent", never "Next". Omitted with no `aside`: no bar. */
  primary?: ReactNode;
  onSubmit?: () => void;
  pending?: boolean;
  disabled?: boolean;
  onBack?: () => void;
  /** A second way on, beside the primary action ("Skip the rest and build"). */
  aside?: ReactNode;
  /** Where the step is within itself, above the question ("Question 2 of 3"). */
  eyebrow?: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [title]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!pending && !disabled) onSubmit?.();
  };

  return (
    <form noValidate onSubmit={submit} className={`min-w-0 lg:pb-0 ${primary || aside ? "pb-36" : "pb-4"}`}>
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="press -ml-2 mb-2 inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-meta font-medium text-ink-muted transition-colors duration-(--duration-fast) hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Back
        </button>
      ) : null}
      {eyebrow ? <div className="mb-1">{eyebrow}</div> : null}
      <h2 ref={heading} tabIndex={-1} className="text-balance text-title text-ink focus:outline-none">
        {title}
      </h2>
      {hint ? <div className="mt-1 max-w-prose text-body text-ink-muted">{hint}</div> : null}
      <div className="mt-5 space-y-5">{children}</div>
      {primary || aside ? (
        <div className="fixed inset-x-0 bottom-0 z-sticky border-t border-line bg-surface/95 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur supports-[backdrop-filter]:bg-surface/85 lg:sticky lg:mt-4 lg:bg-app lg:px-0 lg:pt-3 lg:pb-4 lg:backdrop-blur-none supports-[backdrop-filter]:lg:bg-app">
          <div className="mx-auto flex max-w-xl flex-col gap-1.5 lg:mx-0 lg:flex-row lg:items-center lg:gap-4">
            {primary ? (
              <button
                type="submit"
                disabled={disabled || pending}
                aria-busy={pending || undefined}
                className={`${PRIMARY_BUTTON_LG} w-full justify-center lg:w-auto`}
              >
                {primary}
              </button>
            ) : null}
            {aside ? (
              <div className="flex flex-wrap items-center justify-center gap-x-4 lg:justify-start">{aside}</div>
            ) : null}
          </div>
        </div>
      ) : null}
    </form>
  );
}

/**
 * The four steps of a guided flow ("Meet your agent", D-855; the go-live guide, D-859). A row
 * of four on a phone (the current one named under it), a column with every name from `lg`. A
 * finished step can be gone back to.
 */
export function StepRail({
  steps,
  current,
  onGo,
  layout = "column",
}: {
  /** Four steps: the phone row is four columns. */
  steps: readonly { id: string; label: string }[];
  current: number;
  onGo: (step: number) => void;
  /** From `lg`: a column beside the content, or one row above it joined by lines, which
   *  leaves the content the width a step's cards need. */
  layout?: "column" | "row";
}) {
  const row = layout === "row";
  return (
    <nav aria-label="Steps">
      <ol
        className={`grid grid-cols-4 gap-1.5 ${row ? "lg:flex lg:items-center lg:gap-0" : "lg:grid-cols-1 lg:gap-1"}`}
      >
        {steps.map((entry, index) => {
          const done = index < current;
          const here = index === current;
          const tile = (
            <>
              <span
                aria-hidden
                className={`grid h-7 w-7 shrink-0 place-items-center rounded-[8px] border text-[12px] font-medium tabular-nums ${
                  done
                    ? "border-brand-strong bg-brand-strong text-white"
                    : here
                      ? "border-ink/40 text-ink"
                      : "border-line text-ink-faint"
                }`}
              >
                {done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : index + 1}
              </span>
              <span
                className={`hidden whitespace-nowrap text-body lg:inline ${here ? "font-medium text-ink" : done ? "text-ink-muted" : "text-ink-faint"}`}
              >
                {entry.label}
              </span>
              <span className="sr-only lg:hidden">{entry.label}</span>
            </>
          );
          const bar = (
            <span
              aria-hidden
              className={`h-1 rounded-full lg:hidden ${done || here ? "bg-brand-strong" : "bg-line"}`}
            />
          );
          return (
            <li
              key={entry.id}
              aria-current={here ? "step" : undefined}
              className={`flex min-w-0 flex-col gap-1.5 ${row ? `lg:flex-row lg:items-center lg:gap-0 ${index > 0 ? "lg:flex-1" : ""}` : "lg:block"}`}
            >
              {row && index > 0 ? (
                <span
                  aria-hidden
                  className={`mx-3 hidden h-px min-w-6 flex-1 lg:block ${done || here ? "bg-brand-strong" : "bg-line"}`}
                />
              ) : null}
              {bar}
              {done ? (
                <button
                  type="button"
                  onClick={() => onGo(index)}
                  className={`press hidden items-center gap-2.5 rounded-md px-1 py-1 text-left hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand lg:flex ${row ? "shrink-0" : "w-full"}`}
                >
                  {tile}
                  <span className="sr-only">, done. Go back to it</span>
                </button>
              ) : (
                <span className={`hidden items-center gap-2.5 px-1 py-1 lg:flex ${row ? "shrink-0" : ""}`}>{tile}</span>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-meta text-ink-muted lg:hidden">
        Step {Math.min(current, steps.length - 1) + 1} of {steps.length}:{" "}
        <span className="font-medium text-ink">{steps[Math.min(current, steps.length - 1)]?.label}</span>
      </p>
    </nav>
  );
}

/** The first run's cards are the console's one choice card. */
export { ChoiceCard } from "@/components/console/choiceCards";

/**
 * A small pill choice for a list of options (trade choices, days, the extra languages). A
 * checkbox pill shows a tick when chosen, so "chosen" is not carried by colour alone
 * (WCAG 1.4.1); a radio pill is one of a set and its fill says which.
 */
export function ChipChoice({
  type,
  name,
  value,
  checked,
  onChange,
  children,
  disabled = false,
  size = "md",
}: {
  type: "radio" | "checkbox";
  name: string;
  value: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
  size?: "sm" | "md";
}) {
  return (
    <label
      className={`press inline-flex cursor-pointer select-none items-center gap-1.5 rounded-full border transition-colors duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand has-[:focus-visible]:ring-offset-1 ${
        size === "sm" ? "min-h-9 px-3 text-meta touch:min-h-11" : "min-h-10 px-3.5 text-body touch:min-h-11"
      } ${
        checked
          ? "border-brand-strong bg-brand-soft font-medium text-brand-strong"
          : "border-line bg-surface text-ink hover:border-ink/30"
      } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <input
        type={type}
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="sr-only"
      />
      {type === "checkbox" && checked ? <Check aria-hidden className="-ml-0.5 h-3.5 w-3.5" strokeWidth={2.5} /> : null}
      {children}
    </label>
  );
}

/**
 * ONE TICK BEFORE THE CALL: a real checkbox in a row of a single bordered list, so the
 * agreements, the pledge and "this number is mine" read as one short checklist rather than
 * three tall cards. `extra` holds the row's "Read it" link, outside the label's sentence.
 */
export function TickRow({
  name,
  checked,
  onChange,
  label,
  hint,
  extra,
}: {
  name: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          name={name}
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          className="peer sr-only"
        />
        <span
          aria-hidden
          className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[5px] border-[1.5px] transition-colors duration-(--duration-fast) peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2 ${
            checked ? "border-brand-strong bg-brand-strong text-white" : "border-ink/30 bg-surface"
          }`}
        >
          {checked ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
        </span>
        <span className="min-w-0">
          <span className="block text-body text-ink">{label}</span>
          {hint ? <span className="block text-meta text-ink-muted">{hint}</span> : null}
        </span>
      </label>
      {extra ? <div className="shrink-0">{extra}</div> : null}
    </li>
  );
}
