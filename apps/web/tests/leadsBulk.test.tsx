import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { Lead, Member } from "@/lib/api/leads";

import { problem, renderClientPage, type ApiCall } from "./harness";

/**
 * Bulk actions and inline edit — slice AE, the half of the leads floor slice Z deferred.
 *
 * The property under test is not "a checkbox toggles". It is the four things a bulk
 * action gets wrong, every one of which looks fine on a screen showing a tick:
 *
 * 1. **The screen does not say which set it acted on.** "Select all" meaning the visible
 *    PAGE and "select all" meaning the whole filtered QUERY are different actions over
 *    sets that differ by orders of magnitude once facets are in play, and the person
 *    cannot see the difference. Every assertion about copy below is about that sentence.
 * 2. **A partial failure renders as a success.** A batch where two of three rows could
 *    not move must NAME them; a tick over `changed: 1` is the defect.
 * 3. **Already-there reads as failure.** D-65: it is a success bucket of its own, and
 *    wording it as a fault teaches a client to report correct behaviour as a bug.
 * 4. **A failed inline edit reverts silently.** The select snaps back to the stored value
 *    and, without a sentence in the row, the only evidence is a value that did not stick.
 *
 * The refusal path (§52) is here too: a bulk request that 403s or 409s must show the
 * server's refusal, never a summary of a batch that did not run.
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
  engine: "bolna",
  extraction_fields: [],
};

const MEMBERS: Member[] = [{ id: "u1", name: "Priya Nair", role: "owner" }];

const COLUMNS = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
  { key: "status", label: "Stage", kind: "fixed", type: "enum" },
];

function lead(id: string, name: string, over: Record<string, unknown> = {}): Lead {
  return {
    id,
    name,
    phone_masked: `+9198••••${id.slice(-4).padStart(4, "0")}`,
    status: "new",
    source: "inbound_call",
    data: {},
    schema_version: 1,
    call_count: 1,
    is_repeat_caller: false,
    last_call_id: null,
    created_at: "2026-08-10T06:00:00Z",
    updated_at: "2026-08-13T04:30:00Z",
    assigned_to: null,
    assigned_to_name: null,
    ...over,
  };
}

const LEAD_A = lead("lead-1001", "Ramesh Kumar");
const LEAD_B = lead("lead-1002", "Sita Devi");

function leadList(items: Lead[], total: number) {
  return {
    items,
    columns: COLUMNS,
    available_columns: COLUMNS,
    dropped_column_keys: [],
    total,
    limit: 100,
    offset: 0,
    status_counts_matching_search: { new: total, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
  };
}

const FACETS = { facets: [], omitted_field_count: 0 };

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [AGENT],
    "/v1/members": MEMBERS,
    "/v1/leads?limit=100": leadList([LEAD_A, LEAD_B], 2),
    "/v1/leads/facets": FACETS,
    "/v1/leads/views": { items: [] },
    ...over,
  };
}

async function lastCallTo(calls: ApiCall[], prefix: string, method = "GET"): Promise<ApiCall> {
  return vi.waitFor(() => {
    const found = [...calls]
      .reverse()
      .find((c) => c.path.startsWith(prefix) && c.method === method);
    if (!found) throw new Error(`nothing was ${method}ed to ${prefix}`);
    return found;
  });
}

/** Tick a row by the lead's own name — the label the screen actually gives the box. */
async function tick(name: string) {
  fireEvent.click(await screen.findByLabelText(`Select ${name}`));
}

/** Walk the bar's two-step control: review, then apply. */
async function review() {
  fireEvent.click(await screen.findByRole("button", { name: /Review this change/ }));
}

