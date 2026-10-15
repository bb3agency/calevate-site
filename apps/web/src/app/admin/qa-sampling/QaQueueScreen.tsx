"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SearchSelect } from "@/components/console/searchSelect";
import { TEXT_ACTION } from "@/components/console/section";
import { Pagination } from "@/components/interior/pagination";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ADMIN_PAGE_WIDE } from "@/components/admin/kit";
import {
  FIELD,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  formatDuration,
  formatIST,
} from "@/components/ui";
import {
  DEFAULT_FILTERS,
  QUEUE_MAX_OFFSET,
  QUEUE_PAGE_SIZE,
  VERDICTS,
  filtersFromSearch,
  filtersToSearch,
  useNextWaiting,
  useQaQueue,
  type QaQueueClient,
  type QaQueuePage,
  type QaSample,
  type QaVerdict,
  type QueueFilters,
  type QueueStatus,
} from "@/lib/api/qaSamples";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { calls, directionLabel, reviewHref, weekLabel } from "./queueWords";

const QUEUE_ROUTE = "/admin/qa-sampling";

/**
 * The QA sampling queue (SURFACES §1): about 5% of each client's calls per week, drawn by
 * `apps/api/quality/sampling.py` on the weekly tick in `apps/workers/qa_sampling.py`.
 *
 * A work queue built for a hundred clients and several hundred calls a week:
 *
 * 1. The headline is the work — how many calls are waiting — and one button starts on
 *    the first of them, under the filters on screen.
 * 2. Every filter is in the URL, so a filtered view can be shared and survives a refresh,
 *    and the review screen inherits it for its own "Next call to review".
 * 3. Rows are grouped by draw week and then by client, in the order the API merges them
 *    (week, client name, draw rank), so one client's calls read as one block under its
 *    name. Paging is the server's; nothing here filters a partial page.
 * 4. Empty is the good state and says what happens next. A failed or paused read is a
 *    third branch: "nobody is waiting" is a claim about the world, and a dead token is not
 *    evidence.
 *
 * The list carries ids, timings and tags only (hard rule 6): no phone number and no
 * transcript text. The conversation is on the review screen.
 */
export function QaQueueScreen() {
  const [filters, update] = useQueueFilters();
  const queue = useQaQueue(filters);
  const data = queue.data;
  const search = filtersToSearch({ ...filters, page: 1 });

  /*
   * The draw spans every client, so counts leave and names do not — no client, agent or
   * call id. The status filter is writable: a three-value toggle over a list the person
   * is already looking at.
   */
  useCopilotSurface({
    route: QUEUE_ROUTE,
    title: "Call quality checks",
    realm: "admin",
    fields: [
      {
        id: "qa-filter-status",
        label: "Which calls are listed",
        type: "select",
        value: filters.status,
        options: STATUS_OPTIONS.map(({ value, label }) => ({ value, label })),
      },
    ],
    facts: data
      ? [
          { key: "waiting", label: "Calls waiting for review, every client", value: String(data.waiting_total) },
          { key: "listed", label: "Calls matching the filters", value: String(data.total) },
          { key: "clients", label: "Clients with sampled calls", value: String(data.clients.length) },
        ]
      : [
          {
            key: "queue",
            label: "The sampling queue",
            value: queue.error ? "could not be read" : "still loading",
          },
        ],
    apply: (items) => {
      const status = items.find((item) => item.field_id === "qa-filter-status");
      if (status !== undefined) {
        const value = asText(status.value) as QueueStatus;
        if (STATUS_OPTIONS.some((option) => option.value === value)) update({ status: value });
      }
    },
  });

  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description={
          <>
            About 5% of each client&apos;s finished calls, picked every Monday for a person to
            check.{" "}
            <InfoTip label="How calls are picked">
              <p>
                Each Monday at 07:20 IST we pick about 5% of every client&apos;s finished calls
                from the week that just ended, at least one per client with calls.
              </p>
              <p>
                The pick can be re-run and checked: every call gets a fixed place from a seed
                shown on its review, so the same week always gives the same calls. A call is
                never picked twice.
              </p>
            </InfoTip>
          </>
        }
      />

      <WorkBand data={data} filters={filters} search={search} />

      <Filters data={data} filters={filters} update={update} />

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      <div>
        {queue.isLoading ? (
          <Skeleton rows={6} label="Loading the sampling queue" />
        ) : /* `!data` as well as `error`: an offline browser PAUSES the query, which reports
               neither loading nor error with no data — and "every call reviewed" off a
               request nobody made is the sentence this branch exists to refuse. */
        queue.error || !data ? (
          <NoticeBox tone="warn" title="The sampling queue could not be read">
            <p className="mt-1">
              So we cannot say whether anything is waiting for review. This is not an empty
              queue.
            </p>
          </NoticeBox>
        ) : data.total === 0 ? (
          <Empty filters={filters} data={data} onClear={() => update(DEFAULT_FILTERS)} />
        ) : (
          <Results data={data} filters={filters} search={search} update={update} />
        )}
      </div>
    </div>
  );
}

