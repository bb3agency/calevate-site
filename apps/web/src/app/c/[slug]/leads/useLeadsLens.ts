"use client";

import { useEffect, useState } from "react";

import type { DateRange } from "@/components/arc/calendar";
import { istDateStamp } from "@/components/ui";
import {
  lensKey,
  type CapturedFilter,
  type LeadLens,
  type SavedView,
  type SavedViewFilters,
} from "@/lib/api/leads";
import { DEFAULT_LEAD_COLUMNS } from "@/lib/leadLabels";
import { fromViewDays, toViewDays } from "@/lib/viewDays";

import { anyFilterInForce, type LeadFilterKey } from "./leadFilters";
import { PAGE_SIZE } from "./leadsTable";
import type { LeadCallFilters } from "./MoreFilters";

type LeadStatus = NonNullable<SavedViewFilters["status"]>;
type Outcome = NonNullable<SavedViewFilters["last_outcome"]>;

/**
 * WHICH ROWS AND WHICH COLUMNS — the leads screen's filter state, and the one `LeadLens`
 * built from it that the table, the facet counts and the CSV export all read. That
 * sharing is the screen's correctness claim: the file cannot disagree with the table about
 * the filters when one object spells them (`lib/api/leads.ts::lensBody`).
 *
 * Every filter here is SERVER-side. A page holds 100 rows, so a filter applied in the
 * browser would be a filter over whatever happened to load.
 *
 * A saved view holds the whole lens except the search box and the question
 * (`crm.schemas.SavedViewFilters`), so `viewFilters` and `applyView` are exact inverses.
 */
