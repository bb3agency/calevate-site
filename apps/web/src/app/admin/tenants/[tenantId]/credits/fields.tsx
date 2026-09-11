"use client";

import type { ReactNode } from "react";

import { FIELD_HINT, FIELD_LABEL } from "@/components/ui";

/**
 * The labelled field the credits screens share.
 *
 * It lived inside `page.tsx` until the trial control arrived beside it, and a route module
 * may export only its `default` (D-196) — so the choice was a SECOND copy of the same
 * markup in the sibling panel, or this file. Two copies is the defect even when both work:
 * the a11y decision below (a persistent visible label, never a placeholder) is the kind
 * that gets fixed in one copy and not the other, and `make web-check` runs axe over the
 * rendered page rather than over each author's memory of it.
 */

/**
 * The description an input points at. Both halves are named so a screen reader hears the
 * error AND the guidance — an error span that nothing references is a message only
 * sighted users get, which on the field that decides double-crediting is the wrong half
 * of the audience to serve.
 */
export function describedBy(id: string, hasError: boolean): string {
  return hasError ? `${id}-hint ${id}-error` : `${id}-hint`;
}

export function Field({
  label,
  id,
  hint,
  error,
  children,
}: {
  label: string;
  id: string;
  hint: string;
  error: string | null;
  children: ReactNode;
}) {
  return (
    <div>
      {/* A PERSISTENT VISIBLE label, not a placeholder. axe scores a placeholder as an
          accessible name and WCAG 3.3.2 does not: the text vanishes on the first
          keystroke, which on a hand-transcribed bank reference is exactly when it is
          needed (tests/a11y.ts states this limitation). */}
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      <div className="mt-1">{children}</div>
      <span id={`${id}-hint`} className={FIELD_HINT}>
        {hint}
      </span>
      {error && (
        <span
          id={`${id}-error`}
          className="mt-1 block text-xs font-medium text-rose-700 dark:text-rose-300"
        >
          {error}
        </span>
      )}
    </div>
  );
}

