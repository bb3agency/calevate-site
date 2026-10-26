"use client";

import { useEffect, useState } from "react";

import { lensKey, type LeadLens } from "@/lib/api/leads";
import { DEFAULT_LEAD_COLUMNS } from "@/lib/leadLabels";

import { anyFilterInForce, type LeadFilterKey } from "./leadFilters";
import { PAGE_SIZE } from "./leadsTable";

/**
 * WHICH ROWS AND WHICH COLUMNS — the leads screen's filter state, and the one `LeadLens`
 * built from it that the table, the facet counts and the CSV export all read. That
 * sharing is the screen's correctness claim: the file cannot disagree with the table about
 * the filters when one object spells them (`lib/api/leads.ts::lensBody`).
 *
 * Every filter here is SERVER-side. A page holds 100 rows, so a filter applied in the
 * browser would be a filter over whatever happened to load.
 */
export function useLeadsLens(needKey: string = "need") {
  const [status, setStatus] = useState<string | undefined>();
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
  const [created, setCreated] = useState<{ start: string; end: string } | null>(null);
  /** How the lead's latest call ended (`lib/callFilters.OUTCOMES`). */
  const [lastOutcome, setLastOutcome] = useState<string | undefined>();
  const [followUp, setFollowUp] = useState<"done" | "not_done" | undefined>();
  const [callbackOpen, setCallbackOpen] = useState<boolean | undefined>();
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
    last_outcome: lastOutcome,
    follow_up: followUp,
    callback_open: callbackOpen,
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
    last_outcome: () => setLastOutcome(undefined),
    follow_up: () => setFollowUp(undefined),
    callback_open: () => setCallbackOpen(undefined),
  };
  const clearFilters = () => {
    for (const clear of Object.values(clearFilter)) clear();
  };

  // A changed FILTER returns to page one — page 4 of "hot" is not page 4 of "won". Keyed
  // without the offset, or this would undo every page turn.
  const filterKey = lensKey(lens, { limit: PAGE_SIZE });
  useEffect(() => {
    setOffset(0);
  }, [filterKey]);

  return {
    lens,
    filtered: anyFilterInForce(lens),
    /** The key a selection must be cleared on: the lens AND the page. */
    currentLens: lensKey(lens, { limit: PAGE_SIZE, offset: offset || undefined }),
    clearFilters,
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
    lastOutcome,
    setLastOutcome,
    followUp,
    setFollowUp,
    callbackOpen,
    setCallbackOpen,
    activeViewId,
    setActiveViewId,
    offset,
    setOffset,
  };
}
