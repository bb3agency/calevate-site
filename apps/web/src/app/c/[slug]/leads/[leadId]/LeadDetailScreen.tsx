"use client";

import Link from "next/link";
import { ArrowRight, ShieldAlert } from "lucide-react";

import {
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatusBadge,
  formatCount,
  formatIST,
  formatISTStamp,
  formatPhone,
} from "@/components/ui";
import { CopyButton } from "@/components/interior/copy-button";
import { PageHeader } from "@/components/console/pageHeader";
import { TEXT_ACTION } from "@/components/console/section";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { useEditLead, useLead, useLeadTimeline, useMembers } from "@/lib/api/leads";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { calledTimes, leadNextStep, leadTitle, sourceLabel, stageSetBy } from "@/lib/leadLabels";

import { AssigneeSelect } from "../AssigneeSelect";
import { STATUSES, StatusSelect } from "../StatusSelect";
import { LeadCaptured } from "./LeadCaptured";
import { LeadTimeline } from "./LeadTimeline";

/** How many events one page of the history holds. The API caps this at 100. */
const TIMELINE_LIMIT = 50;

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

export function LeadDetailScreen({ slug, leadId }: { slug: string; leadId: string }) {
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
            { key: "created_at", label: "First seen (IST)", value: formatISTStamp(lead.data.created_at) },
            { key: "updated_at", label: "Last changed (IST)", value: formatISTStamp(lead.data.updated_at) },
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
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader back={{ href: href(`/c/${slug}/leads`), label: "Leads" }} />

      {lead.error && <ProblemNotice error={lead.error} onRetry={() => void lead.refetch()} />}

      {lead.isLoading ? (
        <Skeleton rows={3} />
      ) : lead.data ? (
        <section aria-label="Lead">
          {/* IN FULL (D-436) and as text, never an `href` (hard rule 6); the copy button
              copies the E.164 form. */}
          <PageHeader
            title={leadTitle(lead.data)}
            status={
              <>
                <StatusBadge value={lead.data.status} />
                <span className="text-meta text-ink-muted">{stageSetBy(lead.data.status_set_by)}</span>
              </>
            }
            description={
              <>
                <span className="flex items-center gap-1 text-body tabular-nums text-ink">
                  {formatPhone(lead.data.phone_e164)}
                  <CopyButton value={lead.data.phone_e164} label="Copy phone number" />
                </span>
                <span className="block text-meta text-ink-faint">
                  {sourceLabel(lead.data.source)} ·{" "}
                  {calledTimes(lead.data.call_count) ??
                    `${formatCount(lead.data.call_count)} ${lead.data.call_count === 1 ? "call" : "calls"}`}{" "}
                  · updated {formatIST(lead.data.updated_at)}
                </span>
              </>
            }
            actions={
              lead.data.last_call_id && (
                <Link
                  href={href(`/c/${slug}/calls/${lead.data.last_call_id}`)}
                  className={TEXT_ACTION}
                >
                  Open the last call
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </Link>
              )
            }
          />

          {(leadNextStep(lead.data) || lead.data.last_call_headline) && (
            <dl className="mt-4 max-w-2xl space-y-1 border-t border-line pt-4">
              {leadNextStep(lead.data) && (
                <div className="flex flex-wrap gap-x-3">
                  <dt className="text-body text-ink-muted">Next step</dt>
                  <dd className="text-body text-ink">{leadNextStep(lead.data)}</dd>
                </div>
              )}
              {lead.data.last_call_headline && (
                <div className="flex flex-wrap gap-x-3">
                  <dt className="text-body text-ink-muted">Last call</dt>
                  <dd className="text-body text-ink">{lead.data.last_call_headline}</dd>
                </div>
              )}
            </dl>
          )}

          {/* What the agents captured about this person, under the business's own labels. */}
          <div className="mt-4">
            <LeadCaptured session={session} leadId={leadId} />
          </div>

          {/* The stage and owner are CHANGEABLE here (ux-audit LD1): this page is where the
              decision is made, with the same shared selects and mutation as the table. */}
          <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2 lg:max-w-xl">
            <div className="flex flex-col gap-1">
              <span className="text-meta font-medium text-ink-muted">Stage</span>
              <StatusSelect
                value={lead.data.status}
                label={`Stage for ${lead.data.name ?? lead.data.phone_e164}`}
                disabled={!mayAssign.allowed || editLead.isPending}
                onChange={(next) => editLead.mutate({ leadId, edit: { status: next } })}
                className="h-9 rounded-md border border-line bg-surface px-2 text-sm capitalize text-ink disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11"
              />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-meta font-medium text-ink-muted">Owner</span>
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
                className="h-9 rounded-md border border-line bg-surface px-2 text-sm text-ink touch:min-h-11"
              />
            </div>
          </div>
          <div className="mt-2">
            <RestrictionNote reason={mayAssign.reason} />
          </div>
        </section>
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

      <LeadTimeline
        timeline={timeline}
        events={events}
        timelineTotal={timelineTotal}
        impersonating={me.data?.impersonating}
        slug={slug}
        href={href}
      />
    </div>
  );
}
