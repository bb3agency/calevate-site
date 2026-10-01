"use client";

import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import { DataTable } from "@/components/console/dataTable";
import { LoadMore } from "@/components/interior/load-more";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { useClientRealm } from "@/lib/api/session";
import { useCallsLog } from "@/lib/api/hooks";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { callColumns } from "./callColumns";

/**
 * The call log — every call the agents took or placed, newest first.
 *
 * PRIMARY JOB: find a call and open it. One filter (a server-side status, so row 101 is
 * findable), one table, one way to older calls.
 *
 * The number is the client's own contact data and is printed in full (D-436); the summary
 * is transcript-derived and is shown as the API redacted it. Nothing the API did not send
 * is shown: a call with no number or summary shows that it has none.
 */

/** One page of the log — and the honesty threshold for the header count (CL1). */
const CALLS_PAGE_SIZE = 100;

/** Every status `calls.status` records that a client would ask for (ux-audit CL3). */
const STATUS_FILTERS = [
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "no_answer", label: "No answer" },
  { value: "busy", label: "Busy" },
  { value: "voicemail", label: "Voicemail" },
  { value: "failed", label: "Failed" },
] as const;

/** A status from `?status=` (the header's live pill links here) — only a known one. */
function initialStatus(param: string | null): string | undefined {
  return STATUS_FILTERS.some((f) => f.value === param) ? (param ?? undefined) : undefined;
}


export function CallsScreen({ slug }: { slug: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const params = useSearchParams();
  const [status, setStatus] = useState<string | undefined>(() =>
    initialStatus(params.get("status")),
  );
  const calls = useCallsLog(session, { status, pageSize: CALLS_PAGE_SIZE });

  // Flattened across the loaded pages, deduped by id: a call landing mid-read shifts
  // rows across an offset boundary, and a duplicate React key would crash the log.
  const seen = new Set<string>();
  const rows = (calls.data?.pages ?? [])
    .flatMap((page) => page)
    .filter((call) => (seen.has(call.id) ? false : (seen.add(call.id), true)));

  /*
   * THE CALL LOG, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * THE FILTER IS THE ONLY WRITABLE THING ON THIS SCREEN, and it is worth writing: "show
   * me the ones nobody answered" is the question this log is opened with. Its options are
   * the SAME `STATUS_FILTERS` the chips render from plus the "all" chip, so the assistant
   * cannot select a status this screen has no chip for, and `apply` ignores anything else.
   *
   * NOT ONE ROW OF THE LOG IS DECLARED. Every row carries a caller's number (hard rule 6),
   * and the number of rows loaded plus whether more remain is the whole of what a reader
   * can see that a copilot read tool cannot fetch for itself under the caller's own RLS.
   */
  useCopilotSurface({
    route: "/c/{slug}/calls",
    title: "Call log",
    realm: "client",
    fields: [
      {
        id: "calls-status",
        label: "Show only calls with this outcome",
        type: "select",
        value: status ?? "",
        options: [
          { value: "", label: "All" },
          ...STATUS_FILTERS.map((filter) => ({ value: filter.value, label: filter.label })),
        ],
        help: "Empty means every call. Filtering re-reads the log from the server.",
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: calls.data
          ? "the log below has loaded"
          : calls.error
            ? "the log failed to load, so no call is listed"
            : "still loading",
      },
      { key: "rows_loaded", label: "Call rows loaded so far", value: String(rows.length) },
      {
        key: "more_pages",
        label: "Are there older calls behind this page?",
        value: calls.hasNextPage ? "yes — the count above is this page, not the total" : "no — the count above is the total",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "calls-status") continue;
        const wanted = asText(item.value);
        if (wanted === "") setStatus(undefined);
        else if (STATUS_FILTERS.some((filter) => filter.value === wanted)) setStatus(wanted);
      }
    },
  });

  const columns = useMemo(
    () => callColumns({ callHref: (id) => href(`/c/${slug}/calls/${id}`) }),
    [href, slug],
  );
  const filterLabel = status ? STATUS_FILTERS.find((f) => f.value === status)?.label : null;

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          label="Show calls by outcome"
          value={status ?? ""}
          onValueChange={(next) => setStatus(next === "" ? undefined : next)}
          options={[{ value: "", label: "All" }, ...STATUS_FILTERS]}
          className="min-w-0"
        />
        {/* The denominator, only once the query has answered — a count rendered while
            loading says 0 and then jumps. With more pages behind it the loaded length is
            a statement about our query, not their business, so it is not called a total
            (ux-audit CL1). */}
        {calls.data &&
          (calls.hasNextPage ? (
            <p className="text-[13px] text-ink-muted">
              Showing the{" "}
              <span className="font-semibold tabular-nums text-ink">{formatCount(rows.length)}</span>{" "}
              most recent{filterLabel ? ` · ${filterLabel.toLowerCase()}` : ""}
            </p>
          ) : (
            <p className="text-[13px] text-ink-muted">
              <span className="font-semibold tabular-nums text-ink">{formatCount(rows.length)}</span>{" "}
              {filterLabel ? `${filterLabel.toLowerCase()}` : rows.length === 1 ? "call" : "calls"}
            </p>
          ))}
      </div>

      {calls.error && <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />}

      <Card bodyClassName="p-1 sm:p-2">
        {calls.isLoading ? (
          <div className="p-4">
            <Skeleton rows={6} />
          </div>
        ) : /* A PAUSED query (offline) is neither loading nor failed and has no data;
               `!calls.data` keeps it from printing "No calls yet" (§52). With an error the
               notice above is the whole answer. */
        calls.error ? null : !calls.data ? (
          <div className="p-4">
            <ProblemNotice
              error={new Error("Your calls did not load.")}
              onRetry={() => void calls.refetch()}
            />
          </div>
        ) : rows.length ? (
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(call) => call.id}
            label="Calls, newest first"
            partialNote={
              calls.hasNextPage
                ? `Sorted within the ${formatCount(rows.length)} calls loaded; older calls are not included.`
                : undefined
            }
          />
        ) : (
          <EmptyState
            title={status ? "No calls match this filter" : "No calls yet"}
            hint={
              status
                ? "Choose All to see everything."
                : "A call appears here within a couple of minutes of the caller hanging up."
            }
          />
        )}
        {/* The way to yesterday (ux-audit CL2). Manual: a log the reader is scanning
            grows when asked, not while their scroll passes a sentinel. */}
        {calls.hasNextPage && rows.length > 0 && (
          <LoadMore
            auto={false}
            hasMore={calls.hasNextPage}
            labels={{ idle: "Show older calls" }}
            onLoad={async () => {
              const result = await calls.fetchNextPage();
              if (result.isError) throw result.error;
              return result.hasNextPage;
            }}
            className="py-1"
          />
        )}
      </Card>
    </div>
  );
}
