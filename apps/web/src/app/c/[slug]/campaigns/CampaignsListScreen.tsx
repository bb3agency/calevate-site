"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { StatusPill } from "@/components/console/statusPill";
import { Pagination } from "@/components/interior/pagination";
import {
  FIELD,
  FilterChip,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  usePauseCampaign,
  useCampaignPage,
  type CampaignStatus,
  type CampaignSummary,
} from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { TrialLockNotice } from "../TrialLockNotice";
import { LIST_PROVENANCE_COPY } from "./blockerCopy";
import { CampaignStatusPill, ReachBar } from "./campaignStatus";

/**
 * How far a row has got. A campaign that has not started has no progress to draw, so it
 * says how many people are on it rather than "0 of 342 reached" under an empty bar.
 */
function RowProgress({ campaign }: { campaign: CampaignSummary }) {
  if (campaign.status === "draft" || campaign.status === "scheduled") {
    return (
      <span className="whitespace-nowrap text-xs tabular-nums text-ink-muted">
        {formatCount(campaign.contacts)} {campaign.contacts === 1 ? "person" : "people"} on the list
      </span>
    );
  }
  return <ReachBar reached={campaign.connected} total={campaign.contacts} />;
}

const PAGE_SIZE = 25;

/** The status tabs, in the order a campaign moves through them. */
const FILTERS: { value: CampaignStatus | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "scheduled", label: "Scheduled" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Finished" },
  { value: "cancelled", label: "Stopped" },
];

function initialStatus(value: string | null): CampaignStatus | undefined {
  return FILTERS.find((f) => f.value === value)?.value;
}

/**
 * `/c/{slug}/campaigns`: every campaign, a page at a time (FLOWS §5).
 *
 * The page, the search and the status filter are the server's (`GET /v1/campaigns/page`),
 * so a client with three hundred campaigns sees a true count and a true order; the status
 * filter starts from `?status=` so a link can open "Paused". Each name is a link to the
 * campaign's own address, so Back and a shared link both work.
 *
 * A row offers the one action its state allows: Pause or Resume. Launch is never a row
 * action, because a launch restates what it will do and asks for the count to be typed
 * (`LaunchConfirm`), which a list row would skip.
 */
export function CampaignsListScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const params = useSearchParams();
  const [status, setStatus] = useState<CampaignStatus | undefined>(() =>
    initialStatus(params.get("status")),
  );
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);
  const campaigns = useCampaignPage(session, { page, pageSize: PAGE_SIZE, status, search });
  const [rowError, setRowError] = useState<unknown>(null);

  const data = campaigns.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const everything = data ? Object.values(data.status_counts).reduce((a, b) => a + b, 0) : 0;
  const detail = (id: string) => href(`/c/${slug}/campaigns/${id}`);

  const columns: DataColumn<CampaignSummary>[] = [
    {
      id: "name",
      header: "Campaign",
      cell: (row) => <NameCell campaign={row} href={detail(row.id)} />,
      className: "sm:min-w-[14rem]",
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => <CampaignStatusPill status={row.status} pauseReason={row.pause_reason} />,
      flash: (row) => `${row.status}:${row.pause_reason ?? ""}`,
      hideBelow: "sm",
    },
    {
      id: "reach",
      header: "Reached",
      cell: (row) => <RowProgress campaign={row} />,
      flash: (row) => `${row.connected}/${row.contacts}`,
      hideBelow: "sm",
    },
    {
      id: "launched",
      header: "Started",
      cell: (row) => (
        <span className="whitespace-nowrap text-meta text-ink-muted">
          {row.launched_at ? formatIST(row.launched_at) : "Not started"}
        </span>
      ),
      hideBelow: "md",
    },
    ...(data?.items.some((row) => row.status === "running" || row.status === "paused") ? [{
      id: "actions",
      header: "Actions",
      align: "right",
      // On a phone the row is a stacked card and its Pause lives on the campaign page.
      hideBelow: "sm",
      cell: (row) => (
        <RowActions campaign={row} canWrite={write.allowed} refusal={refusal} onError={setRowError} />
      ),
    } satisfies DataColumn<CampaignSummary>] : []),
  ];

  return (
    <div className="max-w-5xl space-y-5 pb-12">
      <PageHeader
        description="Call a list of people with one of your agents."
        actions={
          write.allowed ? (
            <Link href={href(`/c/${slug}/campaigns/new`)} className={PRIMARY_BUTTON}>
              New campaign
            </Link>
          ) : (
            <span title={refusal} aria-disabled className={`${PRIMARY_BUTTON} cursor-not-allowed opacity-60`}>
              New campaign
            </span>
          )
        }
      />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />
      {rowError != null && <ProblemNotice error={rowError} />}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div role="group" aria-label="Show campaigns by status" className="flex flex-wrap gap-1.5">
          {FILTERS.map((filter) => {
            const count = filter.value ? data?.status_counts[filter.value] : everything;
            return (
              <FilterChip
                key={filter.label}
                label={data ? `${filter.label} ${formatCount(count ?? 0)}` : filter.label}
                active={status === filter.value}
                onClick={() => {
                  setStatus(filter.value);
                  setPage(1);
                }}
              />
            );
          })}
        </div>
        <label className="block w-full sm:w-64">
          <span className="sr-only">Search campaigns by name</span>
          <input
            type="search"
            value={search}
            placeholder="Search by name"
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className={FIELD}
          />
        </label>
      </div>

      {campaigns.isLoading ? (
        <Skeleton rows={4} />
      ) : !data ? (
        <ProblemNotice
          error={campaigns.error ?? new Error("Your campaigns did not load.")}
          onRetry={() => campaigns.refetch()}
        />
      ) : data.items.length === 0 ? (
        everything === 0 ? (
          <EmptyState
            illustration={<EmptySketch kind="campaigns" />}
            message="No campaigns yet."
            hint="Start one with New campaign: your agent calls the people you add."
          />
        ) : (
          <p className="text-body text-ink-muted">No campaign matches. Clear the search or choose All.</p>
        )
      ) : (
        <div className="space-y-4">
          {campaigns.error ? <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} /> : null}
          <DataTable label="Your campaigns" rows={data.items} columns={columns} getRowId={(row) => row.id} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-meta text-ink-muted">
              {formatCount(data.total)} {data.total === 1 ? "campaign" : "campaigns"}
            </p>
            {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="Campaign pages" />}
          </div>
        </div>
      )}
    </div>
  );
}