export function useLeadsLens(
  needKey: string = "need",
  initial: { campaignId?: string; status?: string } = {},
) {
  // `?status=` comes from a link that opens this table on one stage (a Pip chart, D-934).
  const [status, setStatus] = useState<string | undefined>(initial.status);
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  /**
   * THE QUESTION (D-504). Submitted, never debounced: each submission buys an embedding
   * against the account's AI ceiling, so it fires when the person says so. `ask` is the
   * box, `askTerm` what the server was told.
   */
  const [ask, setAsk] = useState("");
  const [askTerm, setAskTerm] = useState("");
  /** "Assigned to me" — a member id sent to the server, never a slice of the page. */
  const [assignedTo, setAssignedTo] = useState<string | undefined>();
  /** Extraction-schema key → chosen values. */
  const [facetValues, setFacetValues] = useState<Record<string, string[]>>({});
  /**
   * `undefined` means "nothing chosen", and the table then asks for the usual five
   * (`DEFAULT_LEAD_COLUMNS`, with the business's own "what they want" key). Every other
   * column, the business's own fields included, is one tick away in the chooser.
   */
  const [chosenColumns, setChosenColumns] = useState<string[] | undefined>();
  /** When the lead came in, as India days, both ends included (D-893). */
  const [created, setCreated] = useState<DateRange | null>(null);
  /** When the lead's latest call happened. */
  const [lastCall, setLastCall] = useState<DateRange | null>(null);
  /** How the lead's latest call ended (`lib/callFilters.OUTCOMES`). */
  const [lastOutcome, setLastOutcome] = useState<string | undefined>();
  const [direction, setDirection] = useState<"inbound" | "outbound" | undefined>();
  /** False leaves out leads whose latest call was a free-trial test call. */
  const [testCalls, setTestCalls] = useState(true);
  const [followUp, setFollowUp] = useState<"done" | "not_done" | undefined>();
  const [callbackOpen, setCallbackOpen] = useState<boolean | undefined>();
  /** Captured details the rows must match ("city contains Hyd"). */
  const [captured, setCaptured] = useState<CapturedFilter[]>([]);
  /** The leads one campaign reached, set by the link from its results (D-905). */
  const [campaignId, setCampaignId] = useState<string | undefined>(initial.campaignId);
  const [activeViewId, setActiveViewId] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);

  // The search box drives the query key; a short pause is "finished typing", so one
  // keystroke is not one server-side LIKE.
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const lens: LeadLens = {
    status,
    search: searchTerm || undefined,
    ask: askTerm || undefined,
    assigned_to: assignedTo,
    fields: facetValues,
    created_from: created?.start,
    created_to: created?.end,
    last_call_from: lastCall?.start,
    last_call_to: lastCall?.end,
    last_outcome: lastOutcome,
    direction,
    test_calls: testCalls ? undefined : false,
    follow_up: followUp,
    callback_open: callbackOpen,
    captured: captured.length ? captured : undefined,
    campaign_id: campaignId,
    columns: chosenColumns ?? DEFAULT_LEAD_COLUMNS.map((key) => (key === "need" ? needKey : key)),
  };

  /**
   * HOW EACH FILTER IS PUT BACK. A `Record<LeadFilterKey, …>` cannot regress: a new
   * narrowing key on `LeadLens` makes this object incomplete and `tsc` refuses the build
   * until somebody writes how it is cleared. Search and question reset both the box and
   * the term — clearing only one is how a cleared-looking screen keeps a filter on.
   */
  const clearFilter: Record<LeadFilterKey, () => void> = {
    status: () => setStatus(undefined),
    search: () => {
      setSearch("");
      setSearchTerm("");
    },
    ask: () => {
      setAsk("");
      setAskTerm("");
    },
    assigned_to: () => setAssignedTo(undefined),
    // Never set by this screen (the lens carries it for agent-scoped reads), but it is a
    // filter, so it is answered rather than skipped.
    agent_id: () => {},
    fields: () => setFacetValues({}),
    // One picker sets both ends, so either end clears the range.
    created_from: () => setCreated(null),
    created_to: () => setCreated(null),
    last_call_from: () => setLastCall(null),
    last_call_to: () => setLastCall(null),
    last_outcome: () => setLastOutcome(undefined),
    direction: () => setDirection(undefined),
    test_calls: () => setTestCalls(true),
    follow_up: () => setFollowUp(undefined),
    callback_open: () => setCallbackOpen(undefined),
    captured: () => setCaptured([]),
    campaign_id: () => setCampaignId(undefined),
  };
  const clearFilters = () => {
    for (const clear of Object.values(clearFilter)) clear();
  };

  /**
   * The lens as a saved view stores it. `rolling` keeps a range that ends today as "the
   * last N days". The owner filter is a boolean on the view, resolved against whoever is
   * signed in; a stored id would dangle the day that colleague leaves.
   */
  const viewFilters = (rolling: boolean): SavedViewFilters => {
    const today = istDateStamp();
    return {
      status: (status as LeadStatus | undefined) ?? null,
      assigned_to_me: Boolean(assignedTo),
      fields: facetValues,
      created: toViewDays(created, today, rolling),
      last_call: toViewDays(lastCall, today, rolling),
      last_outcome: (lastOutcome as Outcome | undefined) ?? null,
      direction: direction ?? null,
      test_calls: testCalls,
      follow_up: followUp ?? null,
      callback_open: callbackOpen ?? null,
      captured,
    };
  };

  /** Puts back every filter the view holds, and clears the ones it does not. */
  const applyView = (view: SavedView | undefined, myUserId: string | undefined) => {
    const filters = view?.filters;
    const today = istDateStamp();
    setActiveViewId(view?.id);
    setStatus(filters?.status ?? undefined);
    setFacetValues(filters?.fields ?? {});
    setChosenColumns(view?.columns ?? undefined);
    setAssignedTo(filters?.assigned_to_me ? myUserId : undefined);
    setCreated(fromViewDays(filters?.created, today));
    setLastCall(fromViewDays(filters?.last_call, today));
    setLastOutcome(filters?.last_outcome ?? undefined);
    setDirection(filters?.direction ?? undefined);
    setTestCalls(filters?.test_calls ?? true);
    setFollowUp(filters?.follow_up ?? undefined);
    setCallbackOpen(filters?.callback_open ?? undefined);
    setCaptured(filters?.captured ?? []);
    // A view does not hold a campaign: that filter arrives only by its link.
    setCampaignId(undefined);
  };

  // A changed FILTER returns to page one — page 4 of "hot" is not page 4 of "won". Keyed
  // without the offset, or this would undo every page turn.
  const filterKey = lensKey(lens, { limit: PAGE_SIZE });
  useEffect(() => {
    setOffset(0);
  }, [filterKey]);

  /** How many of the "More filters" are narrowing the rows, for its closed state. */
  const moreInUse =
    (assignedTo ? 1 : 0) +
    Object.values(facetValues).filter((values) => values.length > 0).length +
    (created ? 1 : 0) +
    (lastCall ? 1 : 0) +
    (lastOutcome ? 1 : 0) +
    (direction ? 1 : 0) +
    (testCalls ? 0 : 1) +
    (followUp ? 1 : 0) +
    (callbackOpen !== undefined ? 1 : 0) +
    captured.length;

  /** `MoreFilters`' call half, given the details this account captures. */
  const callFilters = (capturedFields: LeadCallFilters["capturedFields"]): LeadCallFilters => ({
    created,
    onCreated: setCreated,
    lastCall,
    onLastCall: setLastCall,
    lastOutcome,
    onLastOutcome: setLastOutcome,
    direction,
    onDirection: setDirection,
    testCalls,
    onTestCalls: setTestCalls,
    followUp,
    onFollowUp: setFollowUp,
    callbackOpen,
    onCallbackOpen: setCallbackOpen,
    captured,
    onCaptured: setCaptured,
    capturedFields,
  });

  return {
    lens,
    filtered: anyFilterInForce(lens),
    moreInUse,
    callFilters,
    /** The key a selection must be cleared on: the lens AND the page. */
    currentLens: lensKey(lens, { limit: PAGE_SIZE, offset: offset || undefined }),
    clearFilters,
    applyView,
    viewFilters,
    status,
    setStatus,
    search,
    setSearch,
    ask,
    setAsk,
    askTerm,
    setAskTerm,
    assignedTo,
    setAssignedTo,
    facetValues,
    setFacetValues,
    chosenColumns,
    setChosenColumns,
    created,
    setCreated,
    lastCall,
    setLastCall,
    lastOutcome,
    setLastOutcome,
    direction,
    setDirection,
    testCalls,
    setTestCalls,
    followUp,
    setFollowUp,
    callbackOpen,
    setCallbackOpen,
    captured,
    setCaptured,
    campaignId,
    setCampaignId,
    activeViewId,
    setActiveViewId,
    offset,
    setOffset,
  };
}

/** The lens state one screen holds; the campaign picker takes it from the form. */
export type LeadsLensState = ReturnType<typeof useLeadsLens>;
