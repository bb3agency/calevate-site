"use client";

import Link from "next/link";
import { Bell, CircleDot, PhoneCall, StickyNote, UserCheck } from "lucide-react";

import { ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { LoadMore } from "@/components/interior/load-more";
import type { LeadTimelineEvent, useLeadTimeline } from "@/lib/api/leads";
import { lookup } from "@/lib/lookup";

/**
 * How each event type is dressed. Read with `lookup` and falling back VISIBLY — the
 * server's `type` is a string it chose at runtime, not a union this build is entitled to
 * assume, and a build sitting behind its own migration must not drop a row it does not
 * recognise. Same call, for the same reason, as the call-detail transcript's `speaker`.
 */
const EVENT_STYLES: Record<string, { icon: typeof Bell; medallion: string }> = {
  status_change: {
    icon: CircleDot,
    medallion: "bg-brand-soft text-brand-strong",
  },
  assignment: { icon: UserCheck, medallion: "bg-brand-soft text-brand-strong" },
  call: {
    icon: PhoneCall,
    medallion: "bg-ink/[0.05] text-ink-muted",
  },
  notification: {
    icon: Bell,
    medallion: "bg-ink/[0.05] text-ink-muted",
  },
  note: {
    icon: StickyNote,
    medallion: "bg-warn-soft text-warn",
  },
};

const FALLBACK_STYLE = {
  icon: CircleDot,
  medallion: "bg-ink/[0.05] text-ink-muted",
};

/**
 * THE LEAD'S HISTORY — every status change, call, alert and blocked dial, as prose the
 * server composed. Its own read with its own failure and retry: a dead timeline must not
 * blank the header above it, and an empty list renders only where the server said so.
 */
export function LeadTimeline({
  timeline,
  events,
  timelineTotal,
  impersonating,
  slug,
  href,
}: {
  timeline: ReturnType<typeof useLeadTimeline>;
  events: LeadTimelineEvent[];
  timelineTotal: number | undefined;
  /** The server's answer; undefined until `/v1/me` has answered, and then no line shows. */
  impersonating: boolean | undefined;
  slug: string;
  href: (path: string) => string;
}) {
  return (
      <section className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-ink">History</h2>
          {/* No count until there IS one. "0 events" printed while the request is in
              flight is a statement about this lead, and it is the wrong one. */}
          {timeline.data && timelineTotal !== undefined && (
            <p className="text-xs text-ink-muted">
              {timelineTotal > events.length
                ? `The ${formatCount(events.length)} most recent of ${formatCount(timelineTotal)}`
                : `${formatCount(timelineTotal)} ${timelineTotal === 1 ? "entry" : "entries"}`}
            </p>
          )}
        </div>

        {/* The timeline's own failure, its own retry. It must not be answered by the
            header above it, and it must not be answered by an empty list. */}
        {timeline.error && (
          <ProblemNotice error={timeline.error} onRetry={() => void timeline.refetch()} />
        )}

        {timeline.isLoading ? (
          <div>
            <Skeleton rows={4} />
          </div>
        ) : !timeline.data ? null : events.length ? (
          <div className="border-y border-line">
            <ol className="divide-y divide-line">
              {events.map((event) => (
                <TimelineRow key={event.id} event={event} slug={slug} href={href} />
              ))}
            </ol>
            {/* The rest of the record, reachable (ux-audit LD4): the history used to
                stop at the newest 50 with an honest sentence about an unreachable
                remainder. `auto` off — a reverse-chronological audit trail should grow
                when asked, not while the reader's scroll happens to pass a sentinel. */}
            {timeline.hasNextPage && (
              <LoadMore
                auto={false}
                hasMore={timeline.hasNextPage}
                labels={{ idle: "Show earlier history" }}
                onLoad={async () => {
                  const result = await timeline.fetchNextPage();
                  if (result.isError) throw result.error;
                  return result.hasNextPage;
                }}
                className="py-1"
              />
            )}
          </div>
        ) : (
          <div className="border-y border-line">
            {/* Reached ONLY when the server answered with an empty list — a failed
                request never gets this far, which is the whole point of the branch
                order above. */}
            <EmptyState
              illustration={<EmptySketch kind="calls" />}
              message="Nothing has happened yet"
              hint="Calls, status changes, alerts and blocked dials all appear here."
            />
          </div>
        )}

        {impersonating && (
          <p className="text-xs text-ink-muted">
            {/* D-587: a view-as session can change this lead. What the reader needs to know
                is no longer "you cannot" but "this is not anonymous" — the shell's amber
                banner says the same thing, and this line says it where the controls are. */}
            You are working inside this account as an operator. Every change here is logged
            against you.
          </p>
        )}
      </section>
  );
}

/**
 * One line of history.
 *
 * `title` and `detail` are prose the SERVER composed from a whitelist of payload keys
 * (`crm.service._project_event`); this screen renders them and adds nothing. That split
 * is deliberate — the payload is schemaless JSONB written by six producers, so the place
 * that decides what may be said about a row is the place that can see all of them.
 */
function TimelineRow({
  event,
  slug,
  href,
}: {
  event: LeadTimelineEvent;
  slug: string;
  href: (path: string) => string;
}) {
  const style = lookup(EVENT_STYLES, event.type) ?? FALLBACK_STYLE;
  const Icon = style.icon;
  return (
    <li className="flex gap-3 px-3 py-3">
      <span
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${style.medallion}`}
        aria-hidden
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{event.title}</p>
        {event.detail && <p className="mt-0.5 text-xs text-ink-muted">{event.detail}</p>}
        <p className="mt-1 text-xs text-ink-faint">
          {formatIST(event.occurred_at)}
          {/* "Calevate" for a platform event and the colleague's name for a human one.
              A member the account can no longer name arrives as `actor_kind: "member"`
              with no name, and reads as a colleague rather than as the platform —
              because that is what it was. */}
          {" · "}
          {event.actor_kind === "system" ? "Calevate" : (event.actor_name ?? "A colleague")}
          {event.call_id && (
            <>
              {" · "}
              <Link
                href={href(`/c/${slug}/calls/${event.call_id}`)}
                className="font-medium text-ink-muted hover:underline"
              >
                Open the call
              </Link>
            </>
          )}
        </p>
      </div>
    </li>
  );
}
