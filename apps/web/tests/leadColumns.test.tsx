import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { Lead } from "@/lib/api/leads";

import { problem, renderClientPage, type ApiCall } from "./harness";

/**
 * The Leads table's LENS: which rows, which columns, and whether the CSV agrees.
 *
 * The property worth testing here is not that a checkbox toggles. It is that ONE lens
 * reaches three places — the table, the facet counts and the export — because the file
 * is the only surface in this product carrying unmasked phone numbers, and a screen that
 * narrows the table while the file stays wide is how a client mails a supplier their
 * whole contact list. Every "sends the same thing" assertion below compares two query
 * strings the screen produced, which is the one place that defect is visible.
 *
 * The refusal paths are the other half (BUILD-LOG §52). A facet rail that could not load
 * must not render as "this agent captures nothing to filter on", and a saved-view picker
 * that could not load must not render as "you have no saved views" — both are statements
 * about the client's account manufactured from our own ignorance.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["leads:read", "leads:write", "leads:dispatch", "calls:read_raw"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const AGENT: Agent = {
  id: "agent-1",
  name: "Reception",
  published: true,
  status: "live",
  direction: "inbound",
  // Hard rule 5: an agent ALWAYS carries a non-null disclosure line. These fixtures had
  // none — `as unknown as Agent` is why nobody noticed.
  language_primary: "te-IN",
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  // D-163 split the bundled line into two notices with two switches. The fixture keeps
  // both ON, which is what a new agent is born with, and carries the server-composed
  // `opening_line` rather than joining the two sentences here — the screens read that
  // field, so a fixture that computed it would be testing its own arithmetic.
  ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  recording_notice_enabled: true,
  opening_line:
    "Namaskaram, this is an AI assistant calling for Sri Clinic. This call is being recorded.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  engine: "bolna",
  // D-440 widened `AgentOut`: an agent knows when it was retired (NULL until it is) and
  // how many lines it answers in parallel, which is the one honest per-agent deployment
  // fact the API carries. Both are REQUIRED on the wire, so a fixture without them is not
  // an agent this server can send.
  archived_at: null,
  inbound_number_count: 1,
  extraction_fields: [],
};

const COLUMNS = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
  { key: "budget_band", label: "Budget band", kind: "extraction", type: "enum" },
  { key: "updated_at", label: "Updated", kind: "fixed", type: "date" },
];

const LEAD: Lead = {
  id: "lead-a",
  name: "Ramesh Kumar",
  phone_e164: "+919876543210",
  status: "new",
  source: "inbound_call",
  data: { budget_band: "over_50l" },
  schema_version: 1,
  call_count: 1,
  is_repeat_caller: false,
  last_call_id: null,
  created_at: "2026-08-10T06:00:00Z",
  updated_at: "2026-08-13T04:30:00Z",
  assigned_to: null,
  assigned_to_name: null,
};

function leadList(over: Record<string, unknown> = {}) {
  return {
    items: [LEAD],
    columns: COLUMNS,
    available_columns: COLUMNS,
    dropped_column_keys: [],
    total: 1,
    limit: 100,
    offset: 0,
    status_counts_matching_search: { new: 1, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
    ...over,
  };
}

const FACETS = {
  facets: [
    {
      key: "budget_band",
      label: "Budget band",
      values: [
        { value: "over_50l", count: 3, declared: true },
        { value: "legacy_band", count: 1, declared: false },
      ],
    },
  ],
  omitted_field_count: 0,
};

const VIEW = {
  id: "view-1",
  name: "Hot this week",
  filters: { status: "hot", agent_id: null, assigned_to_me: false, fields: {} },
  columns: ["name", "budget_band"],
  stale_filter_keys: [],
  stale_column_keys: [],
  created_at: "2026-08-10T06:00:00Z",
  updated_at: "2026-08-10T06:00:00Z",
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/members": [],
    "POST /v1/leads/search": leadList(),
    "/v1/leads/facets": FACETS,
    "/v1/leads/views": { items: [] },
    ...over,
  };
}

/** The last request the screen made to `path`'s prefix — the seam these tests read. */
async function lastCallTo(calls: ApiCall[], prefix: string): Promise<ApiCall> {
  return vi.waitFor(() => {
    const found = [...calls].reverse().find((c) => c.path.startsWith(prefix));
    if (!found) throw new Error(`nothing was requested from ${prefix}`);
    return found;
  });
}

