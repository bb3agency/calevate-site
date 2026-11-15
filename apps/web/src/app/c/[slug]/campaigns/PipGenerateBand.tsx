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
  refusal,
  label = "Generate",
}: {
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
      className="flex flex-col gap-3 rounded-card border border-brand/40 bg-surface p-4 shadow-card sm:flex-row sm:items-center sm:justify-between sm:p-5"
    >
      <div className="min-w-0">
        <h2 id="pip-generate" className="text-heading text-ink">
          Let Pip, our AI agent, generate the script
        </h2>
        <p className="mt-0.5 text-meta text-ink-muted">
          {reason ?? "Pip writes it from your main task and materials."}
        </p>
      </div>
      <button
        type="button"
        className={`${PRIMARY_BUTTON} shrink-0`}
        disabled={disabled || busy}
        title={reason ?? refusal}
        onClick={onGenerate}
      >
        {busy ? "Generating…" : label}
      </button>
    </section>
  );
}
