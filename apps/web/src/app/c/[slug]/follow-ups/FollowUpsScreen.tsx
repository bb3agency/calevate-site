"use client";

import Link from "next/link";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { StatusPill } from "@/components/console/statusPill";
import { ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import { useFollowUps, type FollowUpSummaryOut } from "@/lib/api/followUps";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { lookup } from "@/lib/lookup";

import { STATUS_TONES, STATUS_WORDS } from "./followUpCopy";
import { NewFollowUpButton, Starters } from "./Starters";

/**
 * FOLLOW-UPS (D-940).
 *
 * PRIMARY JOB: see which Follow-ups are on and how many leads each is taking through, and
 * start a new one.
 *
 * - "New Follow-up" opens Pip with the request written; Pip builds it from a sentence.
 *   There is no builder here (founder decision 3).
 * - The ready-made ones sit under the list as buttons; choosing one makes a draft and
 *   opens it, so nothing calls anybody until the owner publishes.
 * - Loading, failure and empty are three states; "No Follow-ups yet" is said only from a
 *   list the server sent.
 */
export function FollowUpsScreen() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const me = useMe(session);
  const list = useFollowUps(session);
  const write = useWriteAccess(session, "leads:dispatch", "change Follow-ups");
  const rows = list.data?.items;

  useCopilotSurface({
    route: "/c/{slug}/follow-ups",
    title: "Follow-ups",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: rows ? "the Follow-ups below have loaded" : list.error ? "the list failed to load" : "still loading",
      },
      ...(rows
        ? [
            {
              key: "follow_ups",
              label: "Follow-ups",
              value:
                rows.map((row) => `${row.name} (${lookup(STATUS_WORDS, row.status) ?? row.status})`).join("; ") ||
                "none",
            },
          ]
        : []),
      { key: "can_change", label: "Can this person change them?", value: write.allowed ? "yes" : "no" },
    ],
    // Nothing to fill: Pip changes a Follow-up through its own tools, not this screen.
    apply: () => {},
  });

  const refused = me.data !== undefined && !me.data.permissions.includes("leads:read");
  if (refused) {
    return <RestrictionNote reason="Only people who can see leads can see Follow-ups." />;
  }

  const columns: DataColumn<FollowUpSummaryOut>[] = [
    {
      id: "name",
      header: "Follow-up",
      sort: { value: (row) => row.name },
      cell: (row) => (
        <div className="min-w-0">
          <Link
            href={href(`/c/${slug}/follow-ups/${row.id}`)}
            className="font-medium text-ink underline-offset-2 after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {row.name}
          </Link>
          <p className="text-meta text-ink-muted sm:hidden">{row.starts_when}</p>
        </div>
      ),
    },
    {
      id: "trigger",
      header: "Starts when",
      hideBelow: "sm",
      cell: (row) => <span className="text-ink-muted">{row.starts_when}</span>,
    },
    {
      id: "status",
      header: "Status",
      flash: (row) => row.status,
      cell: (row) => (
        <span className="inline-flex flex-col items-end gap-0.5 sm:items-start">
          <StatusPill tone={lookup(STATUS_TONES, row.status) ?? "neutral"}>
            {lookup(STATUS_WORDS, row.status) ?? row.status}
          </StatusPill>
          {row.has_unpublished_changes && row.status !== "draft" && (
            <span className="text-meta text-ink-muted">Changes not published</span>
          )}
        </span>
      ),
    },
    {
      id: "running",
      header: "Running now",
      align: "right",
      sort: { value: (row) => row.counts.running + row.counts.waiting, kind: "number" },
      cell: (row) => (
        <span className="tabular-nums text-ink">{formatCount(row.counts.running + row.counts.waiting)}</span>
      ),
    },
    {
      id: "goal",
      header: "Reached goal, 30 days",
      align: "right",
      sort: { value: (row) => row.counts.goal_30d, kind: "number" },
      cell: (row) => <span className="tabular-nums text-ink">{formatCount(row.counts.goal_30d)}</span>,
    },
  ];

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader
        description="Steps each lead goes through on its own: calls, waits, messages."
        actions={write.allowed ? <NewFollowUpButton /> : undefined}
      />

      <RestrictionNote reason={write.reason} />

      {list.error && <ProblemNotice error={list.error} onRetry={() => void list.refetch()} />}
      <div className="border-y border-line">
        {list.isLoading ? (
          <div className="py-4">
            <Skeleton rows={4} label="Loading your Follow-ups" />
          </div>
        ) : !rows ? null : rows.length ? (
          <DataTable label="Your Follow-ups" rows={rows} columns={columns} getRowId={(row) => row.id} />
        ) : (
          <EmptyState
            message="No Follow-ups yet."
            hint={write.allowed ? "Pick a ready-made one below, or describe your own to Pip." : undefined}
          />
        )}
      </div>

      {write.allowed && rows && (
        <Starters session={session} href={href} taken={new Set(rows.flatMap((row) => (row.starter ? [row.starter] : [])))} />
      )}
    </div>
  );
}
