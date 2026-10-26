"use client";

/**
 * THE CALL LOG: every call, newest first, filtered on the server (REDESIGN-2).
 *
 * PRIMARY JOB: find the calls that need you and open one.
 *
 * ONE filter row (`FilterToolbar`, folded behind "Filters" on a phone): how the call ENDED
 * (outcome chips, "Needs you" first), WHEN as a span of India-time days (`DateRangePicker`,
 * `lib/callFilters`), WHICH WAY, and whether free-trial test calls are included. One agent's calls arrive by link from that agent's page
 * (`?agent_id=`) and show as a chip that clears them. A STATUS filter (no answer, failed …)
 * still arrives by link, from the dashboard's "did not connect" row, and shows as a chip
 * that clears it. Every filter is a server query, never a slice of the loaded page, so a
 * filtered count is a fact about the business, not about our paging.
 *
 * "Export CSV" downloads the same filtered log (owner-only on the server, audited), so
 * the file is the table.
 *
 * Each call carries the follow-up actions (`components/calls/followUpActions`): a swipe on
 * a phone, where the log is a list rather than a table, and the row's ⋯ menu elsewhere.
 */

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DateRangePicker, type DateRange } from "@/components/arc/calendar";
import { ChipGroup } from "@/components/arc/chip-group";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar, type ActiveFilter } from "@/components/arc/filter-toolbar";
import { formatDateRange } from "@/components/arc/ist-dates";
import { RowMenu } from "@/components/arc/menu";
import { useFollowUpActions, type Dialer, type FollowUpTarget } from "@/components/calls/followUpActions";
import { DataTable } from "@/components/console/dataTable";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { LoadMore } from "@/components/interior/load-more";
import { FIELD, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount, istDateStamp } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import { queryKeys, useCallsLog, useExportCalls, useWriteAccess, type CallsLogFilters } from "@/lib/api/hooks";
import { useLiveCalls, type CallLive } from "@/lib/api/liveCalls";
import { useClientRealm } from "@/lib/api/session";
import {
  DIRECTIONS,
  OUTCOMES,
  RANGES,
  callWindow,
  shiftDay,
  type CallDirection,
  type CallOutcome,
} from "@/lib/callFilters";
import { callTitle } from "@/lib/callReview";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { callColumns, liveOf } from "./callColumns";
import { CallsPhoneList } from "./CallsPhoneList";
import { endedReads, liveIds, withLive } from "./liveRows";

/** Below `sm` the log is a swipeable list, not a table (different markup, so a query). */
const PHONE = "(max-width: 639px)";

