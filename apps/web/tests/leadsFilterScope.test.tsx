import { act, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import {
  anyFilterInForce,
  filtersInForce,
  narrowedBeyondStatus,
  LEAD_FILTER_KEYS,
} from "@/app/c/[slug]/leads/leadFilters";
import { exportRefusal, scopeLabel } from "@/app/c/[slug]/leads/leadsTable";
import type { Me } from "@/lib/api/client";
import { useLeadsLens } from "@/app/c/[slug]/leads/useLeadsLens";
import type { Lead, LeadLens, LeadList, Member, SavedView } from "@/lib/api/leads";
import { istDateStamp } from "@/components/ui";
import { shiftDay } from "@/lib/callFilters";

import { readInfoTip } from "./infoTip";
import { lensOf, problem, renderClientPage, type ApiCall } from "./harness";
import { LEAD_FIELDS_CORE_ONLY } from "./fixtures/sharedReads";

/**
 * WHAT THE SCREEN IS ALLOWED TO SAY ABOUT AN ACCOUNT WITH FILTERS ON.
 *
 * The leads screen sends the server FIVE filters — status, search, question, facet values
 * and owner — and three of its sentences were derived from two of them:
 *
 * 1. **The empty state.** `status || searchTerm` decided the title, the hint and whether a
 *    "Clear the filters" button appeared at all. An owner who ticked "Assigned to me", or
 *    chose one facet value, got a correct zero-row response and the words "No leads yet —
 *    Every answered call becomes a lead within two minutes." over an account holding
 *    twelve hundred leads, with nothing offered to undo it. UX-DOCTRINE §52: a statement
 *    about the account manufactured from something that is not evidence about the account.
 * 2. **The header count** (`scopeLabel`) — a bare "12 leads", which reads as the total.
 * 3. **The stage tally** — "In this account, by stage:" printed over numbers the owner
 *    chip and the facet rail had already narrowed.
 *
 * And the button that was supposed to rescue them cleared two filters of five.
 *
 * Every assertion below is written against the SENTENCE a client reads, not against the
 * boolean behind it, so the fix can be reshaped without rewriting the suite. The shape
 * itself is pinned once, at the bottom: the derivation is exhaustive over `LeadLens` by
 * type, which is what makes a sixth filter a compile error rather than a sixth bug.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: [
    "leads:read",
    "leads:write",
    "leads:dispatch",
    "calls:read_raw",
  ],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

/** A staff session: everything but `calls:read_raw`, which is the export's gate. */
const STAFF: Me = {
  ...ME,
  role: "staff",
  permissions: ["leads:read", "leads:write"],
};

const MEMBERS: Member[] = [{ id: "u1", name: "Priya Nair", role: "owner" }];

const COLUMNS: LeadList["columns"] = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
];

function leadList(items: Lead[], over: Partial<LeadList> = {}): LeadList {
  return {
    items,
    columns: COLUMNS,
    available_columns: COLUMNS,
    dropped_column_keys: [],
    total: items.length,
    limit: 100,
    offset: 0,
    status_counts_matching_search: {
      new: 0,
      contacted: 0,
      interested: 0,
      hot: 0,
      won: 0,
      lost: 0,
    },
    semantic_truncated: false,
    ...over,
  };
}

/**
 * The account this suite is about: the server answers every lens with ZERO rows, exactly
 * as it correctly would for a filter that matches nothing — while `status_counts` say the
 * account is far from empty. That gap is the whole subject: the screen must not turn a
 * filtered zero into "you have no leads".
 */
function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": MEMBERS,
    "POST /v1/leads/search": leadList([]),
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    "/v1/lead-fields": LEAD_FIELDS_CORE_ONLY,
    ...over,
  };
}

/** The last lens the table asked the server for. */
function lastSearchLens(calls: ApiCall[]): Record<string, unknown> {
  const searches = calls.filter(
    (c) => c.path === "/v1/leads/search" && c.method === "POST",
  );
  expect(searches.length, "the table made no search request").toBeGreaterThan(
    0,
  );
  return lensOf(searches[searches.length - 1]);
}

/** Tick "Assigned to me" — a real server-side filter that the old chain never saw. */
async function filterByOwner(): Promise<void> {
  const chip = await screen.findByRole("button", { name: "Assigned to me" });
  await act(async () => {
    fireEvent.click(chip);
  });
}

/** Ask the semantic question — the other filter the empty state was blind to. */
async function askQuestion(text: string): Promise<void> {
  const box = await screen.findByLabelText("Find leads by what they asked for");
  await act(async () => {
    fireEvent.change(box, { target: { value: text } });
    fireEvent.submit(box.closest("form")!);
  });
}

