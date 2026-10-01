"use client";

import Link from "next/link";

import { useCalls } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

/** The wire value of a call that is happening now (`calls.status`). */
export const LIVE_STATUS = "in_progress";

/**
 * How many in-progress calls the chrome asks for. The count is shown as "N+" when the
 * page comes back full, because `/v1/calls` returns a list without a total and a full
 * page means "at least this many", not "exactly this many".
 */
const LIVE_PAGE = 20;

/**
 * The "this is happening now" mark. A solid dot with a soft ping around it; under reduced
 * motion the ping is not drawn and the solid dot carries the meaning. Decorative to a
 * screen reader — every place that draws it also says "Live" or "In progress" in text.
 */
export function LiveDot({ className = "" }: { className?: string }) {
  return (
    <span aria-hidden className={`relative inline-flex h-2 w-2 shrink-0 ${className}`}>
      <span className="absolute inset-0 rounded-full bg-brand-bright opacity-60 motion-safe:animate-ping" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-brand" />
    </span>
  );
}

/**
 * "2 live" in the client header — how many calls are in progress across the account,
 * linking to the call log filtered to them.
 *
 * Read from the existing `/v1/calls?status=in_progress` through `useCalls`, so it polls on
 * the same 20-second cadence as every other call list and adds no endpoint. Nothing while
 * the first read is out and nothing on zero; a failed read says it could not check,
 * because its silence would read as "no calls live".
 */
export function LiveCallsPill({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const live = useCalls(session, { status: LIVE_STATUS, limit: LIVE_PAGE });
  if (live.isPending) return null;
  // A failed read is not "no calls live": it says it could not check, like the bell's "?".
  if (live.isError) {
    return (
      <Link
        href={href(`/c/${slug}/calls`)}
        aria-label="Live calls: we could not check just now"
        title="We could not check for calls in progress. Open the call log to try again."
        className="press inline-flex h-9 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-[13px] font-medium text-ink-muted hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-11"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-ink-faint" />
        live ?
      </Link>
    );
  }
  if (live.data.length === 0) return null;
  const count = live.data.length;
  const label = count >= LIVE_PAGE ? `${LIVE_PAGE}+` : String(count);
  return (
    <Link
      href={href(`/c/${slug}/calls?status=${LIVE_STATUS}`)}
      aria-label={`${label} ${count === 1 ? "call" : "calls"} in progress now`}
      className="press inline-flex h-9 items-center gap-2 rounded-full border border-line bg-surface px-3 text-[13px] font-medium text-ink shadow-card hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-11"
    >
      <LiveDot />
      <span className="tabular-nums">{label}</span>
      <span className="text-ink-muted">live</span>
    </Link>
  );
}
