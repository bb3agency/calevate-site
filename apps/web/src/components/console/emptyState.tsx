import type { ReactNode } from "react";
import { Lock } from "lucide-react";

import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";

/**
 * NOTHING HERE YET — a small drawing of what will appear, one plain line, an optional
 * second line, and the one action that fills it (REDESIGN-2). The one empty state in both
 * consoles; the variants below are its four reasons for being empty, each with its own
 * honest next step (the useful half of uiarc's `empty-states`, MIT, see
 * components/arc/LICENSE — its artwork set is not used).
 *
 * - `first-use` (default): the server said the list is empty. `illustration` is an
 *   `EmptySketch` of the rows to come, `action` the create button or link. An empty state
 *   that is the GOOD state (an empty holds queue) rightly offers no action.
 * - `filtered`: the list exists but the filters hide everything. No illustration (the list
 *   is not new, only narrowed); `onClear` gives the one way back.
 * - `restricted`: this person may not see or fill it. Says why and who can, offers nothing
 *   that would be refused.
 * - `error`: the read failed. It renders `ProblemNotice`, the app's one failure surface,
 *   with `onRetry` — never "nothing here", because an unread list is not an empty one
 *   (BUILD-LOG §52).
 *
 * `message` is a sentence about the list ("No calls yet."), not a paragraph about the
 * feature; `hint` says when something will appear, for a list the reader cannot fill.
 */
export function EmptyState({
  message,
  hint,
  action,
  illustration,
  variant = "first-use",
  onClear,
  clearLabel = "Clear filters",
  error,
  onRetry,
  align = "center",
  className = "",
}: {
  message: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  illustration?: ReactNode;
  variant?: "first-use" | "filtered" | "restricted" | "error";
  /** `filtered`: clears the filters that hide everything. */
  onClear?: () => void;
  clearLabel?: string;
  /** `error`: the failed read's error, rendered by `ProblemNotice`. */
  error?: unknown;
  onRetry?: () => void;
  /** "start" for an empty list that sits under its own heading: same left edge as the content. */
  align?: "center" | "start";
  className?: string;
}) {
  if (variant === "error") {
    return (
      <div className={`py-6 ${className}`}>
        <ProblemNotice error={error ?? new Error(typeof message === "string" ? message : "This did not load.")} onRetry={onRetry} />
      </div>
    );
  }
  const drawn = variant === "first-use" ? illustration : null;
  return (
    <div
      data-empty={variant}
      className={`flex flex-col gap-4 py-10 ${align === "start" ? "items-start text-left" : "items-center px-4 text-center"} ${className}`}
    >
      {drawn ? <div className="w-full max-w-60">{drawn}</div> : null}
      {variant === "restricted" ? (
        <span aria-hidden className="flex h-9 w-9 items-center justify-center rounded-full bg-ink/[0.05] text-ink-muted">
          <Lock className="h-4 w-4" />
        </span>
      ) : null}
      <div className="max-w-sm">
        <p className="text-body text-ink">{message}</p>
        {hint && <p className="mt-1 text-meta text-ink-muted">{hint}</p>}
      </div>
      {variant === "filtered" && onClear ? (
        <button type="button" onClick={onClear} className={SECONDARY_BUTTON}>
          {clearLabel}
        </button>
      ) : null}
      {variant !== "restricted" ? action : null}
    </div>
  );
}
