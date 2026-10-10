"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * "SAVED", BESIDE THE BUTTON THAT SAVED (founder, REDESIGN-2): a small tick and one word
 * next to the control that did it, which fades after a moment. It replaces success toasts:
 * a toast appears far from where the person was looking and says what they already know.
 *
 * Pass the mutation's \`submittedAt\` once it has succeeded (0 otherwise); each new save
 * shows it again. It is a polite live region, so a screen reader hears "Saved" too. The
 * fade is the one motion it has, and reduced motion removes it.
 */
export function SavedTick({ at, label = "Saved" }: { at: number; label?: string }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!at) return undefined;
    setVisible(true);
    const timer = window.setTimeout(() => setVisible(false), 2500);
    return () => window.clearTimeout(timer);
  }, [at]);
  // Nothing until the first save: an empty live region on every screen with a save button
  // would be one more "status" a reader (or a test) has to step over.
  if (!at) return null;
  return (
    <span
      role="status"
      aria-live="polite"
      className={`inline-flex items-center gap-1 text-meta font-medium text-brand-strong motion-safe:transition-opacity motion-safe:duration-500 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
    >
      {visible ? (
        <>
          <Check aria-hidden className="h-3.5 w-3.5" />
          {label}
        </>
      ) : null}
    </span>
  );
}
