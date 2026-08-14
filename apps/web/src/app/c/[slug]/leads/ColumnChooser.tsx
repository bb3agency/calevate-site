"use client";

import { Columns3 } from "lucide-react";

import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { LeadColumn } from "@/lib/api/leads";

/**
 * Which columns this client is looking at — and, because the export takes the same
 * selection, which columns leave the building (SURFACES §2, "column chooser mirrored in
 * CSV export").
 *
 * **`<details>`, not a hand-rolled popover.** The native element is keyboard-operable,
 * screen-reader-announced and dismissible without a single line of focus management,
 * which is three ways a hand-rolled dropdown gets accessibility wrong. shadcn/ui's
 * Popover is the eventual answer for the design pass; this is correct today at a
 * hundredth of the code.
 *
 * **Every control carries a persistent visible label.** Each checkbox is wrapped in a
 * `<label>` whose text is the column's own name, and the group carries a `<legend>` —
 * axe cannot see a placeholder or a title attribute, and neither can a person who has
 * turned the tooltip off.
 *
 * **`undefined` is not "none".** `chosen === undefined` means the client has expressed no
 * preference, which the API renders as every column this agent HAS — so a column added
 * to the capture list tomorrow appears rather than being silently excluded by a
 * selection frozen today. Clearing the last checkbox therefore returns to `undefined`
 * rather than sending an empty list.
 */
export function ColumnChooser({
  available,
  chosen,
  onChange,
  unavailableReason,
}: {
  /** `undefined` while the list request is in flight or has failed — see below. */
  available: LeadColumn[] | undefined;
  chosen: string[] | undefined;
  onChange: (next: string[] | undefined) => void;
  unavailableReason: string | null;
}) {
  /**
   * The control is DISABLED until the server has said what the columns are, and the
   * reason is on the control (BUILD-LOG §52). Rendering an empty chooser over a failed
   * request would say "this table has no columns", which is a claim about the client's
   * capture list made from a request that never landed.
   */
  if (!available?.length) {
    return (
      <button
        type="button"
        disabled
        title={unavailableReason ?? "Reading this table's columns…"}
        className={SECONDARY_BUTTON_SM}
      >
        <Columns3 className="h-3.5 w-3.5" />
        Columns
      </button>
    );
  }

  const selected = chosen ?? available.map((c) => c.key);
  const toggle = (key: string) => {
    const next = selected.includes(key)
      ? selected.filter((k) => k !== key)
      : // Re-inserted in the REGISTRY's order rather than appended, so ticking a column
        // back on puts it where it was instead of at the end of the table.
        available.filter((c) => selected.includes(c.key) || c.key === key).map((c) => c.key);
    onChange(next.length ? next : undefined);
  };

  return (
    <details className="relative">
      <summary
        className={`${SECONDARY_BUTTON_SM} cursor-pointer list-none marker:content-none`}
        aria-label={`Choose columns — ${selected.length} of ${available.length} shown`}
      >
        <Columns3 className="h-3.5 w-3.5" />
        Columns
        <span className="tabular-nums text-ink-muted">
          {selected.length}/{available.length}
        </span>
      </summary>
      <div className="absolute right-0 z-20 mt-1 w-64 rounded-card border border-line bg-surface p-3 shadow-lg">
        <fieldset>
          <legend className="mb-2 text-xs font-semibold text-ink">
            Columns shown here and in the CSV
          </legend>
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {available.map((column) => (
              <label
                key={column.key}
                className="flex items-center gap-2 rounded-md px-1 py-1 text-sm text-ink hover:bg-black/5 dark:hover:bg-white/5"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(column.key)}
                  onChange={() => toggle(column.key)}
                  className="h-3.5 w-3.5"
                />
                <span>{column.label}</span>
              </label>
            ))}
          </div>
          {/* The escape hatch, and the one that restores "whatever this agent has"
              rather than pinning today's list. */}
          <button
            type="button"
            onClick={() => onChange(undefined)}
            className="mt-2 text-xs font-medium text-brand-strong hover:underline dark:text-brand-bright"
          >
            Show every column
          </button>
        </fieldset>
      </div>
    </details>
  );
}