/**
 * The LENS a request carried, from wherever the route puts it.
 *
 * The list and the export take it in a BODY now, because it holds the search term and a
 * search term is matched against a phone number — a number in a request line is in
 * nginx's access log (hard rule 6, and the reason `POST /v1/dnc/check` has always been a
 * POST). The facet rail is the one leg still on a GET, so it is still read off the query
 * string. One helper, so the mirroring assertions below stay one comparison rather than
 * growing a second shape.
 */
async function lensSentTo(calls: ApiCall[], prefix: string): Promise<Record<string, unknown>> {
  const call = await lastCallTo(calls, prefix);
  if (call.body !== null) return JSON.parse(call.body) as Record<string, unknown>;
  const params = new URLSearchParams(call.path.split("?")[1] ?? "");
  const out: Record<string, unknown> = {};
  for (const [key, value] of params) {
    if (key === "f") ((out.f as string[] | undefined) ?? (out.f = [] as string[])).push(value);
    else out[key] = value;
  }
  return out;
}

describe("the column chooser reaches the table AND the file", () => {
  it("renders exactly the columns the server resolved, in its order", async () => {
    await renderClientPage(<LeadsPage />, routes());
    const headers = (await screen.findAllByRole("columnheader")).map((h) => h.textContent);
    // The leading "Select" is the bulk-selection column (slice AE), not a data column:
    // it is a CONTROL the screen owns, so it is not part of the server's resolved list
    // and it is deliberately absent from the CSV. The assertion still pins that the
    // DATA columns are the server's, in the server's order, which is what this test is
    // about — the mirroring between the table and the file.
    expect(headers).toEqual(["Select", "Name", "Phone", "Budget band", "Updated"]);
  });

  it("sends a column choice to the list and the identical one to the export", async () => {
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "POST /v1/leads/search": leadList({
          columns: COLUMNS.slice(0, 2),
        }),
      }),
    );

    // Untick the two columns that are not Name/Phone. The checkboxes carry the column's
    // own visible label — axe cannot see a placeholder, and neither can a person.
    fireEvent.click(await screen.findByLabelText("Budget band"));
    fireEvent.click(await screen.findByLabelText("Updated"));

    expect(await lensSentTo(calls, "/v1/leads/search")).toEqual({
      limit: 100,
      columns: "name,phone",
    });

    fireEvent.click(screen.getByRole("button", { name: /Export this view as CSV/ }));
    // THE MIRRORING, at the seam: the file's columns are the table's columns.
    expect(await lensSentTo(calls, "/v1/leads/export.csv")).toEqual({ columns: "name,phone" });
  });

  it("disables the chooser with a reason rather than showing an empty one when the list fails", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "POST /v1/leads/search": problem(503, { title: "Service unavailable" }) }),
    );
    const button = (await screen.findByRole("button", { name: /Columns/ })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("could not read this table's columns");
  });
});

