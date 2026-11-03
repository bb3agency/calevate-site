"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { formatCount, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { useAttention } from "@/lib/api/attention";

import { HOME_NOTICE_LINK, ReadFailedRow } from "./homeNotices";
import { HOME } from "./setup/_ui/copy";

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
    <ReadFailedRow
      action={
        <button type="button" onClick={() => void attention.refetch()} className={`${SECONDARY_BUTTON_SM} shrink-0`}>
          {HOME.tryAgain}
        </button>
      }
    >
      {HOME.queueFailed}
    </ReadFailedRow>
  ) : (
    attention.data &&
    attention.data.total > 0 && (
      <Link
        href={href}
        className={`${HOME_NOTICE_LINK} items-center`}
      >
        <span className="flex items-center gap-2">
          <span>
            <span className="font-semibold tabular-nums">
              {formatCount(attention.data.total)}
            </span>{" "}
            {HOME.queue(attention.data.total)}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-1 font-medium text-brand-strong">
          {HOME.queueAction}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </span>
      </Link>
    )
  )}
    </>
  );
}
