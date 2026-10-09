"use client";

import { BotMessageSquare } from "lucide-react";

import { SECONDARY_BUTTON_SM } from "@/components/ui";
import { openAssistant } from "@/lib/copilot/launcher";

/**
 * "LET THE ASSISTANT DO THIS" — a small button beside a task that opens the side panel with
 * the request already written (D-694, inline suggestions).
 *
 * It prefills and never sends: the person sees the words, can change them, and presses
 * Ask. So the button costs nothing and does nothing on its own, which is why it can sit on
 * any screen without a confirmation of its own. The accessible name carries the request,
 * because "do this" means nothing to a screen reader that did not see what "this" is.
 */
export function AskAssistant({
  prompt,
  label = "Let the assistant do this",
  className = "",
}: {
  /** The request, in the client's own words, as it will appear in the ask box. */
  prompt: string;
  label?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => openAssistant({ prompt })}
      aria-label={`${label}: ${prompt}`}
      title={prompt}
      className={`${SECONDARY_BUTTON_SM} inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}
    >
      <BotMessageSquare aria-hidden className="h-3.5 w-3.5 shrink-0 text-brand" />
      {label}
    </button>
  );
}
