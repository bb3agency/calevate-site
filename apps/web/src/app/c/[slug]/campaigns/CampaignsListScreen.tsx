"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Pause, Play, Plus } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { SearchField } from "@/components/arc/search-field";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { HowItWorks } from "@/components/console/howItWorks";
import { PageHeader } from "@/components/console/pageHeader";
import { StatusPill } from "@/components/console/statusPill";
import { FlashValue } from "@/components/console/valueFlash";
import { Pagination } from "@/components/interior/pagination";
import { SegmentedControl, type SegmentedOption } from "@/components/interior/segmented-control";
import {
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_LG,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  RestrictionNote,
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
import { CampaignStatusPill } from "./campaignStatus";

const PAGE_SIZE = 25;
const ALL = "all";

/**
 * The status segments. Running and Paused lead because they are the two a person may have
 * to act on today; the rest follow the order a campaign moves through. A status nobody has
 * is not offered (see `segmentOptions`), so a new account sees two or three choices rather
 * than seven.
 */
const STATUS_FILTERS: { value: CampaignStatus; label: string; dot?: string }[] = [
  { value: "running", label: "Running", dot: "bg-brand" },
  { value: "paused", label: "Paused", dot: "bg-chart-warn" },
  { value: "scheduled", label: "Scheduled" },
  { value: "draft", label: "Drafts" },
  { value: "completed", label: "Finished" },
  { value: "cancelled", label: "Stopped" },
];

function initialStatus(value: string | null): CampaignStatus | undefined {
  return STATUS_FILTERS.find((f) => f.value === value)?.value;
}

function segmentOptions(
  counts: Record<string, number> | undefined,
  everything: number,
  chosen: CampaignStatus | undefined,
): SegmentedOption[] {
  const all: SegmentedOption = { value: ALL, label: "All", count: counts ? formatCount(everything) : undefined };
  if (!counts) return [all];
  return [
    all,
    ...STATUS_FILTERS.filter((f) => (counts[f.value] ?? 0) > 0 || f.value === chosen).map((f) => ({
      value: f.value,
      label: f.label,
      dot: f.dot,
      count: formatCount(counts[f.value] ?? 0),
    })),
  ];
}

/**
 * `/c/{slug}/campaigns`: every campaign, a page at a time (FLOWS §5).
 *
 * The page, the search and the status filter are the server's (`GET /v1/campaigns/page`),
 * so a client with three hundred campaigns sees a true count and a true order; the status
 * filter starts from `?status=` so a link can open "Paused". Each name is a link to the
 * campaign's own address, so Back and a shared link both work.
 *
 * A row shows only what the page read returns: the state, how many of the list were
 * reached, and when it started. Anything else (who calls, results, spend) is one tap away
 * on the campaign, because fetching it per row would cost a request per campaign.
 *
 * A row offers the one action its state allows: Pause or Resume, or the fix for a stuck
 * one. Launch is never a row action, because a launch restates what it will do and asks
 * for the count to be typed (`LaunchConfirm`), which a list row would skip.
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
  const filtered = Boolean(status || search);
  // Until the first answer arrives nobody knows whether this account has campaigns; after
  // it, an account with none gets the first-run panel and no toolbar over nothing.
  const firstRun = data !== undefined && everything === 0 && !filtered;

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

  const newButton = write.allowed ? (
    <Link href={newHref} className={PRIMARY_BUTTON}>
      <Plus aria-hidden className="h-4 w-4" />
      New campaign
    </Link>
  ) : (
    <span title={refusal} aria-disabled className={`${PRIMARY_BUTTON} cursor-not-allowed opacity-60`}>
      <Plus aria-hidden className="h-4 w-4" />
      New campaign
    </span>
  );

  return (
    <div className="max-w-5xl space-y-5 pb-12">
      <PageHeader
        description="Your agent calls a list of people for you."
        actions={firstRun ? undefined : newButton}
      />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />

      {!firstRun && (
        <div className="space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <SegmentedControl
              label="Show campaigns by status"
              options={segmentOptions(data?.status_counts, everything, status)}
              value={status ?? ALL}
              onValueChange={(next) => chooseStatus(initialStatus(next))}
              className="min-w-0"
            />
            <SearchField
              label="Search campaigns by name"
              hideLabel
              placeholder="Search by name"
              value={typed}
              onValueChange={setTyped}
              onSearch={runSearch}
              slashToFocus
              className="w-full sm:w-64 sm:shrink-0"
            />
          </div>
          {data && filtered && (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-muted">
              <span className="tabular-nums">
                {formatCount(data.total)} of {formatCount(everything)} {everything === 1 ? "campaign" : "campaigns"}
                {search ? <> matching &ldquo;{search}&rdquo;</> : null}
              </span>
              <button
                type="button"
                onClick={clearAll}
                className="rounded-sm font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                Show all
              </button>
            </p>
          )}
        </div>
      )}

      {campaigns.isLoading ? (
        <RowsSkeleton />
      ) : !data ? (
        <EmptyState
          variant="error"
          message="Your campaigns did not load."
          error={campaigns.error}
          onRetry={() => void campaigns.refetch()}
        />
      ) : firstRun ? (
        <FirstRun canWrite={write.allowed} newHref={newHref} />
      ) : data.items.length === 0 ? (
        <EmptyState variant="filtered" message="No campaign matches." onClear={clearAll} clearLabel="Show all campaigns" />
      ) : (
        <div className="space-y-4">
          {campaigns.error ? <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} /> : null}
          <ul
            aria-label="Your campaigns"
            aria-busy={campaigns.isPlaceholderData || undefined}
            className={`divide-y divide-line overflow-hidden rounded-card border border-line bg-surface transition-opacity duration-(--duration-fast) motion-reduce:transition-none ${
              campaigns.isPlaceholderData ? "opacity-60" : ""
            }`}
          >
            {data.items.map((row) => (
              <CampaignRow
                key={row.id}
                campaign={row}
                href={detail(row.id)}
                canWrite={write.allowed}
                refusal={refusal}
                at={at}
              />
            ))}
          </ul>
          {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="Campaign pages" />}
        </div>
      )}
    </div>
  );
}

/**
 * One campaign. The whole row opens it (the name's link is stretched over the row), and
 * the row's one action sits above that link so pressing it does not navigate.
 *
 * Below `sm` the row stacks: state and date, the name, the reach, then the action. From
 * `sm` the reach takes a fixed column so the bars of every row line up and can be compared
 * down the page.
 */
function CampaignRow({
  campaign,
  href,
  canWrite,
  refusal,
  at,
}: {
  campaign: CampaignSummary;
  href: string;
  canWrite: boolean;
  refusal: string | undefined;
  at: (path: string) => string;
}) {
  const note = lookup(LIST_PROVENANCE_COPY, campaign.consent_provenance_blocker ?? null);
  const started = campaign.launched_at;
  return (
    <li
      data-status={campaign.status}
      className="relative grid gap-x-6 gap-y-3 px-4 py-4 transition-colors duration-(--duration-fast) hover:bg-ink/[0.02] motion-reduce:transition-none sm:grid-cols-[minmax(0,1fr)_11.5rem_auto] sm:items-center sm:px-5"
    >
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <FlashValue value={`${campaign.status}:${campaign.pause_reason ?? ""}`}>
            <CampaignStatusPill status={campaign.status} pauseReason={campaign.pause_reason} />
          </FlashValue>
          <span className="text-meta text-ink-faint">
            {started ? `Started ${formatIST(started)}` : `Created ${formatIST(campaign.created_at)}`}
          </span>
        </div>
        <Link
          href={href}
          className="block rounded-sm text-[15px] font-semibold leading-snug text-ink [overflow-wrap:anywhere] after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {campaign.name}
        </Link>
        <p className="text-meta capitalize text-ink-muted">{campaign.classification}</p>
        {note && (
          <StatusPill tone={note.tone} wrap>
            {note.badge}
          </StatusPill>
        )}
      </div>
      <Reach campaign={campaign} />
      <RowActions campaign={campaign} canWrite={canWrite} refusal={refusal} at={at} detail={href} />
    </li>
  );
}

/**
 * How far the campaign has got: who was reached out of everyone on its list, as a figure
 * and a bar. A campaign that has not started has nothing to measure, so it says how many
 * people are on it instead of drawing an empty bar under "0 of 342".
 *
 * Hand-drawn rather than the kit's `ProgressBar`: that is a single-task bar with a heading
 * and an 8px track, and twenty-five of them read as a wall; this one is a 6px track whose
 * fill takes the row's state (brand while it calls or once it finished, amber while
 * paused, grey once stopped). A running campaign's fill carries the call log's `live-sheen`
 * band, the same "still going" mark a live call has; reduced motion drops the band and
 * the Running word says it.
 */
function Reach({ campaign }: { campaign: CampaignSummary }) {
  const { status, connected, contacts } = campaign;
  if (status === "draft" || status === "scheduled") {
    return (
      <p className="text-meta tabular-nums text-ink-muted">
        <span className="font-medium text-ink">{formatCount(contacts)}</span>{" "}
        {contacts === 1 ? "person" : "people"} to call
      </p>
    );
  }
  const fraction = contacts > 0 ? Math.min(1, connected / contacts) : 0;
  const percent = Math.round(fraction * 100);
  const fill = status === "paused" ? "bg-chart-warn" : status === "cancelled" ? "bg-chart-neutral" : "bg-brand";
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-meta tabular-nums">
        <FlashValue value={`${connected}/${contacts}`} className="text-ink-muted">
          <span className="font-medium text-ink">{formatCount(connected)}</span> of {formatCount(contacts)} reached
        </FlashValue>
        {contacts > 0 && <span className="text-ink-faint">{percent}%</span>}
      </div>
      {contacts > 0 && (
        <div
          role="progressbar"
          aria-label={`${campaign.name}: reached`}
          aria-valuemin={0}
          aria-valuemax={contacts}
          aria-valuenow={connected}
          aria-valuetext={`${formatCount(connected)} of ${formatCount(contacts)} reached`}
          className="relative h-1.5 overflow-hidden rounded-full bg-ink/[0.07]"
        >
          <div
            className={`absolute inset-0 origin-left overflow-hidden rounded-full ${fill} transition-transform duration-(--duration-slow) ease-(--ease-out-strong) motion-reduce:transition-none`}
            style={{ transform: `scaleX(${fraction})` }}
          >
            {status === "running" && (
              <span aria-hidden data-live-sheen className="live-sheen absolute inset-y-0 -left-1/2 w-1/2" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * THE FIRST VISIT: the account has never made a campaign.
 *
 * Three steps and one button. The steps are a real sequence (the new-campaign flow asks
 * for them in this order), so they are numbered; everything a person needs only once sits
 * behind "How it works". A reader who may not start campaigns is told by `RestrictionNote`
 * above and gets no button that would be refused.
 */
const FIRST_STEPS = ["Pick the agent who calls", "Add the people to call", "Check and start"];

function FirstRun({ canWrite, newHref }: { canWrite: boolean; newHref: string }) {
  return (
    <section
      aria-labelledby="campaigns-first-run"
      className="rounded-card border border-line bg-surface px-5 py-8 sm:px-10 sm:py-10"
    >
      <div className="mx-auto flex max-w-md flex-col items-center text-center">
        <div className="w-full max-w-60">
          <EmptySketch kind="campaigns" />
        </div>
        <h2 id="campaigns-first-run" className="mt-6 text-lg font-semibold tracking-tight text-ink">
          No campaigns yet
        </h2>
        <p className="mt-1 text-body text-ink-muted">Start one in three steps.</p>
        <ol className="mt-6 grid w-full gap-2 text-left sm:grid-cols-3 sm:gap-3">
          {FIRST_STEPS.map((step, index) => (
            <li
              key={step}
              className="flex items-center gap-3 rounded-lg bg-ink/[0.03] px-3 py-2.5 sm:flex-col sm:items-start sm:gap-2"
            >
              <span
                aria-hidden
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface text-xs font-semibold tabular-nums text-ink shadow-[inset_0_0_0_1px_var(--line)]"
              >
                {index + 1}
              </span>
              <span className="text-meta font-medium text-ink">{step}</span>
            </li>
          ))}
        </ol>
        {canWrite && (
          <Link href={newHref} className={`${PRIMARY_BUTTON_LG} mt-6 justify-center max-sm:w-full`}>
            <Plus aria-hidden className="h-4 w-4" />
            Start a campaign
          </Link>
        )}
        <HowItWorks
          headingLevel={3}
          className="mt-5 w-full text-left"
          items={[
            "People on your do-not-call list are skipped.",
            "You see who was reached, and can pause or stop at any time.",
          ]}
        />
      </div>
    </section>
  );
}

/** The loading rows: the shape of a campaign row, so nothing jumps when the real ones land. */
function RowsSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Loading your campaigns…</span>
      <div aria-hidden className="divide-y divide-line overflow-hidden rounded-card border border-line bg-surface">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="grid gap-x-6 gap-y-3 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_11.5rem_auto] sm:items-center sm:px-5">
            <div className="space-y-2">
              <div className="h-3 w-24 animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none" />
              <div className="h-4 w-48 max-w-full animate-pulse rounded bg-ink/[0.08] motion-reduce:animate-none" />
              <div className="h-3 w-20 animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none" />
            </div>
            <div className="space-y-2">
              <div className="h-3 w-32 animate-pulse rounded bg-ink/[0.06] motion-reduce:animate-none" />
              <div className="h-1.5 w-full animate-pulse rounded-full bg-ink/[0.07] motion-reduce:animate-none" />
            </div>
            <span />
          </div>
        ))}
      </div>
    </div>
  );
}

/** A pause whose cause must be cleared before Resume works. */
const HELD_PAUSES = ["complaint_spike", "out_of_credit", "spend_cap"];

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
 * state shows in the row's own status mark, so success needs no toast; a refusal is toasted
 * with the server's reason. A row with neither renders an empty cell so the reach column
 * keeps its place.
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
  const cell = "relative z-raised flex sm:w-28 sm:justify-end";
  // A pause whose cause must be cleared first is not resumed from the row: its fix is.
  const held = campaign.status === "paused" && HELD_PAUSES.includes(campaign.pause_reason ?? "");
  const fix = rowFix(campaign, at, detail);
  if (fix && (held || campaign.status === "draft")) {
    return (
      <div className={cell}>
        <Link href={fix.href} className={SECONDARY_BUTTON_SM} aria-label={`${fix.label}: ${campaign.name}`}>
          {fix.label}
        </Link>
      </div>
    );
  }
  if (held || (campaign.status !== "running" && campaign.status !== "paused")) {
    return <div aria-hidden className="hidden sm:block sm:w-28" />;
  }
  const action = campaign.status === "running" ? "pause" : "resume";
  return (
    <div className={cell}>
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
