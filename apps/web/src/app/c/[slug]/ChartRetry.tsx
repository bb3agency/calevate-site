"use client";

/**
 * A chart's failure line with its retry, passed as the chart's `error`: a failed read says
 * what did not load and offers the way back, in the chart's own place (§52).
 */
export function chartError(failed: unknown, message: string, onRetry: () => void) {
  if (!failed) return undefined;
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {message}
      <button
        type="button"
        onClick={onRetry}
        className="press rounded-sm font-medium text-ink underline underline-offset-2 hover:text-brand-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        Try again
      </button>
    </span>
  );
}
