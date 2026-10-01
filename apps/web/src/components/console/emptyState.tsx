import type { ReactNode } from "react";

/**
 * NOTHING HERE YET — one line and the one action that fills it.
 *
 * Render it only where the SERVER said the list is empty: a failed or paused read is a
 * `ProblemNotice`, never this (BUILD-LOG §52). `message` is a sentence about the list
 * ("No campaigns yet."), not a paragraph about the feature; `action` is the create button
 * or link. `filtered` cases say what to clear instead ("No calls match this filter.").
 *
 * `components/ui.tsx::EmptyState` (title + hint) remains for screens not yet moved onto
 * the console set; new and redesigned screens use this one.
 */
export function EmptyState({
  message,
  action,
  className = "",
}: {
  message: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center gap-3 px-4 py-10 text-center ${className}`}>
      <p className="text-[14px] text-ink-muted">{message}</p>
      {action}
    </div>
  );
}
