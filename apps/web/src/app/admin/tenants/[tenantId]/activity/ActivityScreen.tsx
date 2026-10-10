"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Eye } from "lucide-react";

import { StatusPill } from "@/components/admin/kit";
import {
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { useTenant } from "@/lib/api/admin";
import {
  ACTIVITY_PAGE_SIZE,
  ACTOR_LABELS,
  useTenantActivity,
  type ActivityEntry,
  type ActorType,
} from "@/lib/api/adminAccount";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

type ActorFilter = ActorType | "all";

const ACTOR_FILTERS: { value: ActorFilter; label: string }[] = [
  { value: "all", label: "everyone" },
  { value: "admin", label: "us" },
  { value: "user", label: "the client" },
  { value: "system", label: "automatic" },
];

function isActorFilter(value: string): value is ActorFilter {
  return ACTOR_FILTERS.some((option) => option.value === value);
}

/** The operator's name when we have one, else the actor class: a bare uuid answers nothing. */
function who(entry: ActivityEntry): string {
  return entry.actor_label ?? lookup(ACTOR_LABELS, entry.actor_type) ?? entry.actor_type;
}

/**
 * Marks an act done from a view-as session (D-587): "the client did this" and "one of us did
 * this as the client" must never read as the same row. Warn tone for visibility, not suspicion.
 */
function ViewAsMark() {
  return (
    <span title="Done from a view-as session: one of us, acting inside the client's console">
      <StatusPill tone="warn" className="gap-1">
        <Eye aria-hidden className="h-3 w-3" />
        as the client
      </StatusPill>
    </span>
  );
}

function onText(entry: ActivityEntry) {
  if (!entry.object_type) return "—";
  return (
    <>
      {entry.object_type}
      {entry.object_id && <span className="ml-1 break-all font-mono">{entry.object_id}</span>}
    </>
  );
}

/*
 * No column sorts. The rows are one server page of a newest-first ledger, so reordering a
 * page in the browser would misstate the order of the trail.
 *
 * Below `sm` the Action cell carries the whole entry and the other columns drop out, so
 * a phone reads a stacked list instead of scrolling a 720px table sideways.
 */
const COLUMNS: DataColumn<ActivityEntry>[] = [
  {
    id: "at",
    header: "When (IST)",
    hideBelow: "sm",
    className: "whitespace-nowrap text-meta text-ink-muted",
    cell: (entry) => formatIST(entry.at),
  },
  {
    id: "action",
    header: "Action",
    cell: (entry) => (
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {/* Printed as itself: the vocabulary is open, and a translation table would drop
              or mislabel the names it did not know. */}
          <span className="break-all font-mono text-xs text-ink">{entry.action}</span>
          {entry.via_grant_id && <ViewAsMark />}
        </div>
        <p className="mt-1 text-meta text-ink-muted sm:hidden">
          {who(entry)} · {formatIST(entry.at)}
        </p>
        {entry.object_type && (
          <p className="mt-0.5 text-meta text-ink-muted sm:hidden">On {onText(entry)}</p>
        )}
      </div>
    ),
  },
  {
    id: "who",
    header: "Who",
    hideBelow: "sm",
    className: "text-meta text-ink-muted",
    cell: (entry) => who(entry),
  },
  {
    id: "on",
    header: "On",
    hideBelow: "sm",
    className: "text-meta text-ink-muted",
    cell: (entry) => onText(entry),
  },
];

/**
 * What has been done to this account, and by whom, read from `audit_log` — the existing
 * hash-chained, append-only ledger — rather than a second history table that nobody could
 * verify. It answers WHO, WHAT and WHEN, not WHAT CHANGED: the ledger carries no free-form
 * payload (a hashed row holding whatever a caller passed could hold a phone number), so the
 * before-and-after of an act lives on the screen that performed it.
 */
export function ActivityScreen({ tenantId }: { tenantId: string }) {
  const [actorType, setActorType] = useState<ActorFilter>("all");
  const [offset, setOffset] = useState(0);
  const tenantQuery = useTenant(tenantId);
  const activity = useTenantActivity(tenantId, { offset, actorType });

  const page = activity.data;
  const entries = page?.entries ?? [];

  /*
   * Counts and action names, not rows. The actor labels are NOT declared: they name
   * Calevate staff, and a colleague's name has no business in a model conversation.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/activity",
    title: "Account activity",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenantQuery.data?.name ?? "could not be read" },
      {
        key: "total",
        label: "Audited acts recorded against this account, matching the current filter",
        value: page ? String(page.total) : activity.error ? "could not be read" : "still loading",
      },
      {
        key: "actions",
        label: "The action names on the page being read",
        value: entries.length
          ? Array.from(new Set(entries.map((entry) => entry.action))).join(", ")
          : "none",
      },
      {
        key: "view_as",
        label: "How many acts on this page were done from a view-as session",
        value: String(entries.filter((entry) => entry.via_grant_id).length),
      },
    ],
    apply: noFill,
  });

  function refilter(next: ActorFilter) {
    setActorType(next);
    // Offsets of one filtered set mean nothing in another.
    setOffset(0);
  }

  return (
    <div className="max-w-5xl space-y-8">
      <PageHeader
        title="Activity"
        description={
          <>
            Every audited act on this account, newest first — ours and theirs.{" "}
            <InfoTip label="the activity trail">
              <p>
                This is a view of the tamper-evident audit ledger itself, so nothing on it
                can be edited or removed.
              </p>
              <p>
                It says who acted and what they did; what a change contained lives on the
                screen that made it.
              </p>
              <p>
                Each row is a link in a hash chain. The chain itself is verified from the ops
                switchboard, which reports any entry that has been altered since it was
                written.
              </p>
            </InfoTip>
          </>
        }
        actions={
          <SegmentedControl
            label="Acts by"
            options={ACTOR_FILTERS}
            value={actorType}
            onValueChange={(value) => {
              if (isActorFilter(value)) refilter(value);
            }}
          />
        }
      />

      {activity.isLoading ? (
        <Skeleton rows={5} />
      ) : activity.error ? (
        /* "Nothing has been done to this account" is a claim about the record, and a
           failed read is not evidence for it. */
        <ProblemNotice error={activity.error} onRetry={() => void activity.refetch()} />
      ) : entries.length === 0 ? (
        <EmptyState
          message={
            actorType === "all"
              ? "Nothing has been recorded against this account yet."
              : "Nothing matches this filter."
          }
          action={
            actorType === "all" ? undefined : (
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => refilter("all")}>
                Show everyone
              </button>
            )
          }
        />
      ) : (
        <DataTable
          label="Account activity"
          rows={entries}
          columns={COLUMNS}
          getRowId={(entry) => entry.id}
          rowClassName={() => "align-top"}
        />
      )}

      {page && page.total > entries.length && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-meta text-ink-muted">
          <span aria-live="polite">
            Showing {formatCount(page.offset + 1)}–{formatCount(page.offset + entries.length)} of{" "}
            {formatCount(page.total)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset === 0}
              onClick={() => setOffset(Math.max(0, page.offset - ACTIVITY_PAGE_SIZE))}
            >
              <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
              Newer
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset + entries.length >= page.total}
              onClick={() => setOffset(page.offset + ACTIVITY_PAGE_SIZE)}
            >
              Older
              <ChevronRight aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
