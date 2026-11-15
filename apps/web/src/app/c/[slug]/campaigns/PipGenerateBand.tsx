"use client";

/**
 * The one move between the materials and the script (D-992): Pip writes the script from the
 * main task and the materials, and the owner reviews it below, part by part.
 */

import { PRIMARY_BUTTON } from "@/components/ui";

export function PipGenerateBand({
  onGenerate,
  busy,
  disabled,
  reason,
}: {
  onGenerate: () => void;
  busy: boolean;
  disabled: boolean;
  /** Why Generate waits (no main task yet, no permission). */
  reason?: string;
}) {
  return (
    <section
      aria-labelledby="pip-generate"
      className="flex flex-col gap-3 rounded-card border border-brand/40 bg-surface p-4 shadow-card sm:flex-row sm:items-center sm:justify-between sm:p-5"
    >
      <div className="min-w-0">
        <h2 id="pip-generate" className="text-heading text-ink">
          Let Pip, our AI agent, generate the script
        </h2>
        <p className="mt-0.5 text-meta text-ink-muted">
          {reason ?? "Pip reads your main task and materials and writes the script for your review."}
        </p>
      </div>
      <button
        type="button"
        className={`${PRIMARY_BUTTON} shrink-0`}
        disabled={disabled || busy}
        title={reason}
        onClick={onGenerate}
      >
        {busy ? "Generating…" : "Generate"}
      </button>
    </section>
  );
}