describe("the empty state belongs to the filters, not to the business", () => {
  it("does not say 'No leads yet' when the OWNER filter is what emptied the table", async () => {
    const { container } = await renderClientPage(<LeadsPage />, routes());
    await screen.findByRole("button", { name: "Assigned to me" });

    await filterByOwner();

    // The defect, in the words a client read.
    expect(container.textContent).not.toContain("No leads yet");
    expect(container.textContent).not.toContain(
      "Every answered call becomes a lead",
    );
    expect(screen.getByText("No leads match these filters")).toBeTruthy();
    // And the way out is OFFERED, not merely named (ux-audit F-18).
    expect(
      screen.getByRole("button", { name: "Clear the filters" }),
    ).toBeTruthy();
  });

  it("does not say 'No leads yet' when a QUESTION is what emptied the table", async () => {
    const { container } = await renderClientPage(<LeadsPage />, routes());
    await screen.findByLabelText("Find leads by what they asked for");

    await askQuestion("3BHK in Gachibowli");

    // The question branch always had its own title; the HINT and the button below it
    // still fell through to the unfiltered arm, so a ranked empty table told the client
    // their leads were still on their way.
    expect(container.textContent).toContain(
      "No lead's captured answers match that question",
    );
    expect(container.textContent).not.toContain(
      "Every answered call becomes a lead",
    );
    expect(
      screen.getByRole("button", { name: "Clear the filters" }),
    ).toBeTruthy();
  });

  it("still says 'No leads yet' when nothing is filtering — the sentence is not deleted", async () => {
    const { container } = await renderClientPage(<LeadsPage />, routes());

    expect(await screen.findByText("No leads yet")).toBeTruthy();
    expect(container.textContent).toContain(
      "Every answered call becomes a lead",
    );
    // Nothing to clear, so nothing is offered.
    expect(
      screen.queryByRole("button", { name: "Clear the filters" }),
    ).toBeNull();
  });
});

describe("'Clear the filters' clears the filters — all of them", () => {
  it("drops the owner filter and the question, not just the status chip and the search", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, routes());
    await screen.findByLabelText("Find leads by what they asked for");

    // Three filters at once, on three different axes: the chip, the question and the
    // owner. The old clear knew about one of them.
    await act(async () => {
      fireEvent.click(screen.getByRole("radio", { name: /^Hot/ }));
    });
    await askQuestion("3BHK in Gachibowli");
    await filterByOwner();

    const narrowed = lastSearchLens(calls);
    expect(narrowed.status).toBe("hot");
    expect(narrowed.ask).toBe("3BHK in Gachibowli");
    expect(narrowed.assigned_to).toBe("u1");

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Clear the filters" }),
      );
    });

    await waitFor(() => {
      const cleared = lastSearchLens(calls);
      expect(cleared.status).toBeUndefined();
      expect(cleared.search).toBeUndefined();
      expect(cleared.ask).toBeUndefined();
      expect(cleared.assigned_to).toBeUndefined();
      expect(cleared.f ?? []).toEqual([]);
    });

    // And the screen agrees with the request it just made.
    expect(await screen.findByText("No leads yet")).toBeTruthy();
  });
});

describe("the two counts say what they are counts OF", () => {
  it("names the filters in the header count and in the stage tally", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "POST /v1/leads/search": leadList([], {
          total: 12,
          status_counts_matching_search: {
            new: 4,
            contacted: 3,
            interested: 2,
            hot: 1,
            won: 1,
            lost: 1,
          },
        }),
      }),
    );
    await screen.findByRole("button", { name: "Assigned to me" });

    // Unfiltered, both sentences are about the account, and they may say so. The scope
    // of the stage counts is behind the ⓘ beside the count now.
    expect(await readInfoTip("these counts")).toContain("In this account, by stage:");

    await filterByOwner();

    // The header count is 12 of a narrowed set — "12 leads" beside a filtered table
    // reads as the account total.
    expect(container.textContent).toContain("leads matching your filters");
    // And the six badges beside it are the server's counts over that same narrowed
    // scope (crm/service.py), so they are not "this account" either.
    await waitFor(async () => {
      expect(await readInfoTip("these counts")).toContain("Matching these filters, by stage:");
    });
    expect(await readInfoTip("these counts")).not.toContain("In this account, by stage:");
  });
});

