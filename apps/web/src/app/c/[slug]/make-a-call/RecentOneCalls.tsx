"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { MonoValue, ProblemNotice, Skeleton, formatIST, formatPhone } from "@/components/ui";
import { callOutcome, callTitle } from "@/lib/callReview";
import { useBookedOneCalls, useRecentOneCalls } from "@/lib/api/oneCall";
import { useClientRealm } from "@/lib/api/session";

/**
 * Under the form: the calls booked for later that have not rung, then the one-off calls
 * people placed, newest first. Loading, failure and empty are three different states, and
 * "none yet" is said only from rows the server sent.
 */
export function RecentOneCalls() {
  const { session, href } = useClientRealm();
  const booked = useBookedOneCalls(session);
  const recent = useRecentOneCalls(session);

  return (
    <div className="space-y-6">
      {booked.data && booked.data.length > 0 ? (
        <section aria-labelledby="booked-calls" className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="booked-calls" className="text-body font-semibold text-ink">
              Booked for later
            </h2>
            <Link href={href(`/c/${session.orgSlug}/callbacks`)} className={TEXT_ACTION}>
              Move or call off
            </Link>
          </div>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {booked.data.map((row) => (
              <li key={row.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <MonoValue className="block text-body tabular-nums text-ink">{formatPhone(row.phone_e164)}</MonoValue>
                  {row.note ? <p className="break-words text-meta text-ink-muted">{row.note}</p> : null}
                </div>
                <span className="shrink-0 text-right text-meta font-medium tabular-nums text-ink">
                  {formatIST(row.requested_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : booked.error != null ? (
        <ProblemNotice error={booked.error} onRetry={() => void booked.refetch()} />
      ) : null}

      <section aria-labelledby="recent-calls" className="space-y-2">
        <h2 id="recent-calls" className="text-body font-semibold text-ink">
          Recent calls you made
        </h2>
        {recent.isLoading ? (
          <Skeleton rows={3} label="Loading recent calls" />
        ) : recent.error != null ? (
          <ProblemNotice error={recent.error} onRetry={() => void recent.refetch()} />
        ) : !recent.data || recent.data.length === 0 ? (
          <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-body text-ink-muted">
            No calls made from here yet. They show here as they happen.
          </p>
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {recent.data.map((call) => {
              const outcome = callOutcome(call);
              return (
                <li key={call.id}>
                  <Link
                    href={href(`/c/${session.orgSlug}/calls/${call.id}`)}
                    className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11"
                  >
                    <span className="min-w-0">
                      <span className="block break-words text-body font-medium text-ink">{callTitle(call)}</span>
                      <span className="block text-meta text-ink-muted">
                        {[call.agent_name, formatIST(call.started_at ?? call.created_at)].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-meta font-medium text-ink">
                      {outcome.words}
                      <ChevronRight aria-hidden className="h-4 w-4 text-ink-faint" />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
