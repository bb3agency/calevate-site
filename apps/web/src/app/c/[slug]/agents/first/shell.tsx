"use client";

import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { ArrowLeft, Check } from "lucide-react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";

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
 *
 * The primary action carries its own state (`status`, from `useActionFeedback`): pending on
 * the button, then its tick or "Try again". `pending` is the older boolean, read as status.
 */
export function StepScreen({
  title,
  hint,
  children,
  primary,
  onSubmit,
  pending = false,
  status,
  successLabel = "Saved",
  disabled = false,
  onBack,
  aside,
  eyebrow,
  barAtEnd = false,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  /** The consequence as a verb: "Build my agent", never "Next". Omitted with no `aside`: no bar. */
  primary?: ReactNode;
  onSubmit?: () => void;
  pending?: boolean;
  status?: FeedbackStatus;
  /** One past-tense word for the primary action's success face. */
  successLabel?: string;
  disabled?: boolean;
  onBack?: () => void;
  /** A second way on, beside the primary action ("Skip the rest and build"). */
  aside?: ReactNode;
  /** Where the step is within itself, above the question ("Question 2 of 3"). */
  eyebrow?: ReactNode;
  /** From `lg`, the bar closes the step where its content ends instead of sticking to the
   *  window: for a step that is read top to bottom, where a stuck bar sits over the lines
   *  the owner is reading. The phone keeps its pinned bar. */
  barAtEnd?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [title]);

  const shown: FeedbackStatus = status ?? (pending ? "pending" : "idle");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (shown !== "pending" && !disabled) onSubmit?.();
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
        <div className={`fixed inset-x-0 bottom-0 z-sticky border-t border-line bg-surface/95 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur supports-[backdrop-filter]:bg-surface/85 ${barAtEnd ? "lg:static lg:mt-6 lg:bg-transparent lg:pt-5 supports-[backdrop-filter]:lg:bg-transparent" : "lg:sticky lg:mt-4 lg:bg-app lg:pt-3 supports-[backdrop-filter]:lg:bg-app"} lg:px-0 lg:pb-4 lg:backdrop-blur-none`}>
          <div className="mx-auto flex max-w-xl flex-col gap-1.5 lg:mx-0 lg:flex-row lg:items-center lg:gap-4">
            {primary ? (
              <ActionButton
                type="submit"
                variant="primary-lg"
                status={shown}
                successLabel={successLabel}
                disabled={disabled}
                className="w-full lg:w-auto"
              >
                {primary}
              </ActionButton>
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
 * The four steps of a guided flow ("Meet your agent", D-855; the go-live guide, D-859).
 *
 * Narrow, it is four short bars and one line naming where the owner is ("Step 3 of 4 · Hear
 * it"). Wide, every step is named: a column beside the content from `lg`, or one row above
 * it joined by lines. The row switches on the width IT is given (a container query), not on
 * the window's: it shares its line with the screen's title and the way out, so at a laptop
 * width the window is wide while the rail is not, and four names forced into too little room
 * ran the joining lines through the labels. A finished step can be gone back to.
 */
export function StepRail({
  steps,
  current,
  onGo,
  layout = "column",
}: {
  /** Four steps: the narrow shape is four columns. */
  steps: readonly { id: string; label: string }[];
  current: number;
  onGo: (step: number) => void;
  /** Wide: a column beside the content, or one row above it joined by lines, which
   *  leaves the content the width a step's cards need. */
  layout?: "column" | "row";
}) {
  const row = layout === "row";
  const look = row ? ROW : COLUMN;
  const at = Math.min(current, steps.length - 1);
  return (
    <nav aria-label="Steps" className={look.nav}>
      <ol className={look.list}>
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
                className={`${look.label} whitespace-nowrap text-body ${here ? "font-medium text-ink" : done ? "text-ink-muted" : "text-ink-faint"}`}
              >
                {entry.label}
              </span>
              <span className={look.srLabel}>{entry.label}</span>
            </>
          );
          return (
            <li
              key={entry.id}
              aria-current={here ? "step" : undefined}
              className={`${look.item} ${row && index > 0 ? ROW.joined : ""}`}
            >
              {row && index > 0 ? (
                <span aria-hidden className={`${ROW.line} ${done || here ? "bg-brand-strong" : "bg-line"}`} />
              ) : null}
              <span aria-hidden className={`${look.bar} h-1 rounded-full ${done || here ? "bg-brand-strong" : "bg-line"}`} />
              {done ? (
                <button
                  type="button"
                  onClick={() => onGo(index)}
                  className={`press ${look.step} gap-2.5 rounded-md px-1 py-1 text-left hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand`}
                >
                  {tile}
                  <span className="sr-only">, done. Go back to it</span>
                </button>
              ) : (
                <span className={`${look.step} gap-2.5 px-1 py-1`}>{tile}</span>
              )}
            </li>
          );
        })}
      </ol>
      <p className={`mt-2 text-meta text-ink-muted ${look.where}`}>
        Step {at + 1} of {steps.length} · <span className="font-medium text-ink">{steps[at]?.label}</span>
      </p>
    </nav>
  );
}

/**
 * Each shape's classes, written out whole so Tailwind finds them. The row's switch is
 * `@min-[44rem]`: four names, their tiles and three joining lines at their 1.5rem floor need
 * about 42rem, and the spare keeps a label from meeting its line.
 */
const ROW = {
  nav: "@container",
  list: "grid grid-cols-4 gap-1.5 @min-[44rem]:flex @min-[44rem]:items-center @min-[44rem]:gap-0",
  item: "flex min-w-0 flex-col gap-1.5 @min-[44rem]:flex-row @min-[44rem]:items-center @min-[44rem]:gap-0",
  joined: "@min-[44rem]:flex-1",
  line: "mx-3 hidden h-px min-w-6 flex-1 @min-[44rem]:block",
  bar: "@min-[44rem]:hidden",
  step: "hidden shrink-0 items-center @min-[44rem]:flex",
  label: "hidden @min-[44rem]:inline",
  srLabel: "sr-only @min-[44rem]:hidden",
  where: "@min-[44rem]:hidden",
} as const;

const COLUMN = {
  nav: "",
  list: "grid grid-cols-4 gap-1.5 lg:grid-cols-1 lg:gap-1",
  item: "flex min-w-0 flex-col gap-1.5 lg:block",
  joined: "",
  line: "",
  bar: "lg:hidden",
  step: "hidden w-full items-center lg:flex",
  label: "hidden lg:inline",
  srLabel: "sr-only lg:hidden",
  where: "lg:hidden",
} as const;

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