const STATUS_OPTIONS: { value: QueueStatus; label: string }[] = [
  { value: "waiting", label: "Waiting" },
  { value: "reviewed", label: "Reviewed" },
  { value: "all", label: "All" },
];

/**
 * The filters, held in the URL. State first and the URL second, so a change is drawn at
 * once and the address follows; a Back or a pasted link re-reads the URL.
 */
function useQueueFilters(): [QueueFilters, (change: Partial<QueueFilters>) => void] {
  const router = useRouter();
  const params = useSearchParams();
  const fromUrl = params.toString();
  const [filters, setFilters] = useState(() => filtersFromSearch(new URLSearchParams(fromUrl)));
  useEffect(() => {
    setFilters(filtersFromSearch(new URLSearchParams(fromUrl)));
  }, [fromUrl]);
  const update = (change: Partial<QueueFilters>) => {
    // Any change but the page itself starts again at page 1.
    const next = { ...filters, ...change, page: change.page ?? 1 };
    // A verdict only narrows reviewed calls; picking one while "Waiting" shows reviewed.
    if (change.verdict && next.status === "waiting") next.status = "reviewed";
    if (change.status === "waiting") next.verdict = null;
    setFilters(next);
    const query = filtersToSearch(next);
    router.replace(query ? `${QUEUE_ROUTE}?${query}` : QUEUE_ROUTE, { scroll: false });
  };
  return [filters, update];
}

/** The headline and the one action the screen exists for. */
function WorkBand({
  data,
  filters,
  search,
}: {
  data: QaQueuePage | undefined;
  filters: QueueFilters;
  search: string;
}) {
  // The first waiting call under this client and week. On the default view that is the
  // first row of the page already on screen; any other view asks for it.
  const onDefaultView =
    filters.status === "waiting" && filters.order === "oldest" && filters.page === 1;
  const asked = useNextWaiting(filters, { enabled: !onDefaultView });
  const first = onDefaultView ? (data ? (data.items[0] ?? null) : undefined) : asked.next;
  const client = data?.clients.find((row) => row.tenant_id === filters.client);
  const waitingHere = client ? client.waiting : data?.waiting_total;

  return (
    <section
      aria-label="Calls to review"
      className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="min-w-0">
        <p className="text-lg font-semibold text-ink">
          {waitingHere === undefined
            ? "Checking the queue…"
            : waitingHere === 0
              ? "Nothing waiting for review"
              : `${calls(waitingHere)} waiting for review`}
        </p>
        <p className="mt-0.5 text-meta text-ink-muted">
          {client
            ? `${client.tenant_name}: ${client.waiting} of ${client.sampled} picked calls still to review.`
            : data
              ? `Across ${data.clients.length} ${data.clients.length === 1 ? "client" : "clients"}. Oldest week first.`
              : " "}
        </p>
      </div>
      {first ? (
        <Link
          href={reviewHref(first, search)}
          className={`${PRIMARY_BUTTON} justify-center sm:shrink-0`}
        >
          Start reviewing
          <ChevronRight aria-hidden className="h-4 w-4" />
        </Link>
      ) : null}
    </section>
  );
}