describe("selection scope is never ambiguous", () => {
  it("says the ticked rows are ON THIS PAGE, with the count", async () => {
    await renderClientPage(<LeadsPage />, routes());
    await tick("Ramesh Kumar");
    expect(await screen.findByText(/1 lead on this page is selected/)).toBeTruthy();
  });

  it("offers the whole filtered query only when rows are off-screen, and names both counts", async () => {
    // 2 rows on the page, 140 matching the filters — the Gmail escape hatch's premise.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": leadList([LEAD_A, LEAD_B], 140) }),
    );
    fireEvent.click(await screen.findByLabelText("Select all leads on this page"));

    expect(await screen.findByText(/All 2 leads on this page are selected/)).toBeTruthy();
    const extend = screen.getByRole("button", {
      name: /Select all 140 leads matching these filters/,
    });

    fireEvent.click(extend);
    // The scope sentence CHANGES, and it names the rows the person cannot see. That gap
    // is the whole risk of this control and it is stated rather than implied.
    expect(
      await screen.findByText(/All 140 leads matching these filters are selected/),
    ).toBeTruthy();
    expect(container.textContent).toContain("138 not on this page");
  });

  it("does not offer the whole query when the page already holds every matching lead", async () => {
    await renderClientPage(<LeadsPage />, routes());
    fireEvent.click(await screen.findByLabelText("Select all leads on this page"));
    // The bar still names the scope and the count; what is absent is the escape hatch,
    // because there is nothing off-screen for it to reach.
    await screen.findByText(/2 leads on this page are selected/);
    expect(screen.queryByRole("button", { name: /matching these filters/ })).toBeNull();
  });

  it("sends scope 'ids' with exactly the ticked ids", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes(),
      "POST /v1/leads/bulk": {
        action: "status",
        scope: "ids",
        requested: 1,
        changed: 1,
        unchanged: 0,
        failures: [],
      },
    });

    await tick("Ramesh Kumar");
    await review();
    fireEvent.click(await screen.findByRole("button", { name: /Apply to 1/ }));

    const posted = await lastCallTo(calls, "/v1/leads/bulk", "POST");
    expect(JSON.parse(posted.body ?? "{}")).toEqual({
      scope: "ids",
      ids: ["lead-1001"],
      action: "status",
      status: "contacted",
    });
  });

  it("sends scope 'filter' with the lens and the count the person confirmed", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes({
        "/v1/leads?status=hot&limit=100": leadList([LEAD_A, LEAD_B], 140),
        "/v1/leads/facets?status=hot": FACETS,
      }),
      "POST /v1/leads/bulk?status=hot": {
        action: "status",
        scope: "filter",
        requested: 140,
        changed: 140,
        unchanged: 0,
        failures: [],
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "hot" }));
    fireEvent.click(await screen.findByLabelText("Select all leads on this page"));
    fireEvent.click(
      await screen.findByRole("button", { name: /Select all 140 leads matching these filters/ }),
    );
    await review();

    // Above the threshold the confirmation is TYPED, and what must be typed is the COUNT
    // — a fixed word proves the button was meant, and the risk here is the number.
    const apply = screen.getByRole("button", { name: /Apply to 140/ }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Type 140 to confirm"), {
      target: { value: "140" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply to 140/ }));

    const posted = await lastCallTo(calls, "/v1/leads/bulk", "POST");
    // THE LENS TRAVELS IN THE QUERY STRING, exactly as the table and the export send it.
    expect(posted.path).toBe("/v1/leads/bulk?status=hot");
    expect(JSON.parse(posted.body ?? "{}")).toEqual({
      scope: "filter",
      action: "status",
      status: "contacted",
      expected_count: 140,
    });
  });

  it("clears the selection when the filter moves", async () => {
    // The screen's half of a contract whose other half is on the server: an id-scoped
    // action is NOT re-intersected with the filter, so a selection must not outlive the
    // filter it was made under.
    await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?status=won&limit=100": leadList([LEAD_A], 1),
        "/v1/leads/facets?status=won": FACETS,
      }),
    );
    await tick("Ramesh Kumar");
    await screen.findByText(/1 lead on this page is selected/);

    fireEvent.click(screen.getByRole("button", { name: "won" }));
    expect(await vi.waitFor(() => screen.queryByText(/is selected/))).toBeNull();
  });

  it("offers no selection at all to a read-only impersonating operator", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": { ...ME, impersonating: true } }),
    );
    await screen.findByText("Ramesh Kumar");
    expect(screen.queryByLabelText("Select all leads on this page")).toBeNull();
    expect(screen.queryByLabelText("Select Ramesh Kumar")).toBeNull();
  });
});

