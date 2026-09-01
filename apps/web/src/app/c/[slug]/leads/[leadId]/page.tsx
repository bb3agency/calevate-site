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
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { LoadMore } from "@/components/interior/load-more";

import { AssigneeSelect } from "../AssigneeSelect";
import { STATUSES, StatusSelect } from "../StatusSelect";

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
 * 1. **Put the number in a URL.** It is PRINTED in full (D-436) — this is the screen a
 *    receptionist rings back from — but a path or a query string reaches browser
 *    history, referrers and access logs, and that is hard rule 6 and unchanged. The
 *    timeline carries no number at all: the API projects each event into prose rather
 *    than serializing the payload.
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

  // The history, flattened across the loaded pages. Deduped by id: newest-first plus
  // offset paging means an event landing mid-read shifts rows across a page boundary,
  // and a duplicate key would crash the list over a customer doing business.
  const seen = new Set<string>();
  const events = (timeline.data?.pages ?? [])
    .flatMap((page) => page.items)
    .filter((event) => (seen.has(event.id) ? false : (seen.add(event.id), true)));
  // The server restates the whole history's size on every page; the newest answer wins.
  const timelineTotal = timeline.data?.pages.at(-1)?.total;

  /*
   * THIS LEAD, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * A LEAD IS A PERSON, so the only thing about them that leaves this browser is their
   * ID. Not `name`, not `phone_e164`, not `assigned_to_name`, and not one line of the
   * timeline — a timeline entry quotes what was said on a call. What IS declared is the
   * case around them: which stage, which source, how many calls, whether it is a repeat
   * caller, how much history there is. That is the vocabulary of "should I chase this
   * one", which is the question this screen is opened with.
   *
   * The STAGE is the one writable control: it is a fixed enum (`STATUSES`), it is what the
   * screen's own select writes, and moving a lead to "won" is exactly the small act a
   * person wants done while they read. `apply` goes through the SAME `editLead` mutation
   * the select does — never a DOM write — so the optimistic update, the failure toast and
   * the permission refusal all behave identically whoever pressed it.
   */
  useCopilotSurface({
    route: "/c/{slug}/leads/{leadId}",
    title: "Lead",
    realm: "client",
    fields: [
      {
        id: "lead-status",
        label: "Stage",
        type: "select",
        value: lead.data?.status ?? "",
        options: STATUSES.map((stage) => ({ value: stage, label: stage })),
        writable: lead.data !== undefined && mayAssign.allowed,
        help: "Saves immediately — this control has no separate Save button.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: lead.data
          ? "the lead below has loaded"
          : lead.error
            ? "the lead failed to load"
            : "still loading",
      },
      { key: "lead_id", label: "Lead id", value: leadId },
      ...(lead.data
        ? [
            { key: "status", label: "Stage", value: lead.data.status },
            { key: "source", label: "Where the lead came from", value: lead.data.source },
            { key: "call_count", label: "Calls with this lead", value: String(lead.data.call_count) },
            {
              key: "is_repeat_caller",
              label: "Has this person called before?",
              value: lead.data.is_repeat_caller ? "yes" : "no",
            },
            { key: "created_at", label: "First seen (UTC)", value: lead.data.created_at },
            { key: "updated_at", label: "Last changed (UTC)", value: lead.data.updated_at },
            {
              key: "captured_fields",
              label: "Captured detail names on file (the field names, never their values)",
              value: Object.keys(lead.data.data ?? {}).join(", ") || "none",
            },
            {
              key: "assigned",
              label: "Does this lead have an owner?",
              value: lead.data.assigned_to == null ? "no" : "yes, one team member",
            },
            {
              key: "last_call_id",
              label: "Most recent call id",
              value: lead.data.last_call_id ?? "none",
            },
          ]
        : []),
      { key: "timeline_shown", label: "History entries loaded", value: String(events.length) },
      {
        key: "timeline_total",
        label: "History entries in total",
        value: timelineTotal === undefined ? "not known yet" : String(timelineTotal),
      },
      {
        key: "may_edit",
        label: "May this session change the stage or the owner?",
        value: mayAssign.allowed ? "yes" : "no",
      },
    ],
    apply: (fills) => {
      for (const item of fills) {
        if (item.field_id !== "lead-status" || !mayAssign.allowed) continue;
        // `find`, not `some`: it NARROWS the model's opaque string to the enum the
        // mutation takes, so an unrecognised stage is dropped by the type system rather
        // than cast past it.
        const next = STATUSES.find((stage) => stage === asText(item.value));
        if (next !== undefined && next !== lead.data?.status) {
          editLead.mutate({ leadId, edit: { status: next } });
        }
      }
    },
  });

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
            {/* IN FULL (D-436). Text, never an `href` — see rule 1 above. */}
            <span className="tabular-nums text-sm text-ink-muted">{lead.data.phone_e164}</span>
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

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-4">
            {/* The stage is CHANGEABLE here (ux-audit LD1): this page is where the
                decision is made — read the history, ring the customer, mark them won —
                and it used to send the user back to the table to find the row. Same
                shared StatusSelect and same mutation as the table and the board. */}
            <span className="inline-flex items-center gap-2">
              <span className="text-xs font-medium text-ink-muted">Stage</span>
              <StatusSelect
                value={lead.data.status}
                label={`Stage for ${lead.data.name ?? lead.data.phone_e164}`}
                disabled={!mayAssign.allowed || editLead.isPending}
                onChange={(next) => editLead.mutate({ leadId, edit: { status: next } })}
                className="rounded-md border border-line bg-transparent px-2 py-1 text-xs capitalize text-ink disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11"
              />
            </span>
            <span className="inline-flex items-center gap-2">
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
            </span>
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
          <Card bodyClassName="p-4">
            <Skeleton rows={4} />
          </Card>
        ) : !timeline.data ? null : events.length ? (
          <Card bodyClassName="p-2">
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
