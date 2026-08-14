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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
} as unknown as Me;

const AGENT: Agent = {
  id: "agent-1",
  name: "Reception",
  published: true,
  status: "live",
  direction: "inbound",
} as unknown as Agent;

const COLUMNS = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
  { key: "budget_band", label: "Budget band", kind: "extraction", type: "enum" },
  { key: "updated_at", label: "Updated", kind: "fixed", type: "date" },
];

const LEAD = {
  id: "lead-a",
  name: "Ramesh Kumar",
  phone_masked: "+9198••••3210",
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
} as unknown as Lead;

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
    "/v1/leads?limit=100": leadList(),
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

describe("the column chooser reaches the table AND the file", () => {
  it("renders exactly the columns the server resolved, in its order", async () => {
    await renderClientPage(<LeadsPage />, routes());
    const headers = (await screen.findAllByRole("columnheader")).map((h) => h.textContent);
    expect(headers).toEqual(["Name", "Phone", "Budget band", "Updated"]);
  });

  it("sends a column choice to the list and the identical one to the export", async () => {
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100&columns=name%2Cphone": leadList({
          columns: COLUMNS.slice(0, 2),
        }),
      }),
    );

    // Untick the two columns that are not Name/Phone. The checkboxes carry the column's
    // own visible label — axe cannot see a placeholder, and neither can a person.
    fireEvent.click(await screen.findByLabelText("Budget band"));
    fireEvent.click(await screen.findByLabelText("Updated"));

    const listCall = await lastCallTo(calls, "/v1/leads?");
    expect(listCall.path).toBe("/v1/leads?limit=100&columns=name%2Cphone");

    fireEvent.click(screen.getByRole("button", { name: /Export this view as CSV/ }));
    const exportCall = await lastCallTo(calls, "/v1/leads/export.csv");
    // THE MIRRORING, at the seam: the file's columns are the table's columns.
    expect(exportCall.path).toBe("/v1/leads/export.csv?columns=name%2Cphone");
  });

  it("disables the chooser with a reason rather than showing an empty one when the list fails", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": problem(503, { title: "Service unavailable" }) }),
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
        "/v1/leads?limit=100&f=budget_band%3Aover_50l": leadList(),
        "/v1/leads/facets?f=budget_band%3Aover_50l": FACETS,
      }),
    );

    fireEvent.click(await screen.findByLabelText(/over_50l/));

    expect((await lastCallTo(calls, "/v1/leads?")).path).toBe(
      "/v1/leads?limit=100&f=budget_band%3Aover_50l",
    );
    expect((await lastCallTo(calls, "/v1/leads/facets")).path).toBe(
      "/v1/leads/facets?f=budget_band%3Aover_50l",
    );

    fireEvent.click(screen.getByRole("button", { name: /Export this view as CSV/ }));
    expect((await lastCallTo(calls, "/v1/leads/export.csv")).path).toBe(
      "/v1/leads/export.csv?f=budget_band%3Aover_50l",
    );
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
        "/v1/leads?status=hot&limit=100&columns=name%2Cbudget_band": leadList(),
        "/v1/leads/facets?status=hot": FACETS,
      }),
    );

    fireEvent.change(await screen.findByLabelText("Saved view"), { target: { value: "view-1" } });

    expect((await lastCallTo(calls, "/v1/leads?")).path).toBe(
      "/v1/leads?status=hot&limit=100&columns=name%2Cbudget_band",
    );
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
        "/v1/leads?status=hot&limit=100&columns=name%2Cbudget_band": leadList(),
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
