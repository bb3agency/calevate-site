import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClientFind } from "@/app/c/[slug]/ClientFind";
import LeadDetailPage from "@/app/c/[slug]/leads/[leadId]/page";
import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Me } from "@/lib/api/client";
import type { Lead, LeadList, LeadTimelineEvent } from "@/lib/api/leads";

import { lensOf, renderClientPage, type ApiCall } from "./harness";
import { LEAD_FIELDS_CORE_ONLY } from "./fixtures/sharedReads";

/**
 * W7.1 the desk, W7.2 team notes, W7.4 Find.
 *
 * The desk is one read per stage under the table's own lens, and a move is the table's own
 * PATCH. A note is a POST body and comes back on the history with Edit for its writer. Find
 * sends its term in a POST body, never in a URL, and shows a number by its last four digits.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:write", "calls:read"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Traders", slug: "acme", status: "active" },
};

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: "lead-a",
    name: "Ramesh Kumar",
    phone_e164: "+919876543210",
    status: "new",
    source: "inbound_call",
    status_set_by: "system",
    data: { need: "Two tonnes of cement" },
    schema_version: 1,
    call_count: 1,
    is_repeat_caller: false,
    last_call_id: null,
    created_at: "2026-11-20T06:00:00Z",
    updated_at: "2026-11-21T04:30:00Z",
    assigned_to: null,
    assigned_to_name: null,
    ...over,
  };
}

function list(items: Lead[], total = items.length): LeadList {
  return {
    items,
    columns: [{ key: "name", label: "Name", kind: "fixed", type: "text" }],
    available_columns: [
      { key: "name", label: "Name", kind: "fixed", type: "text" },
      { key: "need", label: "Looking for", kind: "extraction", type: "text" },
    ],
    dropped_column_keys: [],
    total,
    limit: 20,
    offset: 0,
    status_counts_matching_search: { new: total, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
    semantic_truncated: false,
  };
}

function leadsRoutes() {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": [{ id: "u1", name: "Priya Nair", role: "owner" }],
    "POST /v1/leads/search": (call: ApiCall) => (lensOf(call).status === "new" ? list([lead()], 31) : list([])),
    "PATCH /v1/leads/lead-a": lead({ status: "contacted" }),
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    "/v1/lead-fields": LEAD_FIELDS_CORE_ONLY,
  };
}

describe("the desk", () => {
  it("reads each stage, shows the card's want, and moves a card through the table's own write", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, leadsRoutes());
    fireEvent.click(await screen.findByRole("radio", { name: "Desk" }));

    const column = await screen.findByRole("region", { name: /by stage/ });
    await within(column).findByText("Ramesh Kumar");
    expect(column.textContent).toContain("Two tonnes of cement");
    expect(column.textContent).toContain("See all 31 in the table");

    const asked = calls.filter((c) => c.path === "/v1/leads/search").map((c) => lensOf(c).status);
    for (const stage of ["new", "contacted", "interested", "hot", "won", "lost"]) expect(asked).toContain(stage);

    fireEvent.change(screen.getByRole("combobox", { name: "Move Ramesh Kumar to another stage" }), {
      target: { value: "contacted" },
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === "/v1/leads/lead-a")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(JSON.parse(patch.body ?? "{}")).toEqual({ status: "contacted" });
  });
});

function noteEvent(over: Partial<LeadTimelineEvent> = {}): LeadTimelineEvent {
  return {
    id: "ev-n",
    type: "note",
    occurred_at: "2026-11-21T04:30:00Z",
    actor_kind: "member",
    actor_name: "Priya Nair",
    title: "Note",
    detail: null,
    call_id: null,
    moments: [],
    note: { id: "note-1", body: "Prefers a call after 6 pm.", version: 1, author_user_id: "u1", edited_at: null },
    ...over,
  };
}

function detailRoutes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [],
    "/v1/members": [{ id: "u1", name: "Priya Nair", role: "owner" }],
    "/v1/leads/lead-a": lead(),
    "/v1/leads/lead-a/timeline?limit=50": { items: [noteEvent()], total: 1, limit: 50, offset: 0 },
    "/v1/leads/lead-a/captured": { fields: [] },
    "POST /v1/leads/lead-a/notes": {
      id: "note-2",
      lead_id: "lead-a",
      call_id: null,
      author_user_id: "u1",
      author_name: "Priya Nair",
      body: "Sent the price list.",
      version: 1,
      created_at: "2026-11-21T05:00:00Z",
      edited_at: null,
    },
    "PATCH /v1/leads/lead-a/notes/note-1": {
      id: "note-1",
      lead_id: "lead-a",
      call_id: null,
      author_user_id: "u1",
      author_name: "Priya Nair",
      body: "Prefers a call after 7 pm.",
      version: 2,
      created_at: "2026-11-21T04:30:00Z",
      edited_at: "2026-11-21T06:00:00Z",
    },
    ...over,
  };
}

const detailPage = () => <LeadDetailPage params={Promise.resolve({ slug: "acme", leadId: "lead-a" })} />;

describe("team notes on a lead", () => {
  it("shows a note's words on the history and adds one in a request body", async () => {
    const { calls } = await renderClientPage(detailPage(), detailRoutes());
    await screen.findByText("Prefers a call after 6 pm.");

    fireEvent.change(screen.getByRole("textbox", { name: "A note for your team" }), {
      target: { value: "  Sent the price list.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/v1/leads/lead-a/notes")).toBe(true));
    const post = calls.find((c) => c.method === "POST" && c.path === "/v1/leads/lead-a/notes")!;
    expect(JSON.parse(post.body ?? "{}")).toEqual({ body: "Sent the price list." });
  });

  it("lets the writer edit with the version they read", async () => {
    const { calls } = await renderClientPage(detailPage(), detailRoutes());
    await screen.findByText("Prefers a call after 6 pm.");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Change this note" }), {
      target: { value: "Prefers a call after 7 pm." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(JSON.parse(patch.body ?? "{}")).toEqual({ body: "Prefers a call after 7 pm.", expected_version: 1 });
  });

  it("offers no Edit on a colleague's note to a member who is not the owner", async () => {
    await renderClientPage(
      detailPage(),
      detailRoutes({
        "/v1/me": { ...ME, role: "staff" },
        "/v1/leads/lead-a/timeline?limit=50": {
          items: [noteEvent({ note: { id: "note-1", body: "Theirs.", version: 1, author_user_id: "u9", edited_at: null } })],
          total: 1,
          limit: 50,
          offset: 0,
        },
      }),
    );
    await screen.findByText("Theirs.");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});

describe("Find", () => {
  const FOUND = {
    people: [{ lead_id: "lead-a", name: "శ్రీనివాస్", phone_last4: "7345", status: "hot" }],
    calls: [],
    screens: [{ route: "/c/{slug}/billing", name: "Credits & billing", group: "Account" }],
    calls_shown: true,
  };

  it("sends the term in a body, shows the last four digits, and offers Pip last", async () => {
    const { calls } = await renderClientPage(<ClientFind slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents": [],
      "/v1/campaigns": [],
      "/v1/inbound-lines": { lines: [] },
      "POST /v1/find": FOUND,
    });
    fireEvent.click(screen.getByRole("button", { name: "Find a person, call or screen" }));
    const box = await screen.findByRole("combobox", { name: "Find a person, call or screen" });
    fireEvent.change(box, { target: { value: "7345" } });

    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("శ్రీనివాస్");
    expect(dialog.textContent).toContain("ends 7345");
    expect(dialog.textContent).toContain("Ask Pip: 7345");

    const find = calls.find((c) => c.path === "/v1/find")!;
    expect(find.method).toBe("POST");
    expect(JSON.parse(find.body ?? "{}")).toEqual({ q: "7345" });
    expect(calls.every((c) => !c.url.includes("7345"))).toBe(true);
  });
});
