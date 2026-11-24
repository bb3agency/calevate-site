"use client";

/**
 * The one move between the sources and the script (D-992): Pip writes the script from the
 * main task and the picked sources, and the owner reviews it below, part by part.
 */

import type { ReactNode } from "react";

import { ActionButton } from "@/components/arc/feedback";

export function PipGenerateBand({
  onGenerate,
  busy,
  disabled,
  reason,
  refusal,
  label = "Generate",
  inline = false,
  heading = "Let Pip, our AI agent, generate the script",
  from = "Pip writes it from your main task and sources.",
  beside,
}: {
  /** Shown before the button, such as the language Pip writes in. */
  beside?: ReactNode;
  /** The band's heading: what Pip will write. */
  heading?: string;
  /** What Pip writes it from, shown while nothing holds Generate back. */
  from?: string;
  /** Inside the Script section: a plain row, not a card of its own. */
  inline?: boolean;
  /** The button's word: Generate, or Try again after a failed draft. */
  label?: string;
  onGenerate: () => void;
  busy: boolean;
  disabled: boolean;
  /** Why Generate waits on this campaign (no main task yet, a draft to review first). */
  reason?: string;
  /** Why this person may not press it; the page's RestrictionNote already says it, so only the control carries it. */
  refusal?: string;
}) {
  return (
    <section
      aria-labelledby="pip-generate"
      className={
        inline
          ? "flex flex-col gap-3 rounded-card border border-line p-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:p-4"
          : "flex flex-col gap-3 border-y border-line py-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
      }
    >
      {/* The heading keeps a readable width; the choices beside Generate wrap under it first. */}
      <div className="min-w-0 sm:min-w-[14rem] sm:flex-1">
        {inline ? (
          <h3 id="pip-generate" className="text-body font-semibold text-ink">
            {heading}
          </h3>
        ) : (
          <h2 id="pip-generate" className="text-heading text-ink">
            {heading}
          </h2>
        )}
        <p className="mt-0.5 text-meta text-ink-muted">
          {reason ?? from}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-3">
      {beside}
      <ActionButton
        className="shrink-0"
        status={busy ? "pending" : "idle"}
        pendingLabel="Generating…"
        disabled={disabled}
        title={reason ?? refusal}
        onClick={onGenerate}
      >
        {label}
      </ActionButton>
      </div>
    </section>
  );
}