describe("the CSV refusal is on the screen, not only in a tooltip", () => {
  it("states why a question cannot be exported, in text a phone and a screen reader reach", async () => {
    const { container } = await renderClientPage(<LeadsPage />, routes());
    await screen.findByLabelText("Find leads by what they asked for");

    await askQuestion("3BHK in Gachibowli");

    const button = screen.getByRole("button", {
      name: /Export this view as CSV/,
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    // The assertion that would have caught it: the sentence is in the DOCUMENT, not in
    // an attribute of a control that takes no focus and receives no hover on touch.
    expect(container.textContent).toContain(
      "A question ranks the best matches",
    );
    expect(container.textContent).toContain(
      "Clear it to export by the filters instead",
    );
  });

  it("states the permission refusal on the screen for a role that lacks calls:read_raw", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": STAFF }),
    );

    const button = (await screen.findByRole("button", {
      name: /Export this view as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(container.textContent).toContain(
      "Only an account owner can export leads.",
    );
  });

  it("says nothing at all while the permission answer is still coming", async () => {
    // A refusal we have not received is not a refusal (§52): a note that flashed and
    // then retracted itself would be worse than the wait. `/v1/me` failing is the other
    // half — that IS an answer of a kind, and it gets its own sentence.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": problem(503, { title: "Service unavailable" }) }),
    );

    await screen.findByRole("button", { name: /Export this view as CSV/ });
    expect(container.textContent).not.toContain(
      "Only an account owner can export leads.",
    );
    expect(container.textContent).toContain(
      "could not check whether you can export",
    );
  });

  it("says nothing when the export is available", async () => {
    const { container } = await renderClientPage(<LeadsPage />, routes());
    const button = (await screen.findByRole("button", {
      name: /Export this view as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(container.textContent).not.toContain(
      "A question ranks the best matches",
    );
    expect(container.textContent).not.toContain(
      "Only an account owner can export leads.",
    );
  });
});

/**
 * THE SHAPE, pinned directly.
 *
 * The screen assertions above would pass over a boolean chain that happened to name all
 * five filters today. These are about why it cannot go stale on the sixth: the key set is
 * derived from `LeadLens` itself, so every filter the wire has is a filter this
 * derivation answers for — including `agent_id`, which no control on the screen sets yet.
 */
describe("the call filters (D-893) are server filters on the one lens", () => {
  it("sends last call, follow-up and call-back to the server and clears them with the rest", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, routes());
    const lastCall = await screen.findByLabelText("Last call");
    await act(async () => {
      fireEvent.change(lastCall, { target: { value: "missed" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Follow-up"), { target: { value: "not_done" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Call-back"), { target: { value: "false" } });
    });
    await waitFor(() =>
      expect(lastSearchLens(calls)).toMatchObject({
        last_outcome: "missed",
        follow_up: "not_done",
        callback_open: false,
      }),
    );
    // Narrowed by calls, emptied by the filter: never "you have no leads".
    expect(await screen.findByText("No leads match these filters")).toBeTruthy();
    expect(screen.getByText(/More filters · 3 in use/)).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Clear the filters" }));
    });
    await waitFor(() => {
      const lens = lastSearchLens(calls);
      expect(lens.last_outcome).toBeUndefined();
      expect(lens.follow_up).toBeUndefined();
      expect(lens.callback_open).toBeUndefined();
    });
  });

  it("counts a created-date range as in force and drops it on clear", () => {
    const lens: LeadLens = { created_from: "2026-10-20", created_to: "2026-10-26" };
    expect(filtersInForce(lens)).toEqual(["created_from", "created_to"]);
    expect(anyFilterInForce({ callback_open: false })).toBe(true);
    expect(anyFilterInForce({ follow_up: undefined, last_outcome: "" })).toBe(false);
  });
});

describe("the derivation is exhaustive over the lens, not over the filters we remembered", () => {
  it("answers for every narrowing key the lens has, and for nothing else", () => {
    // `columns` changes what a row SHOWS, never which rows there are.
    expect(LEAD_FILTER_KEYS).not.toContain("columns");
    expect([...LEAD_FILTER_KEYS].sort()).toEqual(
      [
        "agent_id",
        "ask",
        "assigned_to",
        "callback_open",
        "captured",
        "created_from",
        "created_to",
        "direction",
        "fields",
        "follow_up",
        "last_call_from",
        "last_call_to",
        "last_outcome",
        "search",
        "status",
        "test_calls",
      ].sort(),
    );
  });

  it("reads each filter the way the request does", () => {
    expect(anyFilterInForce({})).toBe(false);
    // Empty is not set — `lensBody` drops all three before the request goes out.
    expect(anyFilterInForce({ search: "", ask: "", fields: {} })).toBe(false);
    // A facet key the client OPENED and chose nothing in is not a filter either.
    expect(anyFilterInForce({ fields: { budget: [] } })).toBe(false);
    expect(anyFilterInForce({ fields: { budget: ["50L"] } })).toBe(true);
    expect(filtersInForce({ status: "hot", assigned_to: "u1" })).toEqual([
      "status",
      "assigned_to",
    ]);
  });

  it("keeps the stage tally's question separate — every filter EXCEPT the stage chip", () => {
    // The server computes the badges over the scope minus the status filter, so a stage
    // chip alone leaves them account-wide and everything else does not.
    expect(narrowedBeyondStatus({ status: "hot" })).toBe(false);
    expect(narrowedBeyondStatus({ status: "hot", assigned_to: "u1" })).toBe(
      true,
    );
    expect(narrowedBeyondStatus({ fields: { budget: ["50L"] } })).toBe(true);
  });

  it("labels the header count off the same lens", () => {
    const owned: LeadLens = { assigned_to: "u1" };
    expect(scopeLabel({}, 12)).toBe("leads");
    expect(scopeLabel({ status: "hot" }, 12)).toBe("hot leads");
    expect(scopeLabel(owned, 12)).toBe("leads matching your filters");
    expect(scopeLabel(owned, 1)).toBe("lead matching your filters");
  });

  it("orders the export refusal the way the button is disabled", () => {
    // A question refuses the export even for an owner who holds the permission.
    expect(exportRefusal("3BHK", true, null)).toContain("cannot be exported");
    expect(
      exportRefusal("", false, "Only an account owner can export leads."),
    ).toBe("Only an account owner can export leads.");
    // Not yet answered, and available: neither is a refusal.
    expect(exportRefusal("", false, null)).toBeNull();
    expect(exportRefusal("", true, null)).toBeNull();
  });
});

describe("a saved view holds the whole lens", () => {
  const base: SavedView = {
    id: "v1",
    name: "Hot",
    columns: null,
    filters: { status: "hot", assigned_to_me: true, fields: {}, test_calls: true },
    stale_column_keys: [],
    stale_filter_keys: [],
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
  };

  it("clears the call filters a view does not name", () => {
    const { result } = renderHook(() => useLeadsLens());
    act(() => {
      result.current.setCreated({ start: "2026-10-20", end: "2026-10-26" });
      result.current.setLastOutcome("missed");
      result.current.setFollowUp("not_done");
      result.current.setCallbackOpen(true);
      result.current.setTestCalls(false);
    });
    act(() => result.current.applyView(base, "u1"));
    expect(filtersInForce(result.current.lens)).toEqual(["status", "assigned_to"]);
    expect(result.current.activeViewId).toBe("v1");
  });

  it("puts back every call filter it was saved with", () => {
    const { result } = renderHook(() => useLeadsLens());
    const view: SavedView = {
      ...base,
      filters: {
        ...base.filters,
        created: { from_day: "2026-10-21", to_day: "2026-10-27", last_days: 7 },
        last_call: { from_day: "2026-10-01", to_day: "2026-10-10", last_days: null },
        last_outcome: "missed",
        direction: "inbound",
        test_calls: false,
        follow_up: "not_done",
        callback_open: false,
        captured: [{ key: "city", op: "contains", value: "Hyd" }],
      },
    };
    act(() => result.current.applyView(view, "u1"));
    expect(result.current.lens).toMatchObject({
      status: "hot",
      assigned_to: "u1",
      created_from: "2026-10-21",
      created_to: "2026-10-27",
      last_call_from: "2026-10-01",
      last_call_to: "2026-10-10",
      last_outcome: "missed",
      direction: "inbound",
      test_calls: false,
      follow_up: "not_done",
      callback_open: false,
      captured: [{ key: "city", op: "contains", value: "Hyd" }],
    });
  });

  it("saves what it applies: a range ending today as the last N days, others as days", () => {
    const { result } = renderHook(() => useLeadsLens());
    const today = istDateStamp();
    act(() => {
      result.current.setCreated({ start: shiftDay(today, -6), end: today });
      result.current.setLastCall({ start: "2026-10-01", end: "2026-10-10" });
      result.current.setDirection("outbound");
    });
    expect(result.current.viewFilters(true)).toMatchObject({
      created: { last_days: 7 },
      last_call: { from_day: "2026-10-01", to_day: "2026-10-10" },
      direction: "outbound",
      test_calls: true,
    });
    expect(result.current.viewFilters(false).created).toEqual({
      from_day: shiftDay(today, -6),
      to_day: today,
    });
  });
});

