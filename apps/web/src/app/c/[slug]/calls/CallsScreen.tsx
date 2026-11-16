"use client";

/**
 * THE CALL LOG: every call, newest first, filtered on the server (REDESIGN-2).
 *
 * PRIMARY JOB: find the calls that need you and open one.
 *
 * ONE filter row (`FilterToolbar`, folded behind "Filters" on a phone): how the call ENDED
 * (outcome chips, "Needs you" first), WHEN as a span of India-time days (`DateRangePicker`,
 * `lib/callFilters`), WHICH WAY, FROM which campaign or Inbound line (D-1006; each row also
 * links to its own), and whether free-trial test calls are included. One agent's calls arrive by link from that agent's page
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
import { daysBetween, formatDateRange } from "@/components/arc/ist-dates";
import { RowMenu } from "@/components/arc/menu";
import { useFollowUpActions, type Dialer, type FollowUpTarget } from "@/components/calls/followUpActions";
import { DataTable } from "@/components/console/dataTable";
import { SavedViewBar } from "@/components/console/savedViewBar";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { LoadMore } from "@/components/interior/load-more";
import { FIELD, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount, istDateStamp } from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useCampaigns } from "@/lib/api/campaigns";
import { useInboundLines } from "@/lib/api/inboundLines";
import type { CallSummary } from "@/lib/api/client";
import {
  queryKeys,
  useActAccess,
  useCallsLog,
  useExportCalls,
  usePrefetchCall,
  useWriteAccess,
  type CallsLogFilters,
} from "@/lib/api/hooks";
import { useReadAhead } from "@/lib/readAhead";
import { readScreenMemory, useRememberScreen } from "@/lib/screenMemory";
import {
  useCallViews,
  useDeleteCallView,
  useSaveCallView,
  type CallView,
  type CallViewBody,
  type CallViewFilters,
} from "@/lib/api/callViews";
import { useLiveCalls, type CallLive } from "@/lib/api/liveCalls";
import { useClientRealm } from "@/lib/api/session";
import {
  DIRECTIONS,
  FOLLOW_UP,
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
import { describeViewDays, endsToday, fromViewDays, toViewDays } from "@/lib/viewDays";

import { CallAgain } from "./CallAgain";
import { callColumns, liveOf, outcomeRowClass } from "./callColumns";
import { CallsPhoneList } from "./CallsPhoneList";
import { sourcePath } from "./callSource";
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

/** "calls from the last 7 days, missed, incoming, not handled yet" — a view's line. */
function describeCallView(filters: CallViewFilters): string | null {
  const parts: string[] = [];
  const when = describeViewDays(filters.when);
  if (when) parts.push(`calls from ${when}`);
  const outcome = OUTCOMES.find((o) => o.value === filters.outcome);
  if (outcome) parts.push(outcome.label.toLowerCase());
  const way = DIRECTIONS.find((d) => d.value === filters.direction);
  if (way) parts.push(way.label.toLowerCase());
  const follow = FOLLOW_UP.find((f) => f.value === filters.follow_up);
  if (follow) parts.push(follow.label.toLowerCase());
  if (filters.callback_open === true) parts.push("a call-back waiting");
  if (filters.callback_open === false) parts.push("no call-back waiting");
  if (filters.test_calls === false) parts.push("no test calls");
  if (filters.agent_id) parts.push("one agent's");
  if (filters.campaign_id) parts.push("one campaign's");
  if (filters.inbound_line_id) parts.push("one Inbound line's");
  return parts.length ? parts.join(", ") : null;
}

/**
 * One page of the log. A paged read rather than the whole history: the log grows without
 * bound, and the reader asks for older calls with "Show older calls".
 */
const CALLS_PAGE_SIZE = 100;

