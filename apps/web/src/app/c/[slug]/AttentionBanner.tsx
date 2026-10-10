"use client";

import Link from "next/link";
import { ArrowRight, CircleAlert } from "lucide-react";

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
    <p className="rounded-md bg-surface-muted px-4 py-3 text-body text-ink-muted">
      We could not check whether anything needs your attention.{" "}
      <button
        type="button"
        onClick={() => void attention.refetch()}
        className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 font-medium text-brand-strong underline"
      >
        Try again
      </button>
    </p>
  ) : (
    attention.data &&
    attention.data.total > 0 && (
      <Link
        href={href}
        className="flex items-center justify-between gap-3 rounded-md border border-warn-line bg-warn-soft px-4 py-3 text-body text-warn transition-colors duration-(--duration-fast) ease-out hover:bg-[color-mix(in_srgb,var(--warn-soft),var(--warn-line)_40%)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-warn focus-visible:ring-offset-2"
      >
        <span className="flex items-center gap-2">
          <CircleAlert aria-hidden className="h-4 w-4 shrink-0" />
          <span>
            <span className="font-semibold tabular-nums">
              {formatCount(attention.data.total)}
            </span>{" "}
            {attention.data.total === 1 ? "thing needs" : "things need"} your attention
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1 font-medium">
          Review
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </span>
      </Link>
    )
  )}
    </>
  );
}
