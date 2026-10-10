"use client";

/**
 * THE CALL LOG: every call, newest first, filtered on the server (REDESIGN-2).
 *
 * Filters, as the founder set them: how the call ENDED (outcome chips), WHEN (today, 7
 * days, 30 days, or two dates, all on India-time days, `lib/callFilters`), and WHICH WAY
 * (incoming or outgoing). There is no agent filter. A STATUS filter (no answer, failed …)
 * still arrives by link, from the dashboard's "did not connect" row, and shows as a chip
 * that clears it. Every filter is a server query, never a slice of the loaded page, so a
 * filtered count is a fact about the business, not about our paging.
 *
 * "Export CSV" downloads the same filtered log (owner-only on the server, audited), so
 * the file is the table.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { DataTable } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { TEXT_ACTION } from "@/components/console/section";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { LoadMore } from "@/components/interior/load-more";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { FIELD, FilterChip, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount, istDateStamp } from "@/components/ui";
import { useCallsLog, useExportCalls, useWriteAccess, type CallsLogFilters } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import {
  DIRECTIONS,
  OUTCOMES,
  RANGES,
  callWindow,
  type CallDirection,
  type CallOutcome,
  type CallRange,
} from "@/lib/callFilters";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { callColumns } from "./callColumns";

/**
 * One page of the log. A paged read rather than the whole history: the log grows without
 * bound, and the reader asks for older calls with "Show older calls".
 */
const CALLS_PAGE_SIZE = 100;

/** Statuses a link may ask for; only shown as a chip that clears them. */
const STATUS_WORDS: Record<string, string> = {
  in_progress: "in progress",
  completed: "completed",
  no_answer: "unanswered",
  busy: "busy",
  voicemail: "voicemail",
  failed: "failed",
};

function initialStatus(param: string | null): string | undefined {
  return param && Object.hasOwn(STATUS_WORDS, param) ? param : undefined;
}