/** Statuses a link may ask for; only shown as a chip that clears them. */
const STATUS_WORDS: Record<string, string> = {
  // The home screen's "missed calls": unanswered, busy, voicemail and failed together.
  missed: "missed",
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

/** The log's filters as `lib/screenMemory` keeps them between visits in one tab. */
interface CallsMemory {
  status: string;
  agentId: string;
  campaignId: string;
  inboundLineId: string;
  outcome: string;
  direction: string;
  dates: DateRange | null;
  testCalls: boolean;
  followUp: string;
  callbackOpen: boolean;
  activeViewId: string;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The filters a link may name; a link that names any opens on what it names alone. */
const LINK_FILTERS = ["status", "agent_id", "campaign_id", "inbound_line_id", "day", "test_calls"];

/** The "From" control's value: one campaign or one Inbound line, never both. */
type SourceChoice = { campaignId?: string; inboundLineId?: string };

function sourceValue({ campaignId, inboundLineId }: SourceChoice): string {
  if (campaignId) return `campaign:${campaignId}`;
  if (inboundLineId) return `line:${inboundLineId}`;
  return "";
}

function sourceOf(value: string): SourceChoice {
  const [kind, id] = value.split(":", 2);
  if (kind === "campaign" && id) return { campaignId: id };
  if (kind === "line" && id) return { inboundLineId: id };
  return {};
}

/** `?day=` (an IST date): the home screen's "missed calls today" opens on that day only. */
function linkedDay(param: string | null): DateRange | null {
  return param && DAY.test(param) ? { start: param, end: param } : null;
}

/**
 * Where the log was left, read once at mount, every value checked against what the
 * controls offer. A link that names a filter opens on that filter alone, as it always did.
 */
function rememberedCalls(slug: string, params: URLSearchParams): Partial<CallsMemory> {
  if (LINK_FILTERS.some((name) => params.has(name))) return {};
  const kept = readScreenMemory<CallsMemory>(`${slug}:calls`) ?? {};
  const text = (value: unknown) => (typeof value === "string" && value ? value : undefined);
  const dates = kept.dates;
  return {
    status: initialStatus(text(kept.status) ?? null),
    agentId: text(kept.agentId),
    campaignId: text(kept.campaignId),
    inboundLineId: text(kept.inboundLineId),
    outcome: OUTCOMES.find((o) => o.value === kept.outcome)?.value,
    direction: DIRECTIONS.find((d) => d.value === kept.direction)?.value,
    dates:
      dates && typeof dates === "object" && DAY.test(String(dates.start)) && DAY.test(String(dates.end))
        ? { start: dates.start, end: dates.end }
        : null,
    testCalls: typeof kept.testCalls === "boolean" ? kept.testCalls : undefined,
    followUp: FOLLOW_UP.find((f) => f.value === kept.followUp)?.value,
    callbackOpen: typeof kept.callbackOpen === "boolean" ? kept.callbackOpen : undefined,
    activeViewId: text(kept.activeViewId),
  };
}

export function CallsScreen({ slug }: { slug: string }) {
  // `href` keeps the D-22 operator session across in-realm links (session.tsx).
  const { session, href } = useClientRealm();
  const params = useSearchParams();
  // Opening a call and pressing Back comes back to the same filters (`lib/screenMemory`).
  const [kept] = useState(() => rememberedCalls(slug, params));
  const [status, setStatus] = useState<string | undefined>(() => initialStatus(params.get("status")) ?? kept.status);
  const [agentId, setAgentId] = useState<string | undefined>(() => params.get("agent_id") || kept.agentId);
  const [campaignId, setCampaignId] = useState<string | undefined>(() => params.get("campaign_id") || kept.campaignId);
  // A line's page links here with `?inbound_line_id=` (D-1006), as a campaign's results do.
  const [inboundLineId, setInboundLineId] = useState<string | undefined>(() =>
    params.get("campaign_id") ? undefined : params.get("inbound_line_id") || kept.inboundLineId,
  );
  const setSource = (choice: SourceChoice) => {
    setCampaignId(choice.campaignId);
    setInboundLineId(choice.inboundLineId);
  };
  const [outcome, setOutcome] = useState<CallOutcome | undefined>(kept.outcome as CallOutcome | undefined);
  const [direction, setDirection] = useState<CallDirection | undefined>(kept.direction as CallDirection | undefined);
  const [dates, setDates] = useState<DateRange | null>(() => linkedDay(params.get("day")) ?? kept.dates ?? null);
  // On by default: a trial account has only test calls, and a log that hid every one of
  // them would read as "nobody has called". Each one carries a "Test call" tag.
  const [testCalls, setTestCalls] = useState(() =>
    params.get("test_calls") === "false" ? false : (kept.testCalls ?? true),
  );
  /** Marked handled or not yet (D-893), and whether a call-back is waiting. */
  const [followUpFilter, setFollowUpFilter] = useState<"done" | "not_done" | undefined>(
    kept.followUp as "done" | "not_done" | undefined,
  );
  const [callbackOpen, setCallbackOpen] = useState<boolean | undefined>(kept.callbackOpen);

  const today = istDateStamp();
  const filters: CallsLogFilters = {
    status,
    agentId,
    campaignId,
    inboundLineId,
    outcome,
    direction,
    testCalls,
    followUp: followUpFilter,
    callbackOpen,
    ...(dates ? callWindow("custom", today, dates.start, dates.end) : {}),
  };
  const calls = useCallsLog(session, { ...filters, pageSize: CALLS_PAGE_SIZE });
  const readAhead = useReadAhead(usePrefetchCall(session));
  const exportCalls = useExportCalls(session);
  // The file arriving is its own success; the button's tick says it started.
  const exporting = useActionFeedback(exportCalls, { errorTitle: "Could not export your calls" });
  const exportAccess = useWriteAccess(session, "calls:read_raw", "export your calls");
  const dispatch = useWriteAccess(session, "leads:dispatch", "call people again");
  const filtered = Boolean(
    status ||
      agentId ||
      campaignId ||
      inboundLineId ||
      outcome ||
      direction ||
      dates ||
      !testCalls ||
      followUpFilter ||
      callbackOpen !== undefined,
  );
  const phone = useMediaQuery(PHONE);

  /* SAVED VIEWS (D-893 L2): every filter on this screen, under a name only this person
     sees. Saving and applying are exact inverses, so a view puts back what it held and
     clears the rest. */
  const callViews = useCallViews(session);
  const [activeViewId, setActiveViewId] = useState<string | undefined>(kept.activeViewId);
  useRememberScreen(`${slug}:calls`, {
    status,
    agentId,
    campaignId,
    inboundLineId,
    outcome,
    direction,
    dates,
    testCalls,
    followUp: followUpFilter,
    callbackOpen,
    activeViewId,
  } satisfies Partial<CallsMemory>);
  const mayView = useActAccess(session, "leads:write", "leads.saved_view", "save a view");
  const callViewFilters = (rolling: boolean): CallViewFilters => ({
    status: status ?? null,
    agent_id: agentId ?? null,
    campaign_id: campaignId ?? null,
    inbound_line_id: inboundLineId ?? null,
    outcome: outcome ?? null,
    direction: direction ?? null,
    when: toViewDays(dates, today, rolling),
    test_calls: testCalls,
    follow_up: followUpFilter ?? null,
    callback_open: callbackOpen ?? null,
  });
  const applyCallView = (view: CallView | undefined) => {
    const saved = view?.filters;
    setActiveViewId(view?.id);
    setStatus(saved?.status ?? undefined);
    setAgentId(saved?.agent_id ?? undefined);
    setCampaignId(saved?.campaign_id ?? undefined);
    setInboundLineId(saved?.inbound_line_id ?? undefined);
    setOutcome(saved?.outcome ?? undefined);
    setDirection(saved?.direction ?? undefined);
    setDates(fromViewDays(saved?.when, today));
    setTestCalls(saved?.test_calls ?? true);
    setFollowUpFilter(saved?.follow_up ?? undefined);
    setCallbackOpen(saved?.callback_open ?? undefined);
  };

  /* Who rings a caller back: the agent that took the call when it places calls, else the
     account's first agent that does (`canDialOut`, the one definition). */
  const agents = useAgents(session);
  const campaigns = useCampaigns(session);
  const lines = useInboundLines(session);
  const dialers = agents.data ? agents.data.filter(canDialOut) : undefined;
  const followUp = useFollowUpActions(session, {
    dialerFor: (target) => {
      const chosen = dialers?.find((agent) => agent.id === target.agentId) ?? dialers?.[0];
      return chosen ? ({ id: chosen.id, name: chosen.name } satisfies Dialer) : null;
    },
    // "None of your agents places calls" only once the list has arrived and says so.
    noDialerReason:
      agents.error != null
        ? "Couldn't load your agents. Reload to call."
        : !agents.data
          ? "Checking your agents…"
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
  /* The "From" control's choices: the campaigns and Inbound lines in use. An archived one
     chosen by a link or a saved view is named from its rows, so the chip still says which. */
  const campaignChoices = (campaigns.isSuccess ? campaigns.data : []).filter((c) => !c.archived_at || c.id === campaignId);
  const lineChoices = lines.isSuccess ? lines.data : [];
  const sourcesUnread = campaigns.isError || lines.isError;
  const campaignName = campaignId
    ? (campaignChoices.find((c) => c.id === campaignId)?.name ??
      rows.find((call) => call.campaign?.id === campaignId)?.campaign?.name)
    : undefined;
  const lineName = inboundLineId
    ? (lineChoices.find((l) => l.id === inboundLineId)?.name ??
      rows.find((call) => call.inbound_line?.id === inboundLineId)?.inbound_line?.name)
    : undefined;
  const offerSource = campaignChoices.length + lineChoices.length > 0 || Boolean(campaignId || inboundLineId);

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
      {
        id: "calls-follow-up",
        label: "Handled",
        type: "select",
        value: followUpFilter ?? "",
        options: [{ value: "", label: "Any" }, ...FOLLOW_UP.map((f) => ({ value: f.value, label: f.label }))],
      },
      {
        id: "calls-from",
        label: "From (campaign or Inbound line)",
        type: "select",
        value: sourceValue({ campaignId, inboundLineId }),
        options: [
          { value: "", label: "Any" },
          ...lineChoices.map((l) => ({ value: `line:${l.id}`, label: `Inbound line: ${l.name}` })),
          ...campaignChoices.map((c) => ({ value: `campaign:${c.id}`, label: `Campaign: ${c.name}` })),
        ],
      },
      {
        id: "calls-callback",
        label: "Call-back",
        type: "select",
        value: callbackOpen === undefined ? "" : String(callbackOpen),
        options: [
          { value: "", label: "Any" },
          { value: "true", label: "Waiting" },
          { value: "false", label: "None waiting" },
        ],
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
      { key: "campaign_link", label: "Only one campaign's calls?", value: campaignId ? `yes: ${campaignName ?? "one campaign"}` : "no" },
      { key: "line_link", label: "Only one Inbound line's calls?", value: inboundLineId ? `yes: ${lineName ?? "one line"}` : "no" },
      { key: "test_calls", label: "Are test calls included?", value: testCalls ? "yes" : "no" },
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
        } else if (item.field_id === "calls-follow-up") {
          setFollowUpFilter(FOLLOW_UP.find((f) => f.value === wanted)?.value);
        } else if (item.field_id === "calls-from") {
          const offered =
            wanted === "" ||
            lineChoices.some((l) => `line:${l.id}` === wanted) ||
            campaignChoices.some((c) => `campaign:${c.id}` === wanted);
          if (offered) setSource(sourceOf(wanted));
        } else if (item.field_id === "calls-callback") {
          setCallbackOpen(wanted === "true" ? true : wanted === "false" ? false : undefined);
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
    readAhead,
    menu: (call) => <RowMenu label={callTitle(call)} items={followUp.menuItems(targetOf(call))} />,
    sourceHref: (source) => href(sourcePath(slug, source)),
  });
  const clearAll = () => {
    setStatus(undefined);
    setAgentId(undefined);
    setSource({});
    setOutcome(undefined);
    setDirection(undefined);
    setDates(null);
    setTestCalls(true);
    setFollowUpFilter(undefined);
    setCallbackOpen(undefined);
  };

  const active: ActiveFilter[] = [
    ...(outcome ? [{ id: "outcome", label: OUTCOMES.find((o) => o.value === outcome)?.label ?? outcome, onRemove: () => setOutcome(undefined) }] : []),
    ...(dates ? [{ id: "dates", label: formatDateRange(dates.start, dates.end), onRemove: () => setDates(null) }] : []),
    ...(direction ? [{ id: "direction", label: DIRECTIONS.find((d) => d.value === direction)?.label ?? direction, onRemove: () => setDirection(undefined) }] : []),
    ...(followUpFilter
      ? [{ id: "follow-up", label: FOLLOW_UP.find((f) => f.value === followUpFilter)?.label ?? followUpFilter, onRemove: () => setFollowUpFilter(undefined) }]
      : []),
    ...(callbackOpen !== undefined
      ? [{ id: "callback", label: callbackOpen ? "Call-back waiting" : "No call-back waiting", onRemove: () => setCallbackOpen(undefined) }]
      : []),
    ...(!testCalls ? [{ id: "tests", label: "Test calls left out", onRemove: () => setTestCalls(true) }] : []),
    ...(agentId ? [{ id: "agent", label: `Agent: ${agentName ?? "the chosen agent"}`, onRemove: () => setAgentId(undefined) }] : []),
    ...(campaignId
      ? [{ id: "campaign", label: campaignName ? `Campaign: ${campaignName}` : "One campaign's calls", onRemove: () => setSource({}) }]
      : []),
    ...(inboundLineId
      ? [{ id: "line", label: lineName ? `Inbound line: ${lineName}` : "One Inbound line's calls", onRemove: () => setSource({}) }]
      : []),
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
              {offerSource ? (
                <label className="block min-w-0 max-w-full">
                  <span className="sr-only">From a campaign or an Inbound line</span>
                  <select
                    value={sourceValue({ campaignId, inboundLineId })}
                    onChange={(e) => setSource(sourceOf(e.target.value))}
                    className={`${FIELD} mt-0 w-auto max-w-full`}
                  >
                    <option value="">Any line or campaign</option>
                    {lineChoices.length > 0 || inboundLineId ? (
                      <optgroup label="Inbound lines">
                        {lineChoices.map((l) => (
                          <option key={l.id} value={`line:${l.id}`}>
                            {l.name}
                          </option>
                        ))}
                        {inboundLineId && !lineChoices.some((l) => l.id === inboundLineId) ? (
                          <option value={`line:${inboundLineId}`}>{lineName ?? "The chosen line"}</option>
                        ) : null}
                      </optgroup>
                    ) : null}
                    {campaignChoices.length > 0 || campaignId ? (
                      <optgroup label="Campaigns">
                        {campaignChoices.map((c) => (
                          <option key={c.id} value={`campaign:${c.id}`}>
                            {c.name}
                          </option>
                        ))}
                        {campaignId && !campaignChoices.some((c) => c.id === campaignId) ? (
                          <option value={`campaign:${campaignId}`}>{campaignName ?? "The chosen campaign"}</option>
                        ) : null}
                      </optgroup>
                    ) : null}
                  </select>
                </label>
              ) : null}
              {sourcesUnread ? (
                <p className="text-meta text-ink-muted">We could not list your lines and campaigns.</p>
              ) : null}
              <label className="block">
                <span className="sr-only">Handled</span>
                <select
                  value={followUpFilter ?? ""}
                  onChange={(e) => setFollowUpFilter(FOLLOW_UP.find((f) => f.value === e.target.value)?.value)}
                  className={`${FIELD} mt-0 w-auto`}
                >
                  <option value="">Handled or not</option>
                  {FOLLOW_UP.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="sr-only">Call-back</span>
                <select
                  value={callbackOpen === undefined ? "" : String(callbackOpen)}
                  onChange={(e) =>
                    setCallbackOpen(e.target.value === "" ? undefined : e.target.value === "true")
                  }
                  className={`${FIELD} mt-0 w-auto`}
                >
                  <option value="">Any call-back</option>
                  <option value="true">Call-back waiting</option>
                  <option value="false">No call-back waiting</option>
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
        <SavedViewBar<CallView, CallViewBody>
          views={callViews.data}
          error={callViews.error}
          activeViewId={activeViewId}
          canWrite={mayView.allowed}
          writeReason={mayView.reason}
          onApply={applyCallView}
          bodyFor={(name, rolling) => ({ name, filters: callViewFilters(rolling) })}
          session={session}
          useSave={useSaveCallView}
          useRemove={useDeleteCallView}
          allLabel="All calls (no view)"
          describe={(view) => describeCallView(view.filters)}
          rollingNote={
            dates && endsToday(dates, today)
              ? `saved as the last ${daysBetween(dates.start, dates.end)} days, so it stays up to date`
              : null
          }
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
        {/* Retrying the unanswered: offered on the view that shows them (D-893 L1). */}
        {outcome === "missed" && dispatch.allowed ? (
          <CallAgain
            session={session}
            dialers={dialers}
            scope={{ direction, fromDay: dates?.start, toDay: dates?.end, testCalls, agentId, campaignId, inboundLineId }}
          />
        ) : null}
        {live.isError ? (
          <p role="status" className="text-meta text-ink-muted">
            Live status paused. Rows update when calls end.
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
               `!calls.data` keeps it from printing "No calls yet" (§52). With an error and
               no rows the notice above is the whole answer; rows that survive a failed
               poll are real and stay under it, as on the Leads page. */
        !calls.data ? (
          calls.error ? null : (
            <div className="p-4">
              <ProblemNotice error={new Error("Your calls did not load.")} onRetry={() => void calls.refetch()} />
            </div>
          )
        ) : rows.length && phone ? (
          <CallsPhoneList
            rows={rows}
            callHref={(id) => href(`/c/${slug}/calls/${id}`)}
            readAhead={readAhead}
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
            rowClassName={(call) =>
              liveOf(call)?.state === "live" ? "isolate bg-brand-soft/40 dark:bg-brand-strong/10" : outcomeRowClass(call)
            }
            label="Calls, newest first"
            partialNote={
              calls.hasNextPage
                ? `Sorted within the ${formatCount(rows.length)} calls loaded.`
                : undefined
            }
          />
        ) : filtered ? (
          <EmptyState variant="filtered" message="No calls match this filter" onClear={clearAll} clearLabel="Show all calls" />
        ) : (
          <EmptyState
            illustration={<EmptySketch kind="calls" />}
            message="No calls yet."
            hint="Calls show here as they happen."
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