describe("the confirmation states the consequences before the click", () => {
  it("names the action, the count and the scope above the button", async () => {
    await renderClientPage(<LeadsPage />, routes());
    await tick("Ramesh Kumar");
    await review();

    const alert = await screen.findByText(/Set the stage to/);
    expect(alert.textContent).toContain("1 lead");
    expect(alert.textContent).toContain("you have ticked on this page");
    // The `unchanged` bucket is promised BEFORE the run, so "3 were already there" in the
    // result is not a surprise the client reads as a fault.
    expect(
      (await screen.findByText(/already at that stage/)).textContent,
    ).toContain("left alone");
  });

  it("takes no typed confirmation for a handful of rows", async () => {
    await renderClientPage(<LeadsPage />, routes());
    await tick("Ramesh Kumar");
    await review();
    expect(screen.queryByLabelText(/Type .* to confirm/)).toBeNull();
    expect((screen.getByRole("button", { name: /Apply to 1/ }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  it("refuses to arm on a typed count that is not the real one", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": leadList([LEAD_A, LEAD_B], 140) }),
    );
    fireEvent.click(await screen.findByLabelText("Select all leads on this page"));
    fireEvent.click(
      await screen.findByRole("button", { name: /Select all 140 leads matching these filters/ }),
    );
    await review();
    fireEvent.change(screen.getByLabelText("Type 140 to confirm"), { target: { value: "14" } });
    expect(
      (screen.getByRole("button", { name: /Apply to 140/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

describe("the result is the server's answer, and a partial failure reads as one", () => {
  it("names every lead it could not move, and does not tick over them", async () => {
    const { container } = await renderClientPage(<LeadsPage />, {
      ...routes(),
      "POST /v1/leads/bulk": {
        action: "status",
        scope: "ids",
        requested: 3,
        changed: 1,
        unchanged: 0,
        failures: [
          {
            lead_id: "lead-1002",
            rule: "not_found",
            reason: "This lead is no longer on this account, so it was left alone.",
          },
          {
            lead_id: "lead-9999",
            rule: "not_found",
            reason: "This lead is no longer on this account, so it was left alone.",
          },
        ],
      },
    });

    await tick("Ramesh Kumar");
    await review();
    fireEvent.click(await screen.findByRole("button", { name: /Apply to 1/ }));

    const summary = await screen.findByRole("status");
    // Every number is the SERVER's, including the ones the screen never asked for.
    expect(summary.textContent).toContain("1 lead changed");
    expect(summary.textContent).toContain("2 could not be changed");
    expect(summary.textContent).toContain("out of 3");
    // THE ROWS, BY NAME where we hold one and by id where we do not — a filter-scoped
    // batch can fail on a lead that is not on this page, and inventing a name for it
    // would be worse than a truncated id.
    const named = within(summary);
    expect(named.getByText("Sita Devi")).toBeTruthy();
    expect(named.getByText(/lead-999/)).toBeTruthy();
    expect(summary.textContent).toContain("no longer on this account");
    // The one thing this must never be: a success.
    expect(container.textContent).not.toContain("All 3 leads changed");
  });

  it("reports leads that were already there as a success, not a failure", async () => {
    await renderClientPage(<LeadsPage />, {
      ...routes(),
      "POST /v1/leads/bulk": {
        action: "status",
        scope: "ids",
        requested: 10,
        changed: 7,
        unchanged: 3,
        failures: [],
      },
    });

    await tick("Ramesh Kumar");
    await review();
    fireEvent.click(await screen.findByRole("button", { name: /Apply to 1/ }));

    const summary = await screen.findByRole("status");
    expect(summary.textContent).toContain("7 leads changed");
    expect(summary.textContent).toContain("3 leads were already there");
    expect(summary.textContent).not.toContain("could not be changed");
  });

  it("says which SCOPE the server ran over, not which one we asked for", async () => {
    await renderClientPage(<LeadsPage />, {
      ...routes(),
      "POST /v1/leads/bulk": {
        action: "status",
        scope: "filter",
        requested: 140,
        changed: 140,
        unchanged: 0,
        failures: [],
      },
    });

    await tick("Ramesh Kumar");
    await review();
    fireEvent.click(await screen.findByRole("button", { name: /Apply to 1/ }));

    expect((await screen.findByRole("status")).textContent).toContain(
      "out of 140 matching those filters",
    );
  });

  it("REFUSES rather than summarising a batch that never ran", async () => {
    // §52 at its sharpest: the screen must not describe an outcome it did not receive.
    await renderClientPage(<LeadsPage />, {
      ...routes(),
      "POST /v1/leads/bulk": problem(409, {
        type: "https://calevate.tech/problems/lead_bulk_set_moved",
        title: "Conflicting request",
        detail: "This now matches 141 leads rather than the 140 you confirmed, so nothing was changed.",
        kind: "conflict",
        remediation: "Check the table and run the action again.",
      }),
    });

    await tick("Ramesh Kumar");
    await review();
    fireEvent.click(await screen.findByRole("button", { name: /Apply to 1/ }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => a.textContent?.includes("nothing was changed"))).toBe(true);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("inline edit says so on the row when it fails", () => {
  it("puts the server's sentence in the row rather than reverting in silence", async () => {
    await renderClientPage(<LeadsPage />, {
      ...routes(),
      "PATCH /v1/leads/lead-1001": problem(422, {
        type: "https://calevate.tech/problems/lead_assignee_not_a_member",
        title: "Request rejected by a business rule",
        detail: "That person is not on this account's team, so this lead cannot be assigned to them.",
        kind: "business_rule",
      }),
    });

    fireEvent.change(await screen.findByLabelText("Status for Ramesh Kumar"), {
      target: { value: "hot" },
    });

    const alerts = await screen.findAllByRole("alert");
    const inRow = alerts.find((a) => a.textContent?.startsWith("Not saved"));
    expect(inRow, "the failed edit did not say so anywhere").toBeTruthy();
    expect(inRow?.textContent).toContain("not on this account's team");
    // The OTHER row is untouched: a failure that painted the whole table would be the
    // page-level notice this replaces.
    expect(
      alerts.filter((a) => a.textContent?.startsWith("Not saved")),
    ).toHaveLength(1);
  });

  it("clears the row's failure once that row saves", async () => {
    let fail = true;
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes(),
      // The harness matches one answer per route, so the retry is exercised by flipping
      // this flag through a getter the stub reads on each call.
      get "PATCH /v1/leads/lead-1001"() {
        if (fail) return problem(503, { title: "Service unavailable", detail: "Try again." });
        return LEAD_A;
      },
    });

    fireEvent.change(await screen.findByLabelText("Status for Ramesh Kumar"), {
      target: { value: "hot" },
    });
    await vi.waitFor(() => {
      expect(
        screen.getAllByRole("alert").some((a) => a.textContent?.startsWith("Not saved")),
      ).toBe(true);
    });

    fail = false;
    fireEvent.change(screen.getByLabelText("Status for Ramesh Kumar"), {
      target: { value: "won" },
    });
    await vi.waitFor(() => {
      expect(
        screen.queryAllByRole("alert").some((a) => a.textContent?.startsWith("Not saved")),
      ).toBe(false);
    });
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2);
  });

  it("edits the NAME inline, committing on Enter and cancelling on Escape", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes(),
      "PATCH /v1/leads/lead-1001": { ...LEAD_A, name: "Ramesh K" },
    });

    fireEvent.click(
      await screen.findByLabelText("Edit the name for the lead on +9198••••1001"),
    );
    const input = screen.getByLabelText("Name for the lead on +9198••••1001");

    // Escape restores the stored value and sends nothing.
    fireEvent.change(input, { target: { value: "Nonsense" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);

    fireEvent.click(screen.getByLabelText("Edit the name for the lead on +9198••••1001"));
    const again = screen.getByLabelText("Name for the lead on +9198••••1001");
    fireEvent.change(again, { target: { value: "Ramesh K" } });
    fireEvent.keyDown(again, { key: "Enter" });

    const posted = await lastCallTo(calls, "/v1/leads/lead-1001", "PATCH");
    expect(JSON.parse(posted.body ?? "{}")).toEqual({ name: "Ramesh K" });
  });

  it("commits on click-out and sends nothing when the name did not change", async () => {
    const { calls } = await renderClientPage(<LeadsPage />, {
      ...routes(),
      "PATCH /v1/leads/lead-1001": { ...LEAD_A, name: "Ramesh Gupta" },
    });

    fireEvent.click(
      await screen.findByLabelText("Edit the name for the lead on +9198••••1001"),
    );
    fireEvent.blur(screen.getByLabelText("Name for the lead on +9198••••1001"));
    // A cell clicked into and out of must not PATCH: the write bumps `updated_at`, which
    // is this table's sort key, so a no-op edit would re-order the client's screen.
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);

    fireEvent.click(screen.getByLabelText("Edit the name for the lead on +9198••••1001"));
    const input = screen.getByLabelText("Name for the lead on +9198••••1001");
    fireEvent.change(input, { target: { value: "Ramesh Gupta" } });
    fireEvent.blur(input);
    const posted = await lastCallTo(calls, "/v1/leads/lead-1001", "PATCH");
    expect(JSON.parse(posted.body ?? "{}")).toEqual({ name: "Ramesh Gupta" });
  });

  it("offers no name edit to a session that may not write", async () => {
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": { ...ME, permissions: ["leads:read"] } }),
    );
    await screen.findByText("Ramesh Kumar");
    expect(screen.queryByLabelText(/^Edit the name/)).toBeNull();
  });
});
