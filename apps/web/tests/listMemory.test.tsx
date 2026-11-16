import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CallsPage from "@/app/c/[slug]/calls/page";
import LeadsPage from "@/app/c/[slug]/leads/page";
import type { CallSummary, Me } from "@/lib/api/client";
import type { Lead, LeadList } from "@/lib/api/leads";

import { lensOf, renderClientPage, type ApiCall } from "./harness";
import { LEAD_FIELDS_CORE_ONLY } from "./fixtures/sharedReads";

/**
 * OPENING A ROW AND PRESSING BACK. The call log and the leads table unmount when a call
 * or a lead is opened, and used to come back on page one with every filter cleared: an
 * owner working down "Needs you" chose the filter again after every call. Each test
 * below unmounts the screen and mounts it again, which is what Back does.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read", "leads:write"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

function call(over: Partial<CallSummary> = {}): CallSummary {
  return {
    id: "c1",
    agent_id: "a1",
    campaign: null,
    inbound_line: null,
    agent_name: "Reception",
    direction: "inbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: "2026-08-13T04:30:00Z",
    duration_s: 92,
    outcome_tag: "call_back_booked",
    summary_state: "ready",
    test_call: false,
    sentiment: "positive",
    summary: "Caller asked for a Tuesday slot.",
    lead_id: null,
    ...over,
  };
}

const callsPage = () => <CallsPage params={Promise.resolve({ slug: "acme" })} />;

function callRoutes() {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/calls/views": { items: [] }, "/v1/campaigns": [], "/v1/inbound-lines": { lines: [] },
    "/v1/calls?limit=100": [call()],
    "/v1/calls?outcome=needs_you&limit=100": [call({ id: "c2", outcome_tag: "needs_you" })],
    "/v1/calls?status=no_answer&limit=100": [],
  };
}

const lastCallsPath = (calls: ApiCall[]) => calls.filter((c) => c.path.startsWith("/v1/calls?")).at(-1)?.path;

describe("the call log comes back as it was left", () => {
  it("keeps the chosen filter after a call is opened and Back is pressed", async () => {
    const first = await renderClientPage(callsPage(), callRoutes());
    fireEvent.click(await screen.findByRole("button", { name: "Needs you" }));
    await waitFor(() => expect(lastCallsPath(first.calls)).toBe("/v1/calls?outcome=needs_you&limit=100"));
    first.unmount();

    const back = await renderClientPage(callsPage(), callRoutes());
    await waitFor(() => expect(lastCallsPath(back.calls)).toBe("/v1/calls?outcome=needs_you&limit=100"));
    expect(back.calls.some((c) => c.path === "/v1/calls?limit=100")).toBe(false);
    expect(screen.getByRole("button", { name: "Needs you" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("opens a link's own filter alone, not the one left behind", async () => {
    const first = await renderClientPage(callsPage(), callRoutes());
    fireEvent.click(await screen.findByRole("button", { name: "Needs you" }));
    await waitFor(() => expect(lastCallsPath(first.calls)).toBe("/v1/calls?outcome=needs_you&limit=100"));
    first.unmount();

    window.history.replaceState(null, "", "/c/acme/calls?status=no_answer");
    const linked = await renderClientPage(callsPage(), callRoutes());
    await waitFor(() => expect(lastCallsPath(linked.calls)).toBe("/v1/calls?status=no_answer&limit=100"));
    expect(linked.calls.some((c) => c.path.includes("outcome=needs_you"))).toBe(false);
  });
});

describe("the call log opened from the home screen's missed calls", () => {
  it("lists that IST day's calls without test calls, as the count did, and says so in chips", async () => {
    window.history.replaceState(null, "", "/c/acme/calls?status=failed&day=2026-08-13&test_calls=false");
    const path =
      "/v1/calls?status=failed&since=2026-08-13T00%3A00%3A00%2B05%3A30&until=2026-08-14T00%3A00%3A00%2B05%3A30&test_calls=false&limit=100";
    const { calls } = await renderClientPage(callsPage(), { ...callRoutes(), [path]: [call({ status: "failed" })] });
    await waitFor(() => expect(lastCallsPath(calls)).toBe(path));
    expect(await screen.findByRole("button", { name: /Remove the filter: 13 Aug/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove the filter: Test calls left out" })).toBeTruthy();
  });
});

const COLUMNS: LeadList["columns"] = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
];

function lead(n: number): Lead {
  return {
    id: `lead-${n}`,
    name: `Person ${n}`,
    phone_e164: `+9198480${String(n).padStart(5, "0")}`,
    status: "new",
    source: "inbound_call",
    status_set_by: "system",
    data: {},
    schema_version: 1,
    call_count: 1,
    is_repeat_caller: false,
    last_call_id: null,
    created_at: "2026-08-10T06:00:00Z",
    updated_at: "2026-08-13T04:30:00Z",
    assigned_to: null,
    assigned_to_name: null,
  };
}

function leadRoutes() {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": [{ id: "u1", name: "Priya Nair", role: "owner" }],
    "POST /v1/leads/search": (c: ApiCall): LeadList => {
      const offset = Number(lensOf(c).offset ?? 0);
      return {
        items: Array.from({ length: Math.min(100, 250 - offset) }, (_, i) => lead(offset + i + 1)),
        columns: COLUMNS,
        available_columns: COLUMNS,
        dropped_column_keys: [],
        total: 250,
        limit: 100,
        offset,
        status_counts_matching_search: { new: 250, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
        semantic_truncated: false,
      };
    },
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    "/v1/lead-fields": LEAD_FIELDS_CORE_ONLY,
  };
}

const searches = (calls: ApiCall[]) => calls.filter((c) => c.path === "/v1/leads/search" && c.method === "POST");

describe("the leads table comes back as it was left", () => {
  it("returns to the page and stage a lead was opened from", async () => {
    const first = await renderClientPage(<LeadsPage />, leadRoutes());
    fireEvent.click(await screen.findByRole("button", { name: "Page 3" }));
    expect(await screen.findByText("Person 201")).toBeTruthy();
    first.unmount();

    const back = await renderClientPage(<LeadsPage />, leadRoutes());
    expect(await screen.findByText("Person 201")).toBeTruthy();
    // Page three is the first thing asked for, not page one and then page three.
    expect(lensOf(searches(back.calls)[0]).offset).toBe(200);
  });

  it("does not keep what was typed in the search box", async () => {
    const first = await renderClientPage(<LeadsPage />, leadRoutes());
    fireEvent.change(await screen.findByLabelText("Search leads"), { target: { value: "98480" } });
    await waitFor(() => expect(lensOf(searches(first.calls).at(-1)!).search).toBe("98480"));
    first.unmount();
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain("98480");

    const back = await renderClientPage(<LeadsPage />, leadRoutes());
    await screen.findByText("Person 1");
    expect(searches(back.calls).some((c) => lensOf(c).search !== undefined)).toBe(false);
  });
});