function Filters({
  data,
  filters,
  update,
}: {
  data: QaQueuePage | undefined;
  filters: QueueFilters;
  update: (change: Partial<QueueFilters>) => void;
}) {
  const clientOptions = useMemo(
    () =>
      (data?.clients ?? []).map((client: QaQueueClient) => ({
        value: client.tenant_id,
        label: client.tenant_name,
        hint:
          client.waiting === 0
            ? "all reviewed"
            : `${client.waiting} of ${client.sampled} to review`,
      })),
    [data?.clients],
  );
  // A week the URL names but the recent list does not still shows as chosen.
  const weeks = data?.weeks ?? [];
  const weekOptions = filters.week && !weeks.includes(filters.week) ? [filters.week, ...weeks] : weeks;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-[minmax(0,1.4fr)_auto_minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
      <SearchSelect
        className="col-span-2 lg:col-span-1"
        label="Client"
        allLabel="All clients"
        placeholder="Type a client's name"
        options={clientOptions}
        value={filters.client}
        onChange={(client) => update({ client })}
      />
      <div className="col-span-2 lg:col-span-1">
        <span className={FIELD_LABEL}>
          Show
        </span>
        <div className="mt-1">
          <SegmentedControl
            label="Show"
            value={filters.status}
            onValueChange={(value) => update({ status: value as QueueStatus })}
            options={STATUS_OPTIONS}
          />
        </div>
      </div>
      <label className="block">
        <span className={FIELD_LABEL}>Verdict</span>
        <select
          className={FIELD}
          value={filters.verdict ?? ""}
          disabled={filters.status === "waiting"}
          onChange={(event) =>
            update({ verdict: (event.target.value || null) as QaVerdict | null })
          }
        >
          <option value="">{filters.status === "waiting" ? "Not reviewed yet" : "Any verdict"}</option>
          {(Object.keys(VERDICTS) as QaVerdict[]).map((verdict) => (
            <option key={verdict} value={verdict}>
              {VERDICTS[verdict].label}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={FIELD_LABEL}>Week picked</span>
        <select
          className={FIELD}
          value={filters.week ?? ""}
          onChange={(event) => update({ week: event.target.value || null })}
        >
          <option value="">All weeks</option>
          {weekOptions.map((week) => (
            <option key={week} value={week}>
              Week of {weekLabel(week)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function Empty({
  filters,
  data,
  onClear,
}: {
  filters: QueueFilters;
  data: QaQueuePage;
  onClear: () => void;
}) {
  const filtered =
    filters.client !== null || filters.week !== null || filters.verdict !== null || filters.status !== "waiting";
  if (filtered) {
    return (
      <EmptyState
        message="No calls match these filters"
        hint={data.waiting_total > 0 ? `${calls(data.waiting_total)} are waiting across every client.` : undefined}
        action={
          <button type="button" onClick={onClear} className={TEXT_ACTION}>
            Clear the filters
          </button>
        }
      />
    );
  }
  return (
    <EmptyState
      message="Every picked call has been reviewed"
      hint="On Monday at 07:20 IST the next calls are picked: about 5% of each client's finished calls from the week that just ended. They will be listed here."
    />
  );
}

/** One block per week, one sub-block per client inside it, in the API's merge order. */
interface ClientRun {
  key: string;
  tenantId: string;
  client: QaQueueClient | undefined;
  name: string;
  rows: QaSample[];
}
interface WeekRun {
  week: string;
  clients: ClientRun[];
}

function group(rows: QaSample[], clients: QaQueueClient[]): WeekRun[] {
  const byId = new Map(clients.map((client) => [client.tenant_id, client]));
  const weeks: WeekRun[] = [];
  for (const row of rows) {
    let week = weeks.at(-1);
    if (week?.week !== row.week_start) {
      week = { week: row.week_start, clients: [] };
      weeks.push(week);
    }
    let run = week.clients.at(-1);
    if (run?.tenantId !== row.tenant_id) {
      run = {
        key: `${row.week_start}:${row.tenant_id}`,
        tenantId: row.tenant_id,
        client: byId.get(row.tenant_id),
        name: row.tenant_name,
        rows: [],
      };
      week.clients.push(run);
    }
    run.rows.push(row);
  }
  return weeks;
}

function Results({
  data,
  filters,
  search,
  update,
}: {
  data: QaQueuePage;
  filters: QueueFilters;
  search: string;
  update: (change: Partial<QueueFilters>) => void;
}) {
  const weeks = group(data.items, data.clients);
  const from = data.offset + 1;
  const to = data.offset + data.items.length;
  // The API answers offsets up to QUEUE_MAX_OFFSET; past that the filters narrow it.
  const reachable = Math.min(data.total, QUEUE_MAX_OFFSET + QUEUE_PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(reachable / QUEUE_PAGE_SIZE));

  return (
    <div className="space-y-8">
      <p className="text-meta text-ink-muted" aria-live="polite">
        Showing {from}–{to} of {calls(data.total)}
      </p>
      {weeks.map((week) => (
        <section key={week.week} aria-labelledby={`qa-week-${week.week}`} className="space-y-3">
          <h3 id={`qa-week-${week.week}`} className="text-body font-semibold text-ink">
            Week of {weekLabel(week.week)}
          </h3>
          <div className="divide-y divide-line overflow-hidden rounded-card border border-line bg-surface">
            {week.clients.map((run) => (
              <ClientBlock key={run.key} run={run} search={search} />
            ))}
          </div>
        </section>
      ))}
      {pages > 1 && (
        <div className="flex flex-col items-start gap-2">
          <Pagination
            count={pages}
            page={Math.min(filters.page, pages)}
            onPageChange={(page) => update({ page })}
            label="Queue pages"
          />
          {data.total > reachable && (
            <p className="text-meta text-ink-muted">
              The first {reachable} are listed. Pick a client or a week to see the rest.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ClientBlock({ run, search }: { run: ClientRun; search: string }) {
  const counts = run.client;
  return (
    // One client's calls for one week: a quiet header row, then the calls, inside the
    // week's single list. A card per client would stack a hundred boxes on a busy Monday.
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-line bg-ink/[0.025] px-4 py-2">
        <h4 className="min-w-0 truncate text-body font-semibold text-ink" title={`/c/${run.rows[0]?.tenant_slug ?? ""}`}>
          {run.name}
        </h4>
        {counts && (
          <span className="text-meta text-ink-muted">
            {counts.waiting === 0
              ? "All reviewed"
              : `${counts.waiting} of ${counts.sampled} to review, all weeks`}
          </span>
        )}
      </div>
      <ul className="divide-y divide-line">
        {run.rows.map((row) => (
          <SampleRow key={row.id} row={row} search={search} />
        ))}
      </ul>
    </div>
  );
}

/** One call: the whole row is the link into its review (UX-DOCTRINE §4, one target). */
function SampleRow({ row, search }: { row: QaSample; search: string }) {
  const verdict = row.verdict ? VERDICTS[row.verdict] : null;
  return (
    <li>
      <Link
        href={reviewHref(row, search)}
        aria-label={`${row.tenant_name}, ${row.agent_name}, ${formatIST(row.started_at)}: ${
          verdict ? `reviewed as ${verdict.label}` : "review this call"
        }`}
        className="group flex items-center gap-3 px-4 py-3 transition-colors duration-(--duration-fast) hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-body font-medium text-ink">{row.agent_name}</span>
          <span className="mt-0.5 block text-meta text-ink-muted">
            {formatIST(row.started_at)} · {directionLabel(row.direction)} ·{" "}
            {formatDuration(row.duration_s)}
            <span className="hidden sm:inline">
              {" "}
              · Pick #{row.selection_rank} of {row.target} from {calls(row.population)}
            </span>
          </span>
        </span>
        {verdict ? (
          <span className="shrink-0 text-right">
            <span className="block text-meta font-medium text-ink">{verdict.label}</span>
            <span className="block text-xs text-ink-muted">{formatIST(row.reviewed_at)}</span>
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 text-meta font-medium text-brand-strong">
            Review
            <ChevronRight aria-hidden className="h-4 w-4 transition-transform duration-(--duration-fast) group-hover:translate-x-0.5" />
          </span>
        )}
      </Link>
    </li>
  );
}