describe("the facet rail is the extraction schema, and its filters reach the file", () => {
  it("offers the schema's enum values with the server's counts", async () => {
    await renderClientPage(<LeadsPage />, routes());
    // The group's label is a visible <legend>, not an aria-label.
    // TWO of them, and that is correct: the facet group's <legend> and the table's
    // column header both name the same extraction field. Asserted as "at least one"
    // rather than "exactly one", so the test does not forbid the table from showing a
    // column it is filtering on.
    expect((await screen.findAllByText("Budget band")).length).toBeGreaterThan(0);
    const chip = await screen.findByLabelText(/over_50l/);
    expect(chip).toBeTruthy();
    // A value the data holds and the capture list no longer declares is offered and
    // said to be retired, rather than being silently unfilterable.
    // `findByLabelText` returns the INPUT; the wording lives on the label around it.
    const retired = (await screen.findByText("legacy_band")).closest("label");
    expect(retired?.textContent).toContain("retired");
  });

  it("sends a chosen facet to the list, the counts and the export alike", async () => {
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "POST /v1/leads/search": leadList(),
        "/v1/leads/facets?f=budget_band%3Aover_50l": FACETS,
      }),
    );

    fireEvent.click(await screen.findByLabelText(/over_50l/));

    expect(await lensSentTo(calls, "/v1/leads/search")).toEqual({
      limit: 100,
      f: ["budget_band:over_50l"],
    });
    expect(await lensSentTo(calls, "/v1/leads/facets")).toEqual({ f: ["budget_band:over_50l"] });

    fireEvent.click(screen.getByRole("button", { name: /Export this view as CSV/ }));
    expect(await lensSentTo(calls, "/v1/leads/export.csv")).toEqual({
      f: ["budget_band:over_50l"],
    });
  });

  it("REFUSES rather than rendering an empty rail when the facets cannot be read", async () => {
    // "This agent captures nothing you can filter on" and "we could not read your
    // filters" are different sentences, and only one of them is ours to make up.
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads/facets": problem(503, { title: "Service unavailable" }) }),
    );
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes("Service unavailable"))).toBe(true);
    expect(screen.queryByText("Filter by what your agent captured")).toBeNull();
  });
});

describe("saved views", () => {
  it("applies a view's filters and columns to the table", async () => {
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads/views": { items: [VIEW] },
        "POST /v1/leads/search": leadList(),
        "/v1/leads/facets?status=hot": FACETS,
      }),
    );

    fireEvent.change(await screen.findByLabelText("Saved view"), { target: { value: "view-1" } });

    expect(await lensSentTo(calls, "/v1/leads/search")).toEqual({
      status: "hot",
      limit: 100,
      columns: "name,budget_band",
    });
  });

  it("saves the current lens under a name", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes({ "/v1/leads/views": { items: [] } }),
      "POST /v1/leads/views": VIEW,
    });

    fireEvent.click(await screen.findByRole("button", { name: /Save this view/ }));
    fireEvent.change(await screen.findByLabelText("Name this view"), {
      target: { value: "My leads" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const posted = await vi.waitFor(() => {
      const found = calls.find((c) => c.method === "POST" && c.path === "/v1/leads/views");
      if (!found) throw new Error("the view was never saved");
      return found;
    });
    expect(JSON.parse(posted.body ?? "{}")).toMatchObject({ name: "My leads" });
  });

  it("says what a view lost when the capture list moved under it", async () => {
    // The degradation, on screen. The server has already REMOVED the dead references
    // from what the view applies — a filter silently applied as nothing would widen the
    // set, and the export follows the same lens — so this is the sentence that makes the
    // removal visible instead of mysterious.
    await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads/views": {
          items: [{ ...VIEW, stale_filter_keys: ["budget_band"], stale_column_keys: [] }],
        },
        "POST /v1/leads/search": leadList(),
        "/v1/leads/facets?status=hot": FACETS,
      }),
    );

    fireEvent.change(await screen.findByLabelText("Saved view"), { target: { value: "view-1" } });
    expect(await screen.findByText(/no longer has/)).toBeTruthy();
  });

  it("REFUSES rather than saying 'you have no saved views' when the list fails", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads/views": problem(503, { title: "Service unavailable" }) }),
    );
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes("Service unavailable"))).toBe(true);
    expect(screen.queryByLabelText("Saved view")).toBeNull();
  });
});
