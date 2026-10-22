"use client";

import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

import { PRIMARY_BUTTON_LG } from "@/components/ui";

/**
 * ONE STEP OF "MEET YOUR AGENT": its question as the heading, what it needs, and its one
 * primary action.
 *
 * On a phone the action sits in a bar pinned to the bottom, in the thumb's reach, padded for
 * the home indicator (`env(safe-area-inset-bottom)`); the content keeps room under it so the
 * last field is never hidden. From `lg` up the bar is part of the column.
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
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  /** The consequence as a verb: "Build my agent", never "Next". Omitted: no bar. */
  primary?: ReactNode;
  onSubmit?: () => void;
  pending?: boolean;
  disabled?: boolean;
  onBack?: () => void;
  /** A quiet second way on, under the primary action ("Skip all and build"). */
  aside?: ReactNode;
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
    <form noValidate onSubmit={submit} className="min-w-0 pb-28 lg:pb-0">
      {onBack ? (
        <button
          type="button"
          onClick={onBack}
          className="press -ml-1 mb-3 inline-flex items-center gap-1 rounded-sm px-1 text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          Back
        </button>
      ) : null}
      <h2 ref={heading} tabIndex={-1} className="text-balance text-title text-ink focus:outline-none">
        {title}
      </h2>
      {hint ? <div className="mt-1.5 max-w-prose text-body text-ink-muted">{hint}</div> : null}
      <div className="mt-6 space-y-6">{children}</div>
      {primary ? (
        <div className="fixed inset-x-0 bottom-0 z-sticky border-t border-line bg-surface/95 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur supports-[backdrop-filter]:bg-surface/85 lg:static lg:mt-8 lg:border-0 lg:bg-transparent lg:p-0 lg:backdrop-blur-none">
          <div className="mx-auto flex max-w-xl flex-col gap-2 lg:mx-0 lg:flex-row lg:items-center lg:gap-4">
            <button
              type="submit"
              disabled={disabled || pending}
              aria-busy={pending || undefined}
              className={`${PRIMARY_BUTTON_LG} w-full justify-center lg:w-auto`}
            >
              {primary}
            </button>
            {aside ? <div className="flex justify-center lg:justify-start">{aside}</div> : null}
          </div>
        </div>
      ) : null}
    </form>
  );
}

/** A choice drawn as a card: a real radio or checkbox underneath, so it is one tab stop per
 *  group, arrow keys move, and a screen reader says "selected". */
export function ChoiceCard({
  type,
  name,
  value,
  checked,
  onChange,
  children,
}: {
  type: "radio" | "checkbox";
  name: string;
  value: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label
      className={`press relative flex cursor-pointer gap-3 rounded-card border bg-surface p-4 transition-[border-color,box-shadow] duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand ${
        checked ? "border-brand-strong shadow-card" : "border-line hover:border-ink/30"
      }`}
    >
      <input
        type={type}
        name={name}
        value={value}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="sr-only"
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
      <span className="min-w-0 flex-1">{children}</span>
    </label>
  );
}

/** A small pill choice for a list of options (languages, trade choices, closed days). */
export function ChipChoice({
  type,
  name,
  value,
  checked,
  onChange,
  children,
  disabled = false,
}: {
  type: "radio" | "checkbox";
  name: string;
  value: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label
      className={`press inline-flex min-h-11 cursor-pointer select-none items-center gap-1.5 rounded-full border px-4 text-body transition-colors duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand ${
        checked ? "border-brand-strong bg-brand-soft font-medium text-brand-strong" : "border-line text-ink hover:border-ink/30"
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
      {children}
    </label>
  );
}
