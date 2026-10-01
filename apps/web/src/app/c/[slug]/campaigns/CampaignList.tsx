"use client";

import { useEffect } from "react";
import { Pause, Play } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import {
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { usePauseCampaign, type CampaignSummary } from "@/lib/api/campaigns";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { LIST_PROVENANCE_COPY } from "./blockerCopy";
import { CampaignStatusPill, ReachBar } from "./campaignStatus";

/**
 * THE LANDING LIST: every campaign, its state, how far it has got, and the one action its
 * state allows.
 *
 * §52 as three exclusive branches: a skeleton while the read is in flight, a refusal when
 * it failed or was PAUSED (offline: not loading, no error, no data), and the rows (or the
 * empty state) only from a response that arrived.
 *
 * Launch is never a row action that dials. A draft's row offers "Launch…", which opens
 * the campaign at its launch checklist, because a launch restates what it will do and asks
 * for the count to be typed (`LaunchConfirm`); a one-click launch from a list would skip
 * exactly that.
 */
export function CampaignList({
  campaigns,
  onOpen,
  canWrite,
  refusal,
  onRowError,
}: {
  campaigns: {
    data: CampaignSummary[] | undefined;
    isLoading: boolean;
    error: unknown;
    refetch: () => void;
  };
  onOpen: (campaignId: string) => void;
  canWrite: boolean;
  refusal: string | undefined;
  onRowError: (error: unknown) => void;
}) {
  if (campaigns.isLoading) return <Skeleton rows={3} />;
  if (!campaigns.data) {
    // A failed read already renders its notice at the top of the screen; a PAUSED one has
    // no error to render, so it is refused here rather than read as "no campaigns".
    return campaigns.error ? null : (
      <ProblemNotice
        error={new Error("Your campaigns did not load.")}
        onRetry={() => campaigns.refetch()}
      />
    );
  }
  if (campaigns.data.length === 0) {
    return (
      <EmptyState message="No campaigns yet. Start one with New campaign." />
    );
  }

  const columns: DataColumn<CampaignSummary>[] = [
    {
      id: "name",
      header: "Campaign",
      sort: { value: (row) => row.name },
      cell: (row) => <NameCell campaign={row} onOpen={onOpen} />,
      className: "sm:min-w-[12rem]",
    },
    {
      id: "status",
      header: "Status",
      sort: { value: (row) => row.status },
      cell: (row) => <CampaignStatusPill status={row.status} />,
      flash: (row) => row.status,
      hideBelow: "sm",
    },
    {
      id: "reach",
      header: "Progress",
      sort: { value: (row) => row.connected, kind: "number" },
      cell: (row) => <ReachBar reached={row.connected} total={row.contacts} />,
      hideBelow: "sm",
      flash: (row) => `${row.connected}/${row.contacts}`,
    },
    {
      id: "launched",
      header: "Launched",
      sort: { value: (row) => row.launched_at, kind: "time", first: "desc" },
      cell: (row) => (
        <span className="whitespace-nowrap text-xs text-ink-muted">
          {row.launched_at ? formatIST(row.launched_at) : "Not launched"}
        </span>
      ),
      hideBelow: "md",
    },
    {
      id: "actions",
      header: "Actions",
      align: "right",
      cell: (row) => (
        <RowActions
          campaign={row}
          onOpen={onOpen}
          canWrite={canWrite}
          refusal={refusal}
          onError={onRowError}
        />
      ),
    },
  ];

  return (
    <DataTable
      label="Your campaigns"
      rows={campaigns.data}
      columns={columns}
      getRowId={(row) => row.id}
    />
  );
}

/**
 * The name opens the campaign, stretched over the row (one target per row). A draft held
 * on its list's consent answer says so under the name, in `LIST_PROVENANCE_COPY`'s words;
 * the rule name itself is the gate's vocabulary and never rendered.
 */
function NameCell({
  campaign,
  onOpen,
}: {
  campaign: CampaignSummary;
  onOpen: (campaignId: string) => void;
}) {
  // `lookup`, not indexing: `LIST_PROVENANCE_COPY["constructor"]` is truthy.
  const note = lookup(LIST_PROVENANCE_COPY, campaign.consent_provenance_blocker ?? null);
  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => onOpen(campaign.id)}
        className="rounded-sm text-left text-sm font-semibold text-ink after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        {campaign.name}
      </button>
      <p className="flex items-center gap-2 text-xs capitalize text-ink-faint">
        {campaign.classification}
        {/* Below `sm` the status column is dropped, so the pill rides here. */}
        <span className="sm:hidden">
          <CampaignStatusPill status={campaign.status} />
        </span>
      </p>
      {/* Visible below `sm`, where the progress column is dropped. */}
      <div className="mt-1.5 sm:hidden">
        <ReachBar reached={campaign.connected} total={campaign.contacts} />
      </div>
      {note && (
        <p className="relative z-[1] mt-1 max-w-md text-xs text-ink-muted">
          <span
            className={`mr-1.5 inline-flex rounded-full border px-1.5 py-0.5 text-[11px] font-medium ${note.badgeClass}`}
          >
            {note.badge}
          </span>
          {note.text}{" "}
          <button
            type="button"
            onClick={() => onOpen(campaign.id)}
            className="rounded-sm font-semibold text-ink underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {note.action}
          </button>
        </p>
      )}
    </div>
  );
}

/**
 * The action the row's state allows: Pause a running campaign, Resume a paused one, open a
 * draft at its launch check. One `usePauseCampaign` per row, bound to that row's id, so a
 * pause here invalidates exactly the queries the detail view's pause would.
 */
function RowActions({
  campaign,
  onOpen,
  canWrite,
  refusal,
  onError,
}: {
  campaign: CampaignSummary;
  onOpen: (campaignId: string) => void;
  canWrite: boolean;
  refusal: string | undefined;
  onError: (error: unknown) => void;
}) {
  const session = useClientSession();
  const setStatus = usePauseCampaign(session, campaign.id);
  const toggle = campaign.status === "running" || campaign.status === "paused";
  const action = campaign.status === "running" ? "pause" : "resume";
  // A refused pause (403, 409, a timeout) is reported above the table, never swallowed.
  useEffect(() => {
    if (setStatus.error) onError(setStatus.error);
  }, [setStatus.error, onError]);

  return (
    <div className="relative z-[1] flex items-center justify-end gap-1">
      {toggle ? (
        <button
          type="button"
          title={refusal}
          disabled={!canWrite || setStatus.isPending}
          onClick={() => setStatus.mutate(action)}
          aria-label={`${action === "pause" ? "Pause" : "Resume"} ${campaign.name}`}
          className={SECONDARY_BUTTON_SM}
        >
          {action === "pause" ? (
            <Pause aria-hidden className="h-3.5 w-3.5" />
          ) : (
            <Play aria-hidden className="h-3.5 w-3.5" />
          )}
          <span className="hidden sm:inline">
            {action === "pause" ? "Pause" : "Resume"}
          </span>
        </button>
      ) : campaign.status === "draft" && campaign.consent_provenance_blocker !== "consent_source_refused" ? (
        <button
          type="button"
          onClick={() => onOpen(campaign.id)}
          aria-label={`Launch ${campaign.name}…`}
          className={SECONDARY_BUTTON_SM}
        >
          Launch…
        </button>
      ) : null}
    </div>
  );
}