/** The assistant's "When" words, as the span of days they mean. */
function rangeDays(value: string, today: string): DateRange | null {
  if (value === "today") return { start: today, end: today };
  if (value === "7d") return { start: shiftDay(today, -6), end: today };
  if (value === "30d") return { start: shiftDay(today, -29), end: today };
  return null;
}

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
  const [agentId, setAgentId] = useState<string | undefined>(() => params.get("agent_id") || undefined);
  const [campaignId, setCampaignId] = useState<string | undefined>(() => params.get("campaign_id") || undefined);
  const [outcome, setOutcome] = useState<CallOutcome | undefined>();
  const [direction, setDirection] = useState<CallDirection | undefined>();
  const [dates, setDates] = useState<DateRange | null>(null);
  // On by default: a trial account has only test calls, and a log that hid every one of
  // them would read as "nobody has called". Each one carries a "Test call" tag.
  const [testCalls, setTestCalls] = useState(true);

  const today = istDateStamp();
  const filters: CallsLogFilters = {
    status,
    agentId,
    campaignId,
    outcome,
    direction,
    testCalls,
    ...(dates ? callWindow("custom", today, dates.start, dates.end) : {}),
  };
  const calls = useCallsLog(session, { ...filters, pageSize: CALLS_PAGE_SIZE });
  const exportCalls = useExportCalls(session);
  // The file arriving is its own success; the button's tick says it started.
  const exporting = useActionFeedback(exportCalls, { errorTitle: "Could not export your calls" });
  const exportAccess = useWriteAccess(session, "calls:read_raw", "export your calls");
  const filtered = Boolean(status || agentId || campaignId || outcome || direction || dates || !testCalls);
  const phone = useMediaQuery(PHONE);

  /* Who rings a caller back: the agent that took the call when it places calls, else the
     account's first agent that does (`canDialOut`, the one definition). */
  const agents = useAgents(session);
  const dialers = agents.data ? agents.data.filter(canDialOut) : undefined;
  const followUp = useFollowUpActions(session, {
    dialerFor: (target) => {
      const chosen = dialers?.find((agent) => agent.id === target.agentId) ?? dialers?.[0];
      return chosen ? ({ id: chosen.id, name: chosen.name } satisfies Dialer) : null;
    },
    // "None of your agents places calls" only once the list has arrived and says so.
    noDialerReason:
      agents.error != null
        ? "We could not read your agents just now, so no call can be placed. Reload the page to try again."
        : !agents.data
          ? "Checking which of your agents can place the call…"
          : undefined,
  });
  const targetOf = (call: CallSummary): FollowUpTarget => ({
    key: call.id,
    name: callTitle(call),
    phone: call.caller_e164,
    leadId: call.lead_id ?? null,
    callId: call.id,
    followUpState: call.follow_up_state as FollowUpTarget["followUpState"],
    agentId: call.agent_id,
  });

  // Flattened across the loaded pages, deduped by id: a call landing mid-read shifts
  // rows across an offset boundary, and a duplicate React key would crash the log.
  const seen = new Set<string>();
  const loaded = (calls.data?.pages ?? [])
    .flatMap((page) => page)
    .filter((call) => (seen.has(call.id) ? false : (seen.add(call.id), true)));

  /* LIVE ROWS (D-886). The rows the server calls live are asked about every few seconds;
     a call the read says has ended is kept as ended, no longer asked about, and the log is
     re-read once so the row turns into the finished call in place. */
  const [ended, setEnded] = useState<Readonly<Record<string, CallLive>>>({});
  const live = useLiveCalls(
    session,
    liveIds(loaded).filter((id) => !Object.hasOwn(ended, id)),
  );
  const queryClient = useQueryClient();
  useEffect(() => {
    const fresh = endedReads(live.data).filter((read) => !Object.hasOwn(ended, read.id));
    if (!fresh.length) return;
    setEnded((before) => ({ ...before, ...Object.fromEntries(fresh.map((read) => [read.id, read])) }));
    void queryClient.invalidateQueries({ queryKey: queryKeys.callsLog(session.orgSlug) });
  }, [live.data, ended, queryClient, session.orgSlug]);
  // A failed live read leaves each live row on its own status; the sentence under the count
  // says why "Dialling…" may not move.
  const rows = withLive(loaded, [...(live.isSuccess ? live.data : []), ...Object.values(ended)]);
  /** Every row under the agent filter is that agent's, so the name comes with them. */
  const agentName = agentId ? (rows.find((call) => call.agent_id === agentId)?.agent_name ?? undefined) : undefined;

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
    saves: "view",
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
        value: dates ? "custom" : "all",
        options: RANGES.map((r) => ({ value: r.value, label: r.label })),
        help: "India time. Custom uses the two dates below.",
      },
      { id: "calls-from", label: "From (custom range)", type: "date", value: dates?.start ?? "" },
      { id: "calls-to", label: "To (custom range)", type: "date", value: dates?.end ?? "" },
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
      { key: "agent_link", label: "Agent chosen by a link", value: agentId ? (agentName ?? agentId) : "none" },
      { key: "campaign_link", label: "Only one campaign's calls?", value: campaignId ? "yes, chosen by a link from that campaign" : "no" },
      { key: "test_calls", label: "Are free-trial test calls included?", value: testCalls ? "yes" : "no" },
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
          if (wanted === "all") setDates(null);
          else if (wanted !== "custom") setDates(rangeDays(wanted, today));
        } else if (item.field_id === "calls-from" && /^\d{4}-\d{2}-\d{2}$/.test(wanted)) {
          setDates((prev) => ({ start: wanted, end: prev && prev.end >= wanted ? prev.end : wanted }));
        } else if (item.field_id === "calls-to" && /^\d{4}-\d{2}-\d{2}$/.test(wanted)) {
          setDates((prev) => ({ start: prev && prev.start <= wanted ? prev.start : wanted, end: wanted }));
        }
      }
    },
  });

  // Rebuilt each render: the menu items read the live state of each follow-up action.
  const columns = callColumns({
    callHref: (id) => href(`/c/${slug}/calls/${id}`),
    menu: (call) => <RowMenu label={callTitle(call)} items={followUp.menuItems(targetOf(call))} />,
  });
  const clearAll = () => {
    setStatus(undefined);
    setAgentId(undefined);
    setCampaignId(undefined);
    setOutcome(undefined);
    setDirection(undefined);
    setDates(null);
    setTestCalls(true);
  };

  const active: ActiveFilter[] = [
    ...(outcome ? [{ id: "outcome", label: OUTCOMES.find((o) => o.value === outcome)?.label ?? outcome, onRemove: () => setOutcome(undefined) }] : []),
    ...(dates ? [{ id: "dates", label: formatDateRange(dates.start, dates.end), onRemove: () => setDates(null) }] : []),
    ...(direction ? [{ id: "direction", label: DIRECTIONS.find((d) => d.value === direction)?.label ?? direction, onRemove: () => setDirection(undefined) }] : []),
    ...(!testCalls ? [{ id: "tests", label: "Test calls left out", onRemove: () => setTestCalls(true) }] : []),
    ...(agentId ? [{ id: "agent", label: `Agent: ${agentName ?? "the chosen agent"}`, onRemove: () => setAgentId(undefined) }] : []),
    ...(campaignId ? [{ id: "campaign", label: "One campaign's calls", onRemove: () => setCampaignId(undefined) }] : []),
    ...(status ? [{ id: "status", label: `Only ${lookup(STATUS_WORDS, status) ?? status} calls`, onRemove: () => setStatus(undefined) }] : []),
  ];

  return (
    <div className="space-y-5 pb-12">
      <div className="space-y-3">
        <FilterToolbar
          filters={
            <>
              <ChipGroup
                mode="single"
                label="Show calls by how they ended"
                chips={OUTCOMES.map((o) => ({ value: o.value, label: o.label }))}
                value={outcome ?? null}
                onChange={(next) => setOutcome(OUTCOMES.find((o) => o.value === next)?.value)}
                className="gap-1.5"
              />
              <DateRangePicker
                label="Dates"
                hideLabel
                value={dates}
                onChange={setDates}
                max={today}
                placeholder="Any time"
                clearLabel="Show calls from any time"
                className="[&>div]:mt-0"
              />
              <label className="block">
                <span className="sr-only">Which way</span>
                <select
                  value={direction ?? ""}
                  onChange={(e) => setDirection(DIRECTIONS.find((d) => d.value === e.target.value)?.value)}
                  className={`${FIELD} mt-0 w-auto`}
                >
                  <option value="">Both ways</option>
                  {DIRECTIONS.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-flex cursor-pointer items-center gap-2 px-1 text-meta text-ink-muted touch:min-h-11">
                <input
                  type="checkbox"
                  checked={testCalls}
                  onChange={(e) => setTestCalls(e.target.checked)}
                  className="h-4 w-4 accent-brand-strong"
                />
                Include test calls
              </label>
            </>
          }
          tools={
            <>
              {exportAccess.allowed && (
                <ActionButton
                  variant="secondary-sm"
                  status={exporting.status}
                  pendingLabel="Preparing…"
                  successLabel="Downloaded"
                  onClick={() => exporting.run(filters)}
                >
                  Export CSV
                </ActionButton>
              )}
              <AskAssistant prompt="Summarise my latest calls: what callers wanted, and what I should follow up." />
            </>
          }
          active={active}
          onClearAll={clearAll}
          removeLabel={(filter) => `Remove the filter: ${filter.label}`}
        />
        {/* The denominator, only once the query has answered — a count rendered while
            loading says 0 and then jumps. With more pages behind it the loaded length is
            a statement about our query, not their business, so it is not called a total. */}
        {calls.data ? (
          <p role="status" className="text-meta text-ink-muted">
            {calls.hasNextPage ? "Showing the " : ""}
            <span className="font-semibold tabular-nums text-ink">{formatCount(rows.length)}</span>{" "}
            {calls.hasNextPage ? "most recent" : rows.length === 1 ? "call" : "calls"}
            {filtered ? " matching these filters" : ""}
            {phone && rows.length > 0 ? ". Swipe a call for quick actions." : ""}
          </p>
        ) : null}
        {live.isError ? (
          <p role="status" className="text-meta text-ink-muted">
            We could not check how your live calls are going just now. Their rows update when the calls end.
          </p>
        ) : null}
      </div>

      {calls.error && <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />}

      <div className="border-y border-line max-sm:-mx-4">
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
        ) : rows.length && phone ? (
          <CallsPhoneList
            rows={rows}
            callHref={(id) => href(`/c/${slug}/calls/${id}`)}
            actions={followUp}
            targetOf={targetOf}
          />
        ) : rows.length ? (
          <DataTable
            rows={rows}
            columns={columns}
            getRowId={(call) => call.id}
            // `isolate` keeps the live sheen (`LiveSheen`, `z-below`) above the row's own
            // background and below its content.
            rowClassName={(call) => (liveOf(call)?.state === "live" ? "isolate bg-brand-soft/40 dark:bg-brand-strong/10" : "")}
            label="Calls, newest first"
            partialNote={
              calls.hasNextPage
                ? `Sorted within the ${formatCount(rows.length)} calls loaded; older calls are not included.`
                : undefined
            }
          />
        ) : filtered ? (
          <EmptyState variant="filtered" message="No calls match this filter" onClear={clearAll} clearLabel="Show all calls" />
        ) : (
          <EmptyState
            illustration={<EmptySketch kind="calls" />}
            message="No calls yet."
            hint="A call you place shows here as soon as it is dialled. A call that comes in shows when it ends."
            action={
              <Link href={href(`/c/${slug}/agents`)} className={SECONDARY_BUTTON_SM}>
                Make a test call
              </Link>
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
      {followUp.dialogs}
    </div>
  );
}
