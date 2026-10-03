import type { ReactNode } from "react";

/**
 * NOTHING HERE YET — one line, an optional second line, and the one action that fills it.
 *
 * Render it only where the SERVER said the list is empty: a failed or paused read is a
 * `ProblemNotice`, never this (BUILD-LOG §52). `message` is a sentence about the list
 * ("No campaigns yet."), not a paragraph about the feature; `hint` says when something will
 * appear, for a list the reader cannot fill themselves; `action` is the create button or
 * link. `filtered` cases say what to clear instead ("No calls match this filter."). An
 * empty state that is the GOOD state (an empty holds queue) rightly offers no action.
 *
 * The one empty state in both consoles: `ui.tsx` carried a second (title + hint), and the
 * two drifted in type size and colour screen by screen.
 */
export function EmptyState({
  message,
  hint,
  action,
  className = "",
}: {
  message: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center gap-3 px-4 py-10 text-center ${className}`}>
      <div>
        <p className="text-[14px] text-ink-muted">{message}</p>
        {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
