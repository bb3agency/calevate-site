"use client";

import Link from "next/link";
import { CheckCircle2, PhoneCall } from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatDuration,
  formatIST,
} from "@/components/ui";
import type { useCalls } from "@/lib/api/hooks";

/**
 * The six most recent calls — the fastest route from "somebody rang" to ringing them
 * back, which is why the number is rendered in full (D-436) and never truncated.
 */
export function LatestCalls({
  recent,
  allHref,
  callHref,
}: {
  recent: ReturnType<typeof useCalls>;
  allHref: string;
  callHref: (id: string) => string;
}) {
  return (
  <Card
    title="Latest calls"
    action={
      <Link
        href={allHref}
        className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
      >
        View all
      </Link>
    }
    bodyClassName="p-2"
  >
    {recent.isLoading ? (
      <Skeleton rows={5} />
    ) : recent.error || !recent.data ? (
      /* `!recent.data?.length` used to decide this, and `?.` collapses the two
         answers §52 keeps apart: an empty list the server sent and no answer at all
         are both falsy, so a paused query printed "No calls yet" to a client whose
         phone had simply lost signal. The refusal arm now owns both non-answers. */
      <ProblemNotice
        error={recent.error ?? new Error("The latest calls did not load.")}
        onRetry={() => void recent.refetch()}
      />
    ) : !recent.data.length ? (
      <EmptyState
        title="No calls yet"
        hint="They appear here within a couple of minutes of the call ending."
      />
    ) : (
      <ul className="divide-y divide-line">
        {recent.data.map((call) => (
          <li key={call.id}>
            <Link
              href={callHref(call.id)}
              className="flex items-center gap-4 rounded-lg px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                {call.status === "completed" ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : (
                  <PhoneCall className="h-4 w-4" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                {/* IN FULL (D-436) — the recent-calls rail is the fastest route
                    from "somebody rang" to ringing them back. */}
                {/* NOT `truncate`, for the reason the comment above gives: E.164 is
                    bounded at 16 characters, so the number the rail exists to let you
                    ring back can be shown whole. */}
                <span className="block text-[13px] font-semibold text-ink">
                  {call.caller_e164 ?? "Unknown number"}
                </span>
                <span className="block truncate text-[12px] text-ink-muted">
                  {call.agent_name ?? "—"} · {call.direction}
                </span>
              </span>
              <span className="hidden sm:block">
                <StatusBadge value={call.status} kind="call" />
              </span>
              <span className="w-20 shrink-0 text-right">
                <span className="block text-[11px] font-medium text-ink-muted">
                  {formatDuration(call.duration_s)}
                </span>
                <span className="block text-[11px] text-ink-faint">
                  {formatIST(call.started_at)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    )}
  </Card>
  );
}
