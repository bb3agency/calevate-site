"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Pause, Play, Plus } from "lucide-react";

import { ChipGroup } from "@/components/arc/chip-group";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar } from "@/components/arc/filter-toolbar";
import { SearchField } from "@/components/arc/search-field";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { StatusPill } from "@/components/console/statusPill";
import { Pagination } from "@/components/interior/pagination";
import {
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  RestrictionNote,
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
        {formatCount(campaign.contacts)} {campaign.contacts === 1 ? "person" : "people"}
      </span>
    );
  }
  return <ReachBar reached={campaign.connected} total={campaign.contacts} />;
}

const PAGE_SIZE = 25;

/** The status filters, in the order a campaign moves through them ("All" is the chip group's own). */
const STATUS_FILTERS: { value: CampaignStatus; label: string }[] = [
  { value: "draft", label: "Drafts" },
  { value: "scheduled", label: "Scheduled" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Finished" },
  { value: "cancelled", label: "Stopped" },
];

function initialStatus(value: string | null): CampaignStatus | undefined {
  return STATUS_FILTERS.find((f) => f.value === value)?.value;
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
  // What is typed, and the settled query the server is asked for (`SearchField.onSearch`).
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const refusal = write.allowed ? undefined : (write.reason ?? undefined);
  const campaigns = useCampaignPage(session, { page, pageSize: PAGE_SIZE, status, search });

  const data = campaigns.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const everything = data ? Object.values(data.status_counts).reduce((a, b) => a + b, 0) : 0;
  const detail = (id: string) => href(`/c/${slug}/campaigns/${id}`);
  const newHref = href(`/c/${slug}/campaigns/new`);
  const at = (path: string) => href(`/c/${slug}${path}`);

  const chooseStatus = (next: CampaignStatus | undefined) => {
    setStatus(next);
    setPage(1);
  };
  const runSearch = (query: string) => {
    setSearch(query);
    setPage(1);
  };
  const clearAll = () => {
    setTyped("");
    runSearch("");
    chooseStatus(undefined);
  };
  const statusLabel = STATUS_FILTERS.find((filter) => filter.value === status)?.label;
  const active = [
    ...(status && statusLabel
      ? [{ id: "status", label: `Status: ${statusLabel}`, onRemove: () => chooseStatus(undefined) }]
      : []),
    ...(search
      ? [
          {
            id: "search",
            label: `Name: ${search}`,
            onRemove: () => {
              setTyped("");
              runSearch("");
            },
          },
        ]
      : []),
  ];

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
    ...(data?.items.some((row) => hasRowAction(row)) ? [{
      id: "actions",
      header: "Actions",
      align: "right",
      // On a phone the row is a stacked card and its actions live on the campaign page.
      hideBelow: "sm",
      cell: (row) => (
        <RowActions campaign={row} canWrite={write.allowed} refusal={refusal} at={at} detail={detail(row.id)} />
      ),
    } satisfies DataColumn<CampaignSummary>] : []),
  ];

  return (
    <div className="max-w-5xl space-y-5 pb-12">
      <PageHeader
        description="Your agent calls a list of people for you."
        actions={
          write.allowed ? (
            <Link href={newHref} className={PRIMARY_BUTTON}>
              <Plus aria-hidden className="h-4 w-4" />
              New campaign
            </Link>
          ) : (
            <span title={refusal} aria-disabled className={`${PRIMARY_BUTTON} cursor-not-allowed opacity-60`}>
              <Plus aria-hidden className="h-4 w-4" />
              New campaign
            </span>
          )
        }
      />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />
      <FilterToolbar
        search={
          <SearchField
            label="Search campaigns by name"
            hideLabel
            placeholder="Search by name"
            value={typed}
            onValueChange={setTyped}
            onSearch={runSearch}
            slashToFocus
            className="w-full sm:w-64"
          />
        }
        filters={
          <ChipGroup
            mode="single"
            label="Show campaigns by status"
            value={status ?? null}
            onChange={(next) => chooseStatus(initialStatus(next))}
            allLabel={data ? `All ${formatCount(everything)}` : "All"}
            chips={STATUS_FILTERS.map((filter) => ({
              value: filter.value,
              label: data ? `${filter.label} ${formatCount(data.status_counts[filter.value] ?? 0)}` : filter.label,
            }))}
          />
        }
        active={active}
        onClearAll={clearAll}
        count={data ? { shown: data.total, total: everything, noun: "campaign" } : undefined}
      />

      {campaigns.isLoading ? (
        <Skeleton rows={4} />
      ) : !data ? (
        <EmptyState
          variant="error"
          message="Your campaigns did not load."
          error={campaigns.error}
          onRetry={() => void campaigns.refetch()}
        />
      ) : data.items.length === 0 ? (
        everything === 0 ? (
          <EmptyState
            illustration={<EmptySketch kind="campaigns" />}
            message="No campaigns yet."
            hint="Your agent calls the people you add."
            action={
              write.allowed ? (
                <Link href={newHref} className={PRIMARY_BUTTON}>
                  Start your first campaign
                </Link>
              ) : undefined
            }
          />
        ) : (
          <EmptyState variant="filtered" message="No campaign matches." onClear={clearAll} clearLabel="Show all campaigns" />
        )
      ) : (
        <div className="space-y-4">
          {campaigns.error ? <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} /> : null}
          <DataTable label="Your campaigns" rows={data.items} columns={columns} getRowId={(row) => row.id} />
          {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="Campaign pages" />}
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

/** A pause whose cause must be cleared before Resume works. */
const HELD_PAUSES = ["complaint_spike", "out_of_credit", "spend_cap"];

function hasRowAction(row: CampaignSummary): boolean {
  return row.status === "running" || row.status === "paused" || Boolean(row.consent_provenance_blocker);
}

/**
 * The fix for a row that is stuck, as a button-styled link: the way out of a held pause
 * (add credit, raise the limit, review the opt-outs) or the draft's missing consent answer,
 * which is given on the campaign's own page.
 */
function rowFix(
  campaign: CampaignSummary,
  at: (path: string) => string,
  detail: string,
): { href: string; label: string } | null {
  if (campaign.status === "paused") {
    if (campaign.pause_reason === "out_of_credit") return { href: at("/billing?tab=credits"), label: "Add credit" };
    if (campaign.pause_reason === "spend_cap") return { href: at("/billing?tab=usage"), label: "Raise limit" };
    if (campaign.pause_reason === "complaint_spike") return { href: detail, label: "Review" };
  }
  if (campaign.consent_provenance_blocker === "consent_provenance_missing") return { href: detail, label: "Answer" };
  if (campaign.consent_provenance_blocker === "consent_source_refused") return { href: detail, label: "Correct" };
  return null;
}

/**
 * Pause or Resume, bound to the row's own id, or the row's fix when it is stuck. The new
 * state shows in the row's own status pill, so success needs no toast; a refusal is toasted
 * with the server's reason.
 */
function RowActions({
  campaign,
  canWrite,
  refusal,
  at,
  detail,
}: {
  campaign: CampaignSummary;
  canWrite: boolean;
  refusal: string | undefined;
  at: (path: string) => string;
  detail: string;
}) {
  const { session } = useClientRealm();
  const setStatus = usePauseCampaign(session, campaign.id);
  const feedback = useActionFeedback(setStatus, {
    errorTitle: `Could not change ${campaign.name}`,
  });
  // A pause whose cause must be cleared first is not resumed from the row: its fix is.
  const held = campaign.status === "paused" && HELD_PAUSES.includes(campaign.pause_reason ?? "");
  const fix = rowFix(campaign, at, detail);
  if (fix && (held || campaign.status === "draft")) {
    return (
      <div className="relative z-raised flex justify-end">
        <Link href={fix.href} className={SECONDARY_BUTTON_SM} aria-label={`${fix.label}: ${campaign.name}`}>
          {fix.label}
        </Link>
      </div>
    );
  }
  if (campaign.status !== "running" && campaign.status !== "paused") return null;
  if (held) return null;
  const action = campaign.status === "running" ? "pause" : "resume";
  return (
    <div className="relative z-raised flex justify-end">
      <ActionButton
        variant="secondary-sm"
        title={refusal}
        disabled={!canWrite}
        status={feedback.status}
        successLabel={action === "pause" ? "Paused" : "Resumed"}
        onClick={() => feedback.run(action)}
        aria-label={`${action === "pause" ? "Pause" : "Resume"} ${campaign.name}`}
      >
        {action === "pause" ? <Pause aria-hidden className="h-3.5 w-3.5" /> : <Play aria-hidden className="h-3.5 w-3.5" />}
        {action === "pause" ? "Pause" : "Resume"}
      </ActionButton>
    </div>
  );
}
