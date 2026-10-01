"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { X } from "lucide-react";

import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/ui";

export type FlowStep = {
  id: string;
  /** The question this step asks, as a heading: "Who should this agent call?" */
  title: string;
  /** One short line under the title, if the question needs it. */
  hint?: ReactNode;
  content: ReactNode;
  /**
   * Runs when the reader presses Next. Return a sentence saying what to fix, or `null`
   * to move on. Field-level messages stay on the fields (`formValidation`); this is the
   * step's own gate.
   */
  validate?: () => string | null;
};

/**
 * A SHORT CREATE FLOW, ONE QUESTION AT A TIME: progress, Back and Next, a check before
 * each step is left, and a review step at the end whose button does the work.
 *
 * - Each step is a `<form>`, so Enter in a field is Next (and Submit on the last step).
 * - Moving between steps puts focus on the new step's heading, so a keyboard or
 *   screen-reader user starts at the question; a refused Next keeps focus where it was
 *   and announces the reason (`role="alert"`).
 * - On a phone the flow is full screen with the actions pinned to the bottom. That needs
 *   a way out, so it applies only when `onCancel` is given; without one the flow renders
 *   in place at every width.
 * - Nothing here talks to the server: `onSubmit` is the caller's mutation, `pending` its
 *   in-flight state and `error` its refusal, rendered above the buttons in the caller's
 *   (server's) words.
 */
export function StepFlow({
  label,
  steps,
  review,
  submitLabel,
  onSubmit,
  pending = false,
  error,
  onCancel,
  cancelLabel = "Cancel",
  className = "",
}: {
  /** What is being created: "New campaign". Names the flow and its progress bar. */
  label: string;
  steps: FlowStep[];
  /** The last step: what will be created, read back before the button that creates it. */
  review: { title?: string; content: ReactNode };
  /** The consequence as a verb: "Create campaign", never "Submit". */
  submitLabel: string;
  onSubmit: () => void;
  pending?: boolean;
  error?: ReactNode;
  onCancel?: () => void;
  cancelLabel?: string;
  className?: string;
}) {
  const all = [...steps, { id: "__review", title: review.title ?? "Check and confirm", content: review.content }];
  const [index, setIndex] = useState(0);
  const [refusal, setRefusal] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const step = all[index];
  const last = index === all.length - 1;
  const fullScreen = onCancel !== undefined;

  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    headingRef.current?.focus();
  }, [index]);

  const go = (to: number) => {
    moved.current = true;
    setRefusal(null);
    setIndex(to);
  };

  const next = (event: FormEvent) => {
    event.preventDefault();
    if (last) {
      if (!pending) onSubmit();
      return;
    }
    const problem = steps[index]?.validate?.() ?? null;
    if (problem) {
      setRefusal(problem);
      return;
    }
    go(index + 1);
  };

  const pct = Math.round(((index + 1) / all.length) * 100);

  return (
    <div
      className={`${
        fullScreen
          ? "fixed inset-0 z-40 flex flex-col overflow-y-auto bg-surface sm:static sm:z-auto sm:overflow-visible"
          : ""
      } sm:rounded-card sm:border sm:border-line sm:bg-surface sm:shadow-card ${className}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-ink">{label}</p>
          <p className="text-[12px] tabular-nums text-ink-muted">
            Step {index + 1} of {all.length}
          </p>
        </div>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            aria-label={cancelLabel}
            className="press flex h-9 w-9 items-center justify-center rounded-md text-ink-muted hover:bg-ink/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
        )}
      </div>
      <div
        role="progressbar"
        aria-label={`${label}: step ${index + 1} of ${all.length}`}
        aria-valuemin={1}
        aria-valuemax={all.length}
        aria-valuenow={index + 1}
        className="h-0.5 bg-ink/[0.06]"
      >
        <div
          className="h-full origin-left bg-brand transition-transform duration-(--duration-base) ease-out motion-reduce:transition-none"
          style={{ transform: `scaleX(${pct / 100})` }}
        />
      </div>

      <form noValidate onSubmit={next} className="flex flex-1 flex-col">
        <div key={step.id} className="settings-enter flex-1 space-y-4 px-4 py-6 sm:px-6">
          <div>
            <h2 ref={headingRef} tabIndex={-1} className="text-[18px] font-semibold tracking-tight text-ink focus-visible:outline-none">
              {step.title}
            </h2>
            {"hint" in step && step.hint ? (
              <p className="mt-1 text-[14px] text-ink-muted">{step.hint}</p>
            ) : null}
          </div>
          {step.content}
          {refusal && (
            <p role="alert" className="text-[13px] font-medium text-danger">
              {refusal}
            </p>
          )}
          {last && error}
        </div>
        <div
          className={`flex items-center justify-between gap-3 border-t border-line bg-surface px-4 py-3 sm:px-6 ${
            fullScreen ? "sticky bottom-0 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] sm:static sm:pb-3" : ""
          }`}
        >
          {index > 0 ? (
            <button type="button" onClick={() => go(index - 1)} className={SECONDARY_BUTTON} disabled={pending}>
              Back
            </button>
          ) : (
            <span />
          )}
          <button type="submit" className={PRIMARY_BUTTON} disabled={pending} aria-busy={pending || undefined}>
            {last ? (pending ? "Working…" : submitLabel) : "Next"}
          </button>
        </div>
      </form>
    </div>
  );
}
