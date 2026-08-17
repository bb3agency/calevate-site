"use client";

import Link from "next/link";
import { use } from "react";
import {
  ArrowLeft,
  Bell,
  CircleDot,
  PhoneCall,
  ShieldAlert,
  StickyNote,
  UserCheck,
} from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatusBadge,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import {
  useEditLead,
  useLead,
  useLeadTimeline,
  useMembers,
  type LeadTimelineEvent,
} from "@/lib/api/leads";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { AssigneeSelect } from "../AssigneeSelect";

/**
 * One lead, and the thing this product could not previously show anybody: its HISTORY.
 *
 * `lead_events` has been written since M1 by six producers across three deployables —
 * the status change, the blocked dial, every call, every hot-lead alert, every WhatsApp
 * attempt, every spent campaign ladder — and the only reader was an aggregate query
 * behind the needs-attention badge. "We called them twice, WhatsApp was refused, the
 * campaign gave up" was on record and invisible to the person it is about. This screen
 * is that record.
 *
 * What it must never do, in the order the damage runs:
 *
 * 1. **Print a raw number.** `phone_masked` is the only form `LeadOut` carries and the
 *    only one allowed in the DOM or in a URL (hard rule 6). The timeline carries none at
 *    all — the API projects each event into prose rather than serializing the payload.
 * 2. **Render an empty history over a failed read.** "Nothing has happened to this lead"
 *    and "we could not read what happened to this lead" send an owner in opposite
 *    directions, and only one of them is ever true. Loading is a `Skeleton`, failure is
 *    a `ProblemNotice`, and the empty state renders ONLY where the server said the list
 *    was empty (BUILD-LOG §52).
 * 3. **Let the two requests answer for each other.** The lead and its timeline are
 *    separate reads and either can fail alone: a dead timeline must not blank the
 *    header, and a dead header must not imply the history is gone.
 */

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
    medallion: "bg-black/5 text-ink-muted dark:bg-white/10",
  },
  notification: {
    icon: Bell,
    medallion: "bg-black/5 text-ink-muted dark:bg-white/10",
  },
  note: {
    icon: StickyNote,
    medallion: "bg-amber-100 text-amber-700 dark:bg-amber-950",
  },
};

const FALLBACK_STYLE = {
  icon: CircleDot,
  medallion: "bg-black/5 text-ink-muted dark:bg-white/10",
};

/** How many events one page of the history holds. The API caps this at 100. */
const TIMELINE_LIMIT = 50;

export default function LeadDetailPage({
  params,
}: {
  params: Promise<{ slug: string; leadId: string }>;
}) {
  const { slug, leadId } = use(params);
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const lead = useLead(session, leadId);
  const timeline = useLeadTimeline(session, leadId, TIMELINE_LIMIT);
  const members = useMembers(session);
  // ONE mutation for every edit of a lead — the same `useEditLead` the table uses,
  // moved here in the change that replaced `useAssignLead` and `useUpdateLeadStatus`.
  const editLead = useEditLead(session);
  const me = useMe(session);
  const mayAssign = useWriteAccess(session, "leads:write", "change who owns a lead");

  return (
    <div className="space-y-4 pb-12">
      {/* No <h1>: the app shell prints the page title from the nav list. */}
      <Link
        href={href(`/c/${slug}/leads`)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" />
        Leads
      </Link>

      {lead.error && <ProblemNotice error={lead.error} onRetry={() => void lead.refetch()} />}

      {lead.isLoading ? (
        <Card bodyClassName="p-4 sm:p-5">
          <Skeleton rows={3} />
        </Card>
      ) : lead.data ? (
        <Card bodyClassName="p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="text-lg font-semibold text-ink">
              {lead.data.name ?? <span className="font-normal text-ink-faint">No name</span>}
            </span>
            {/* MASKED, always — the API sends no other form to this screen. */}
            <span className="tabular-nums text-sm text-ink-muted">{lead.data.phone_masked}</span>
            <StatusBadge value={lead.data.status} />
            {lead.data.is_repeat_caller && (
              <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-semibold text-brand-strong">
                repeat caller
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            {lead.data.source} · {formatCount(lead.data.call_count)}{" "}
            {lead.data.call_count === 1 ? "call" : "calls"} · updated{" "}
            {formatIST(lead.data.updated_at)}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
            <span className="text-xs font-medium text-ink-muted">Owner</span>
            <AssigneeSelect
              lead={lead.data}
              members={members.data}
              unavailableReason={
                members.error
                  ? "We could not read your team just now, so the owner cannot be changed. Reload the page to try again."
                  : mayAssign.reason
              }
              disabled={!mayAssign.allowed || editLead.isPending}
              onChange={(userId) => editLead.mutate({ leadId, edit: { assigned_to: userId } })}
              className="rounded-md border border-line bg-transparent px-2 py-1 text-xs text-ink"
            />
          </div>
          <div className="mt-2">
            <RestrictionNote reason={mayAssign.reason} />
          </div>
        </Card>
      ) : (
        !lead.error && (
          // react-query resolved with nothing, which is a broken premise rather than a
          // lead with no content. Say we have nothing rather than describing the lead as
          // having none.
          <NoticeBox
            tone="neutral"
            icon={<ShieldAlert className="h-5 w-5" />}
            title="Nothing to show"
          >
            We could not read this lead. Reload the page, or go back to the leads table.
          </NoticeBox>
        )
      )}

      {members.error != null && <ProblemNotice error={members.error} />}
      {editLead.error != null && <ProblemNotice error={editLead.error} />}

      <section className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-ink">History</h2>
          {/* No count until there IS one. "0 events" printed while the request is in
              flight is a statement about this lead, and it is the wrong one. */}
          {timeline.data && (
            <p className="text-xs text-ink-muted">
              {timeline.data.total > timeline.data.items.length
                ? `The ${formatCount(timeline.data.items.length)} most recent of ${formatCount(timeline.data.total)}`
                : `${formatCount(timeline.data.total)} ${timeline.data.total === 1 ? "entry" : "entries"}`}
            </p>
          )}
        </div>

        {/* The timeline's own failure, its own retry. It must not be answered by the
            header above it, and it must not be answered by an empty list. */}
        {timeline.error && (
          <ProblemNotice error={timeline.error} onRetry={() => void timeline.refetch()} />
        )}

        {timeline.isLoading ? (
          <Card bodyClassName="p-4">
            <Skeleton rows={4} />
          </Card>
        ) : !timeline.data ? null : timeline.data.items.length ? (
          <Card bodyClassName="p-2">
            <ol className="divide-y divide-line">
              {timeline.data.items.map((event) => (
                <TimelineRow key={event.id} event={event} slug={slug} href={href} />
              ))}
            </ol>
          </Card>
        ) : (
          <Card bodyClassName="p-2">
            {/* Reached ONLY when the server answered with an empty list — a failed
                request never gets this far, which is the whole point of the branch
                order above. */}
            <EmptyState
              title="Nothing has happened yet"
              hint="Calls, status changes, alerts and blocked dials all appear here."
            />
          </Card>
        )}

        {me.data?.impersonating && (
          <p className="text-xs text-ink-muted">
            You are viewing this account read-only, so nothing here can be changed from this screen.
          </p>
        )}
      </section>
    </div>
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
