"use client";

import { PipMark } from "@/components/illustration/pip";
import { SECONDARY_BUTTON, SECONDARY_BUTTON_SM } from "@/components/ui";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";

/** A suggestion chip: one of several example requests set in a row, so no mark on each. */
const CHIP =
  "rounded-full border border-line px-2.5 py-1 text-meta text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:min-h-11";

/**
 * "LET PIP DO THIS" — a small button beside a task that opens the side panel with
 * the request already written (D-694, inline suggestions).
 *
 * It prefills and never sends: the person sees the words, can change them, and presses
 * Ask. So the button costs nothing and does nothing on its own, which is why it can sit on
 * any screen without a confirmation of its own. The accessible name carries the request,
 * because "do this" means nothing to a screen reader that did not see what "this" is.
 *
 * `variant="chip"` is the same button as one of a row of example requests (the Script
 * page's ideas, D-820): its `label` is the example itself, so it carries no mark.
 */
export function AskAssistant({
  prompt,
  label = `Let ${ASSISTANT_NAME} do this`,
  variant = "button",
  size = "sm",
  disabled = false,
  className = "",
}: {
  /** The request, in the client's own words, as it will appear in the ask box. */
  prompt: string;
  label?: string;
  variant?: "button" | "chip";
  /** `md` beside full-size buttons; the chip has one size. */
  size?: "sm" | "md";
  disabled?: boolean;
  className?: string;
}) {
  const chip = variant === "chip";
  return (
    <button
      type="button"
      onClick={() => openAssistant({ prompt })}
      disabled={disabled}
      aria-label={chip ? `Let ${ASSISTANT_NAME} do this: ${prompt}` : `${label}: ${prompt}`}
      title={prompt}
      className={
        chip
          ? `${CHIP} ${className}`
          : `${size === "md" ? SECONDARY_BUTTON : SECONDARY_BUTTON_SM} inline-flex items-center gap-1.5 whitespace-nowrap ${className}`
      }
    >
      {!chip && <PipMark size={16} className="shrink-0" />}
      {label}
    </button>
  );
}
