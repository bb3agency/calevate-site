import type { ReactNode } from "react";

/**
 * NOTHING HERE YET — a small drawing of what will appear, one plain line, an optional
 * second line, and the one action that fills it (REDESIGN-2).
 *
 * Render it only where the SERVER said the list is empty: a failed or paused read is a
 * `ProblemNotice`, never this (BUILD-LOG §52). `message` is a sentence about the list
 * ("No calls yet."), not a paragraph about the feature; `hint` says when something will
 * appear, for a list the reader cannot fill themselves; `action` is the create button or
 * link. `filtered` cases say what to clear instead ("No calls match this filter.") and take
 * no illustration, because the list is not new, only narrowed. An empty state that is the
 * GOOD state (an empty holds queue) rightly offers no action.
 *
 * `illustration` is an `EmptySketch` (`console/emptySketch.tsx`): the screen's own rows,
 * drawn small, so the owner sees what the list will become. Never generic artwork.
 *
 * The one empty state in both consoles: `ui.tsx` carried a second (title + hint), and the
 * two drifted in type size and colour screen by screen.
 */
export function EmptyState({
  message,
  hint,
  action,
  illustration,
  align = "center",
  className = "",
}: {
  message: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  illustration?: ReactNode;
  /** "start" for an empty list that sits under its own heading: same left edge as the content. */
  align?: "center" | "start";
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col gap-4 py-10 ${align === "start" ? "items-start text-left" : "items-center px-4 text-center"} ${className}`}
    >
      {illustration ? <div className="w-full max-w-60">{illustration}</div> : null}
      <div className="max-w-sm">
        <p className="text-body text-ink">{message}</p>
        {hint && <p className="mt-1 text-meta text-ink-muted">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