export function CallsScreen({ slug }: { slug: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const params = useSearchParams();
  const [status, setStatus] = useState<string | undefined>(() => initialStatus(params.get("status")));
  const [outcome, setOutcome] = useState<CallOutcome | undefined>();
  const [direction, setDirection] = useState<CallDirection | undefined>();
  const [range, setRange] = useState<CallRange>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const filters: CallsLogFilters = {
    status,
    outcome,
    direction,
    ...callWindow(range, istDateStamp(), from, to),
  };
  const calls = useCallsLog(session, { ...filters, pageSize: CALLS_PAGE_SIZE });
  const exportCalls = useExportCalls(session);
  const exportAccess = useWriteAccess(session, "calls:read_raw", "export your calls");
  const filtered = Boolean(status || outcome || direction || range !== "all");

  // Flattened across the loaded pages, deduped by id: a call landing mid-read shifts
  // rows across an offset boundary, and a duplicate React key would crash the log.
  const seen = new Set<string>();
  const rows = (calls.data?.pages ?? [])
    .flatMap((page) => page)
    .filter((call) => (seen.has(call.id) ? false : (seen.add(call.id), true)));

  /*
   * THE CALL LOG, DECLARED TO THE ASSISTANT. The filters are the writable things on this
   * screen ("show me yesterday's missed calls"); each field's options are the same lists
   * the controls render, and `apply` ignores anything else. NOT ONE ROW IS DECLARED: every
   * row carries a caller's number (hard rule 6).
   */
  useCopilotSurface({
    route: "/c/{slug}/calls",
    title: "Call log",
    realm: "client",
    fields: [
      {
        id: "calls-outcome",
        label: "How the call ended",
        type: "select",
        value: outcome ?? "",
        options: [{ value: "", label: "Any" }, ...OUTCOMES.map((o) => ({ value: o.value, label: o.label }))],
      },
      {
        id: "calls-range",
        label: "When",
        type: "select",
        value: range,
        options: RANGES.map((r) => ({ value: r.value, label: r.label })),
        help: "India time. Custom uses the two dates below.",
      },
      { id: "calls-from", label: "From (custom range)", type: "date", value: from },
      { id: "calls-to", label: "To (custom range)", type: "date", value: to },
      {
        id: "calls-direction",
        label: "Which way",
        type: "select",
        value: direction ?? "",
        options: [{ value: "", label: "Both" }, ...DIRECTIONS.map((d) => ({ value: d.value, label: d.label }))],
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
      { key: "status_link", label: "Status chosen by a link", value: status ? (lookup(STATUS_WORDS, status) ?? status) : "none" },
      { key: "rows_loaded", label: "Call rows loaded so far", value: String(rows.length) },
      {
        key: "more_pages",
        label: "Are there older calls behind this page?",
        value: calls.hasNextPage ? "yes — the count above is this page, not the total" : "no — the count above is the total",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const wanted = asText(item.value);
        if (item.field_id === "calls-outcome") {
          setOutcome(OUTCOMES.find((o) => o.value === wanted)?.value);
        } else if (item.field_id === "calls-direction") {
          setDirection(DIRECTIONS.find((d) => d.value === wanted)?.value);
        } else if (item.field_id === "calls-range") {
          const next = RANGES.find((r) => r.value === wanted);
          if (next) setRange(next.value);
        } else if (item.field_id === "calls-from") {
          setFrom(wanted);
          setRange("custom");
        } else if (item.field_id === "calls-to") {
          setTo(wanted);
          setRange("custom");
        }
      }
    },
  });

  const columns = useMemo(
    () => callColumns({ callHref: (id) => href(`/c/${slug}/calls/${id}`) }),
    [href, slug],
  );
  const clearAll = () => {
    setStatus(undefined);
    setOutcome(undefined);
    setDirection(undefined);
    setRange("all");
  };

  return (
    <div className="space-y-5 pb-12">
      <div className="space-y-3">
        <SegmentedControl
          label="Show calls by how they ended"
          value={outcome ?? ""}
          onValueChange={(next) => setOutcome(OUTCOMES.find((o) => o.value === next)?.value)}
          options={[{ value: "", label: "All" }, ...OUTCOMES]}
          className="min-w-0"
        />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <SegmentedControl
            label="When"
            value={range}
            onValueChange={(next) => setRange(RANGES.find((r) => r.value === next)?.value ?? "all")}
            options={[...RANGES]}
            className="min-w-0"
          />
          <SegmentedControl
            label="Which way"
            value={direction ?? ""}
            onValueChange={(next) => setDirection(DIRECTIONS.find((d) => d.value === next)?.value)}
            options={[{ value: "", label: "Both" }, ...DIRECTIONS]}
            className="min-w-0"
          />
        </div>
        {range === "custom" && (
          <div className="settings-enter flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="block text-meta text-ink-muted">From</span>
              <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} className={`${FIELD} w-auto`} />
            </label>
            <label className="block">
              <span className="block text-meta text-ink-muted">To</span>
              <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} className={`${FIELD} w-auto`} />
            </label>
            <span className="pb-2 text-meta text-ink-muted">India time, both days included.</span>
          </div>
        )}
        {status && (
          <div className="flex flex-wrap items-center gap-2">
            <FilterChip label={`Only ${lookup(STATUS_WORDS, status) ?? status} calls`} active onClick={() => setStatus(undefined)} />
            <span className="text-meta text-ink-muted">Press it to show every call.</span>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* The denominator, only once the query has answered — a count rendered while
              loading says 0 and then jumps. With more pages behind it the loaded length is
              a statement about our query, not their business, so it is not called a total. */}
          {calls.data ? (
            <p className="text-meta text-ink-muted">
              {calls.hasNextPage ? "Showing the " : ""}
              <span className="font-semibold tabular-nums text-ink">{formatCount(rows.length)}</span>{" "}
              {calls.hasNextPage ? "most recent" : rows.length === 1 ? "call" : "calls"}
              {filtered ? " matching these filters" : ""}
            </p>
          ) : (
            <span />
          )}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            {exportAccess.allowed && (
              <button
                type="button"
                className={TEXT_ACTION}
                disabled={exportCalls.isPending}
                onClick={() => exportCalls.mutate(filters)}
              >
                {exportCalls.isPending ? "Preparing…" : "Export CSV"}
              </button>
            )}
            <AskAssistant prompt="Summarise my latest calls: what callers wanted, and what I should follow up." />
          </div>
        </div>
        {exportCalls.error ? <ProblemNotice error={exportCalls.error} /> : null}
      </div>

      {calls.error && <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />}

      <div className="border-y border-line">
        {calls.isLoading ? (
          <div className="p-4">
            <Skeleton rows={6} />
          </div>
        ) : /* A PAUSED query (offline) is neither loading nor failed and has no data;
               `!calls.data` keeps it from printing "No calls yet" (§52). With an error the
               notice above is the whole answer. */
        calls.error ? null : !calls.data ? (
          <div className="p-4">
            <ProblemNotice error={new Error("Your calls did not load.")} onRetry={() => void calls.refetch()} />
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
            illustration={filtered ? undefined : <EmptySketch kind="calls" />}
            message={filtered ? "No calls match this filter" : "No calls yet."}
            hint={filtered ? undefined : "A call shows here a couple of minutes after the caller hangs up."}
            action={
              filtered ? (
                <button type="button" className={SECONDARY_BUTTON_SM} onClick={clearAll}>
                  Show all calls
                </button>
              ) : (
                <Link href={href(`/c/${slug}/agents`)} className={SECONDARY_BUTTON_SM}>
                  Make a test call
                </Link>
              )
            }
          />
        )}
        {/* The way to yesterday. Manual: a log the reader is scanning grows when asked,
            not while their scroll passes a sentinel. */}
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
      </div>
    </div>
  );
}
