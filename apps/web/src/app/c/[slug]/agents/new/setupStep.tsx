"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";

import { SECONDARY_BUTTON } from "@/components/ui";

import { StepRail } from "../first/shell";

/**
 * THE NEW-AGENT FLOW'S FRAME: the four steps' rail, and one step's heading, body and actions.
 *
 * Accessibility follows the stepper guidance we checked (customer.io Pluma stepper,
 * https://pluma.customer.io/components/stepper/accessibility; GOV.UK question pages,
 * https://design-system.service.gov.uk/patterns/question-pages, read 4 Nov 2026): the current
 * step is `aria-current="step"` in an ordered list with "Step n of 4" in words (`StepRail`),
 * each step is one question as its heading with Back above it and the way on below it, and
 * focus moves to that heading when the step (or its title, as the Script step's wait ends)
 * changes, so a keyboard or screen-reader user starts at the question.
 *
 * Unlike `StepScreen` (`../first/shell`), a step here is not one `<form>`: the Voice and Notes
 * steps hold the agent tab's own forms, which cannot nest inside another.
 */

export const NEW_AGENT_STEPS = [
  { id: "job", label: "Job" },
  { id: "voice", label: "Voice" },
  { id: "script", label: "Script" },
  { id: "notes", label: "Notes" },
] as const;

/** The rail. Step 1 created the agent, so it is shown done and is never gone back to. */
export function NewAgentRail({ current, onGo }: { current: number; onGo?: (step: number) => void }) {
  return (
    <StepRail
      steps={NEW_AGENT_STEPS}
      current={current}
      layout="row"
      onGo={(step) => onGo?.(step)}
      canGo={(step) => step > 0 && onGo !== undefined}
    />
  );
}

export function SetupStep({
  title,
  hint,
  onBack,
  actions,
  children,
}: {
  title: string;
  hint?: ReactNode;
  onBack?: () => void;
  /** The way on: the primary action first, then Skip. */
  actions: ReactNode;
  children?: ReactNode;
}) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, [title]);

  return (
    <section aria-labelledby={id} className="min-w-0">
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
      <h2 id={id} ref={heading} tabIndex={-1} className="text-balance text-title text-ink focus:outline-none">
        {title}
      </h2>
      {hint ? <p className="mt-1 max-w-prose text-body text-ink-muted">{hint}</p> : null}
      {children ? <div className="mt-5 space-y-5">{children}</div> : null}
      <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-line pt-5">{actions}</div>
    </section>
  );
}

/** Skip: on to the next step, nothing saved. Everything stays changeable on the agent's tabs. */
export function SkipButton({ onSkip, label = "Skip" }: { onSkip: () => void; label?: string }) {
  return (
    <button type="button" onClick={onSkip} className={SECONDARY_BUTTON}>
      {label}
    </button>
  );
}
