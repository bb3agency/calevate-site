"use client";

import { useCallback, useState } from "react";

import { toSpokenPlainText } from "@/components/arc/spoken-text";

/** Same words as the kit's `ScriptEditor`, so the page says it one way. */
export const CLEANED_NOTE = "Formatting was removed: the agent speaks plain words only.";

/**
 * Plain text for a script box outside the kit's `ScriptEditor` (a step, a part of
 * "About the agent"): markdown, list markers, HTML and emoji never reach the script, by
 * the same rule as the editor (`arc/spoken-text`). `take` returns the cleaned value and
 * remembers whether anything was removed, so the box can say so instead of dropping it
 * silently.
 */
export function usePlainText(): { cleaned: boolean; take: (raw: string) => string } {
  const [cleaned, setCleaned] = useState(false);
  const take = useCallback((raw: string) => {
    const plain = toSpokenPlainText(raw);
    setCleaned(plain !== raw);
    return plain;
  }, []);
  return { cleaned, take };
}

export function CleanedNote({ shown }: { shown: boolean }) {
  return shown ? (
    <p role="status" className="mt-1 text-meta text-ink-muted">
      {CLEANED_NOTE}
    </p>
  ) : null;
}
