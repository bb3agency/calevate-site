"use client";

import Link from "next/link";

import { formatCount } from "@/components/ui";
import type { useAttention } from "@/lib/api/attention";

/**
 * The triage queue's size, at the top of the daily entry point — and NOTHING when the
 * queue is empty. Its own file because it is three states in one strip: a failed read
 * that must not read as an all-clear, a zero that renders nothing at all, and a count
 * that is a link.
 */
export function AttentionBanner({
  attention,
  href,
}: {
  attention: ReturnType<typeof useAttention>;
  href: string;
}) {
  return (
    <>
  {/* Only when something IS waiting: a zero here is noise and renders nothing. A
      FAILED read is NOT an all-clear, though — dropping the banner silently would
      offer the client neither the action nor a reason for its absence (BUILD-LOG
      §52), so the failure says what it could not read and offers the retry. */}
  {attention.isError ? (
    <p className="rounded-card border border-line bg-surface-muted px-4 py-3 text-sm text-ink-muted">
      We could not check whether anything needs your attention.{" "}
      <button
        type="button"
        onClick={() => void attention.refetch()}
        className="font-medium text-brand-strong underline"
      >
        Try again
      </button>
    </p>
  ) : (
    attention.data &&
    attention.data.total > 0 && (
      <Link
        href={href}
        className="flex items-center justify-between gap-3 rounded-card border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 hover:bg-amber-100 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200 dark:hover:bg-amber-900"
      >
        <span>
          <span className="font-semibold tabular-nums">
            {formatCount(attention.data.total)}
          </span>{" "}
          {attention.data.total === 1 ? "thing needs" : "things need"} your
          attention — things we stopped on purpose, each with the reason and
          the fix.
        </span>
        <span className="shrink-0 font-medium underline">
          Open the list
        </span>
      </Link>
    )
  )}
    </>
  );
}
