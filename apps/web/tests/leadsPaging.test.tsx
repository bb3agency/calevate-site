import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Me } from "@/lib/api/client";
import type { Lead, LeadList } from "@/lib/api/leads";

import { lensOf, renderClientPage, type ApiCall } from "./harness";
import { LEAD_FIELDS_CORE_ONLY } from "./fixtures/sharedReads";

/**
 * The leads table's PAGE is part of what the owner is looking at, and two things moved it
 * when they should not have:
 *
 * 1. The page outliving its rows. On the last page of "New", ticking every row and marking
 *    them Contacted takes them out of the filter; the re-read of that offset comes back
 *    empty while `total` still counts the people on page one, and the table said
 *    "No people match these filters" over a pager pointing at a page that no longer exists.
 * 2. Choosing a column sent the owner back to page one, because the column list sat in
 *    the key that resets the page. Columns change what is shown, never which rows.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:write", "leads:dispatch", "calls:read_raw"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const COLUMNS: LeadList["columns"] = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
];
const AVAILABLE: LeadList["columns"] = [...COLUMNS, { key: "source", label: "Source", kind: "fixed", type: "text" }];

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

/** The account's leads as the server would page them, `total` people in all. */
function serve(total: number) {
  return (call: ApiCall): LeadList => {
    const body = lensOf(call);
    const offset = Number(body.offset ?? 0);
    const items = Array.from({ length: Math.max(0, Math.min(100, total - offset)) }, (_, i) => lead(offset + i + 1));
    return {
      items,
      columns: COLUMNS,
      available_columns: AVAILABLE,
      dropped_column_keys: [],
      total,
      limit: 100,
      offset,
      status_counts_matching_search: { new: total, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
      semantic_truncated: false,
    };
  };
}

function routes(search: (call: ApiCall) => LeadList) {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": [{ id: "u1", name: "Priya Nair", role: "owner" }],
    "POST /v1/leads/search": search,
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    "/v1/lead-fields": LEAD_FIELDS_CORE_ONLY,
  };
}

function lastOffset(calls: ApiCall[]): number {
  const searches = calls.filter((c) => c.path === "/v1/leads/search" && c.method === "POST");
  return Number(lensOf(searches[searches.length - 1]).offset ?? 0);
}

describe("the leads page keeps the owner on a page that exists", () => {
  it("steps back to the last page when the rows on the page it was on are gone", async () => {
    let total = 130;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { calls } = await renderClientPage(<LeadsPage />, routes((call) => serve(total)(call)), "acme", client);

    fireEvent.click(await screen.findByRole("button", { name: "Page 2" }));
    expect(await screen.findByText("Person 130")).toBeTruthy();

    // The 30 on page two were marked Contacted and left the filter.
    total = 100;
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["leads", "acme"] });
    });

    await waitFor(() => expect(lastOffset(calls)).toBe(0));
    expect(await screen.findByText("Person 100")).toBeTruthy();
    expect(screen.queryByText("No people match these filters")).toBeNull();
    expect(screen.queryByText("Nobody here yet")).toBeNull();
  });

  it("stays on the same page when a column is added", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, routes(serve(250)));

    fireEvent.click(await screen.findByRole("button", { name: "Page 2" }));
    expect(await screen.findByText("Person 101")).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: /Choose columns/ }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Source" }));

    await waitFor(() => {
      const searches = calls.filter((c) => c.path === "/v1/leads/search" && c.method === "POST");
      expect(String(lensOf(searches[searches.length - 1]).columns)).toContain("source");
    });
    expect(lastOffset(calls)).toBe(100);
    expect(screen.getByRole("button", { name: "Page 2" }).getAttribute("aria-current")).toBe("page");
  });
});