/** The name links to the campaign; a draft held on its consent answer says so under it. */
function NameCell({ campaign, href }: { campaign: CampaignSummary; href: string }) {
  const note = lookup(LIST_PROVENANCE_COPY, campaign.consent_provenance_blocker ?? null);
  return (
    <div className="min-w-0">
      <Link
        href={href}
        className="rounded-sm text-sm font-semibold text-ink after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        {campaign.name}
      </Link>
      <p className="flex flex-wrap items-center gap-x-2 text-meta text-ink-muted">
        <span className="capitalize">{campaign.classification}</span>
        <span className="sm:hidden">
          <CampaignStatusPill status={campaign.status} pauseReason={campaign.pause_reason} />
        </span>
      </p>
      <div className="mt-1.5 sm:hidden">
        <RowProgress campaign={campaign} />
      </div>
      {note && (
        <StatusPill tone={note.tone} wrap className="mt-1">
          {note.badge}
        </StatusPill>
      )}
    </div>
  );
}

/**
 * Pause or Resume, bound to the row's own id. A paused campaign whose automatic reason
 * still holds is refused by the server with that reason, which is reported above the table.
 */
function RowActions({
  campaign,
  canWrite,
  refusal,
  onError,
}: {
  campaign: CampaignSummary;
  canWrite: boolean;
  refusal: string | undefined;
  onError: (error: unknown) => void;
}) {
  const { session } = useClientRealm();
  const setStatus = usePauseCampaign(session, campaign.id);
  useEffect(() => {
    if (setStatus.error) onError(setStatus.error);
  }, [setStatus.error, onError]);
  if (campaign.status !== "running" && campaign.status !== "paused") return null;
  // A pause whose cause must be cleared first (a review, credit, the cap) is resumed from
  // the campaign's own page, where the cause and its fix are shown.
  const held = ["complaint_spike", "out_of_credit", "spend_cap"].includes(campaign.pause_reason ?? "");
  if (campaign.status === "paused" && held) return null;
  const action = campaign.status === "running" ? "pause" : "resume";
  return (
    <div className="relative z-raised flex justify-end">
      <button
        type="button"
        title={refusal}
        disabled={!canWrite || setStatus.isPending}
        onClick={() => setStatus.mutate(action)}
        aria-label={`${action === "pause" ? "Pause" : "Resume"} ${campaign.name}`}
        className={SECONDARY_BUTTON_SM}
      >
        {action === "pause" ? <Pause aria-hidden className="h-3.5 w-3.5" /> : <Play aria-hidden className="h-3.5 w-3.5" />}
        <span className="hidden sm:inline">{action === "pause" ? "Pause" : "Resume"}</span>
      </button>
    </div>
  );
}
