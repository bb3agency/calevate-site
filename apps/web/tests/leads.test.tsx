import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Agent } from "@/lib/api/agents";
import type { CallLeadResult, Me } from "@/lib/api/client";
import type { Lead, LeadList, Member } from "@/lib/api/leads";

import { expectTextCount, problem, renderClientPage } from "./harness";

/**
 * The leads table — the client's own customer list, and the screen where a wrong number
 * is not a cosmetic defect but a claim about their business.
 *
 * Four things can be wrong here, in falling order of what they cost:
 *
 * 1. **A number nobody sent.** The stage badges used to be counted off the LOADED PAGE
 *    (`items.filter(...)`), which is capped at 100 and already narrowed by the status
 *    chip — so filtering to "hot" told a client "new 0 · contacted 0 · won 0" about
 *    stages they demonstrably had leads in, and the export warning printed the filtered
 *    `total` beside the words "every lead in the account". `status_counts_matching_search`
 *    is the server's answer to exactly this (crm/schemas.py), and these tests fail if the
 *    screen ever goes back to counting rows it happens to be holding.
 * 2. **A confident empty state over a failed request.** The board painted six "No leads"
 *    columns when the list request 503'd. "Your pipeline is empty" and "we could not read
 *    your pipeline" are different sentences and only one of them was true.
 * 3. **A raw phone number.** `LeadOut` carries `phone_masked` and nothing else (hard
 *    rule 6); the number planted below appears in no payload this screen receives, so
 *    every "must not appear" assertion is load-bearing.
 * 4. **A compliance verdict on the wrong row.** D-21's dispatch answer is per-lead state
 *    for a stated reason — `callLead.data` is one slot, so a shared verdict would move
 *    the first lead's refusal onto the second lead the client calls. That is the failure
 *    the page comment predicts, and the test below reproduces the exact sequence.
 */

/** A full E.164 number that appears in NO payload here — if it renders, we put it there. */
const RAW_PHONE = "+919876543210";
const MASKED_A = "+9198••••3210";
const MASKED_B = "+9199••••7788";

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  // An OWNER, which is the only client role holding `calls:read_raw` — the
  // permission the CSV export route requires (core/rbac.py).
  permissions: ["leads:read", "leads:write", "leads:dispatch", "calls:read_raw"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/** Published, live and able to dial out — the three things `canDial` asks for. */
const DIALER: Agent = {
  id: "agent-1",
  name: "Follow-up agent",
  published: true,
  status: "live",
  direction: "outbound",
  // Hard rule 5: an agent ALWAYS carries a non-null disclosure line. These fixtures had
  // none — `as unknown as Agent` is why nobody noticed.
  language_primary: "te-IN",
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  engine: "bolna",
  extraction_fields: [],
};

/**
 * The account's team, as `/v1/members` sends it: ids and display names, NO email
 * (tenancy/routes.py refuses to declare one — `email` is in the redaction guardrail's
 * `RAW_PII_FIELDS`). `PRIYA` is `ME`, so "Assigned to me" has a real id to send.
 */
const PRIYA: Member = { id: "u1", name: "Priya Nair", role: "owner" };
const KIRAN: Member = { id: "u2", name: "Kiran Babu", role: "staff" };
const MEMBERS: Member[] = [PRIYA, KIRAN];

/**
 * The four fixed columns this suite's assertions read: the name link, the masked phone,
 * the status select and the owner picker. `crm.columns` is the server's registry; these
 * are its keys and labels.
 */
const DEFAULT_COLUMNS: LeadList["columns"] = [
  { key: "name", label: "Name", kind: "fixed", type: "text" },
  { key: "phone", label: "Phone", kind: "fixed", type: "text" },
  { key: "status", label: "Status", kind: "fixed", type: "enum" },
  { key: "owner", label: "Owner", kind: "fixed", type: "text" },
];

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: "lead-a",
    name: "Ramesh Kumar",
    phone_masked: MASKED_A,
    status: "new",
    source: "call",
    data: {},
    schema_version: 1,
    call_count: 2,
    is_repeat_caller: false,
    last_call_id: null,
    created_at: "2026-08-10T06:00:00Z",
    updated_at: "2026-08-13T04:30:00Z",
    assigned_to: null,
    assigned_to_name: null,
    ...over,
  };
}

/**
 * A page of leads, with the two counts kept INDEPENDENT of the rows on purpose.
 *
 * The whole point of the fix under test is that `status_counts_matching_search` is not
 * derivable from `items` — it is the server's view of the stage, over a scope the page
 * does not have. A fixture that made them agree could not tell the two apart.
 */
function leadList(items: Lead[], over: Partial<LeadList> = {}): LeadList {
  return {
    items,
    // The server's RESOLVED column list, which is also the CSV's header for the same
    // query string (`crm.columns`). Kept minimal here — the columns a given test needs —
    // because this suite is about the numbers and the refusals, and `leadColumns.test.tsx`
    // is where the chooser and the mirroring are exercised.
    columns: DEFAULT_COLUMNS,
    available_columns: DEFAULT_COLUMNS,
    dropped_column_keys: [],
    total: items.length,
    limit: 100,
    offset: 0,
    status_counts_matching_search: { new: 0, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
    ...over,
  };
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [DIALER],
    "/v1/members": MEMBERS,
    "/v1/leads?limit=100": leadList([]),
    // The facet rail and the saved-view picker are part of this screen now. An unrouted
    // request THROWS in this harness rather than 404ing, which is the point: a screen
    // that quietly grew a call nobody expected should say so.
    "/v1/leads/facets": { facets: [], omitted_field_count: 0 },
    "/v1/leads/views": { items: [] },
    ...over,
  };
}

const BLOCKED: CallLeadResult = {
  status: "blocked",
  blocked_reason: "This number is on your do-not-call list.",
  blocked_rule: "dnc_tenant",
  call_handle: null,
};

const QUEUED: CallLeadResult = {
  status: "queued",
  blocked_reason: null,
  blocked_rule: null,
  call_handle: "call-1",
};

/**
 * The export button is gated on the permission the ROUTE requires, not on the one the
 * list requires. `/v1/leads/export.csv` is the only place a client's contact list
 * leaves us with full phone numbers, so it demands `calls:read_raw` — which `staff`
 * does not hold. Rendering it enabled for everyone turned a deliberate restriction
 * into what looks like a broken button.
 */
describe("the CSV export offers itself only to a session that may use it", () => {
  it("disables the button for a role without calls:read_raw", async () => {
    const staff = { ...ME, role: "staff", permissions: ["leads:read", "leads:write"] };
    await renderClientPage(<LeadsPage />, routes({ "/v1/me": staff }));

    const button = (await screen.findByRole("button", {
      name: /Export this view as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("account owner");
  });

  it("enables it for a session the server would accept", async () => {
    await renderClientPage(<LeadsPage />, routes());
    const button = (await screen.findByRole("button", {
      name: /Export this view as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it("says we could not CHECK — not that they are not allowed — when /v1/me fails", async () => {
    // BUILD-LOG §52 on the smallest possible surface. The gate used to be
    // `me.data?.permissions?.includes("calls:read_raw") ?? false`, and `me.data` is
    // undefined on a FAILED read just as it is on a pending one — so an owner whose
    // `/v1/me` 503'd was shown a disabled button reading "limited to the account
    // owner": a refusal we never received, stated about a permission they hold.
    await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": problem(503, { title: "Service unavailable" }) }),
    );

    const button = (await screen.findByRole("button", {
      name: /Export this view as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("could not check");
    expect(button.title).not.toContain("account owner");
  });
});

describe("what the screen says when it could not read the leads", () => {
  it("renders the refusal and no rows, in the list view", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your leads.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // "No leads yet" is a statement about the business. We do not know it — we could not
    // even read the list — so it must not be on screen next to the notice saying so.
    expect(container.textContent).not.toContain("No leads yet");
    expect(container.textContent).not.toContain("Showing");
    expect(container.textContent).not.toContain("by stage");
  });

  it("paints no empty pipeline in the board view either", async () => {
    // The regression this pins: the board had no failure branch, so a 503 rendered six
    // columns each reading "No leads" over a zero — a complete, confident, invented
    // pipeline drawn from a request that never landed.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": problem(503, { title: "Service unavailable" }) }),
    );

    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: /Board/ }));

    expectTextCount(container, "No leads", 0);
    expect(container.textContent).not.toContain("not on this page");
  });
});

describe("the number on the row", () => {
  it("renders phone_masked and never a raw number, in the DOM or in a URL", async () => {
    const { container, calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([lead()], {
          status_counts_matching_search: { new: 1, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
        }),
      }),
    );

    expect(await screen.findByText(MASKED_A)).toBeTruthy();
    expect(container.textContent).not.toContain(RAW_PHONE);
    // Not merely "the raw string is absent": the ten digits in sequence are what would
    // identify the person, and a partial leak is still a leak.
    expect(container.textContent).not.toContain("9876543210");
    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries a raw number`).not.toContain(
        "9876543210",
      );
    }
  });

  it("says a lead has no name rather than inventing one", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": leadList([lead({ name: null })]) }),
    );

    await screen.findByText(MASKED_A);
    expect(container.textContent).toContain("No name");
    // The masked number is the identifier for a nameless lead; nothing else stands in.
    expect(container.textContent).not.toContain("Unknown caller");
  });
});

describe("the D-21 dispatch verdict, per lead", () => {
  const TWO_LEADS = leadList([
    lead({ id: "lead-a", name: "Ramesh Kumar", phone_masked: MASKED_A }),
    lead({ id: "lead-b", name: "Priya Nair", phone_masked: MASKED_B }),
  ]);

  function row(text: string): HTMLElement {
    const cell = screen.getByText(text);
    const tr = cell.closest("tr");
    expect(tr, `no row for ${text}`).not.toBeNull();
    return tr as HTMLElement;
  }

  it("keeps a refusal on the lead it was given for when a second lead is called", async () => {
    // The exact sequence the page comment predicts. `callLead.data` is a single slot, so
    // a verdict read off the mutation would move Ramesh's compliance refusal onto Priya
    // the moment Priya is called — a client would then see a do-not-call warning against
    // a number that is not on the list, and dial the one that is.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": TWO_LEADS,
        "/v1/leads/lead-a/call": BLOCKED,
        "/v1/leads/lead-b/call": QUEUED,
      }),
    );

    const buttons = await screen.findAllByRole("button", { name: /Call with AI/ });
    expect(buttons).toHaveLength(2);

    fireEvent.click(buttons[0]);
    // ONE lead was called, so one verdict may exist. A shared slot puts it on both rows
    // here, before the second click has even happened.
    const firstVerdict = await screen.findAllByText(/do-not-call list/);
    expect(firstVerdict, "one call placed, one verdict on screen").toHaveLength(1);

    // Priya's row is still callable, and calling her must not disturb Ramesh's answer.
    fireEvent.click(screen.getByRole("button", { name: /Call with AI/ }));
    await screen.findByText("Calling now");

    expect(row(MASKED_A).textContent).toContain("This number is on your do-not-call list.");
    expect(row(MASKED_A).textContent).not.toContain("Calling now");
    expect(row(MASKED_B).textContent).toContain("Calling now");
    expect(row(MASKED_B).textContent).not.toContain("do-not-call");
    // One refusal was issued, so exactly one may be on screen.
    expectTextCount(container, "This number is on your do-not-call list.", 1);
  });

  it("shows a blocked dispatch as the gate's decision, not as a malfunction", async () => {
    // `POST /v1/leads/{id}/call` answers 200 with `status: "blocked"`. Rendering that
    // through ProblemNotice would tell a client their compliance rules are our bug; and
    // leaving the button enabled would read as "nothing happened", so they press again.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([lead()]),
        "/v1/leads/lead-a/call": BLOCKED,
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Call with AI/ }));

    expect(await screen.findByText(/do-not-call list/)).toBeTruthy();
    // The rule is named beside the reason: "dnc_tenant" is what an operator needs to
    // find the row, and the client needs to know which check refused.
    expect(container.textContent).toContain("dnc_tenant");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: /Call with AI/ })).toBeNull();
  });
});

describe("the counts come from the server or are not shown", () => {
  /** Twenty-two leads in the account, two of them hot — numbers `items` cannot produce. */
  const HOT_PAGE = leadList(
    [
      lead({ status: "hot" }),
      lead({ id: "lead-b", name: "Priya Nair", phone_masked: MASKED_B, status: "hot" }),
    ],
    {
      total: 2,
      status_counts_matching_search: {
        new: 12,
        contacted: 3,
        interested: 4,
        hot: 2,
        won: 1,
        lost: 0,
      },
    },
  );

  async function filterToHot() {
    const rendered = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([]),
        "/v1/leads?status=hot&limit=100": HOT_PAGE,
        // The facet rail follows the same status chip, because it describes the same
        // table — one query string, three surfaces (`lib/api/leads.ts::lensQuery`).
        "/v1/leads/facets?status=hot": { facets: [], omitted_field_count: 0 },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "hot" }));
    return rendered;
  }

  it("renders the server's stage counts, not a tally of the rows it happens to hold", async () => {
    const { calls } = await filterToHot();

    // The chips filter SERVER-side — that is the behaviour the counts have to survive.
    // Awaited for the reason the search case is: a positive assertion about a REQUEST
    // cannot be read synchronously off a list the request may not have reached yet.
    await vi.waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/leads?status=hot&limit=100")).toBe(true);
    });

    const tally = (await screen.findByText(/by stage/)).parentElement;

    // Pre-fix, every stage but `hot` was counted over a page the server had already
    // narrowed to `hot`, so this row read "new 0 · contacted 0 · interested 0 · won 0".
    expect(tally?.textContent).toContain("new12");
    expect(tally?.textContent).toContain("contacted3");
    expect(tally?.textContent).toContain("interested4");
    expect(tally?.textContent).not.toContain("new0");
    expect(tally?.textContent).not.toContain("contacted0");
    // …while the denominator stays the filtered one, and says which filter it obeyed.
    expect(tally?.textContent).toContain("Showing 2 of 2 hot leads");
  });

  it("names the number of leads the CSV will actually hold", async () => {
    const { container } = await filterToHot();

    await screen.findByText(/by stage/);
    // **This assertion is the inverse of the one it replaces.** The export used to
    // ignore the status chip, so the sentence had to name the WHOLE account (22) and
    // warn that the file was wider than the table. `/v1/leads/export.csv` now takes the
    // same lens as the list, so the file holds the 2 hot leads on screen and the copy
    // says so. A sentence claiming otherwise would teach a client to distrust a control
    // that works — the more dangerous of the two wrong sentences.
    expect(container.textContent).toContain("The CSV export contains these 2 leads");
    expect(container.textContent).not.toContain("the export ignores this filter");
    expect(container.textContent).not.toContain("every lead in the account");
  });

  it("sends the SAME filters to the export that it sent to the list", async () => {
    // The mirroring, at the seam where it can break: two query strings, compared. A
    // screen that narrowed the table and downloaded the account is the defect this
    // whole slice exists to close, and it is invisible in any assertion about copy.
    const { calls } = await filterToHot();
    await screen.findByText(/by stage/);

    fireEvent.click(screen.getByRole("button", { name: /Export this view as CSV/ }));
    const exportCall = await vi.waitFor(() => {
      const found = calls.find((c) => c.path.startsWith("/v1/leads/export.csv"));
      if (!found) throw new Error("the export was never requested");
      return found;
    });
    expect(exportCall.path).toBe("/v1/leads/export.csv?status=hot");
  });

  it("names no account total while a search is on, because the response holds none", async () => {
    // The other half of the same fix. `status_counts_matching_search` follows the SEARCH
    // (crm/service.py), so once the box has text nothing in the response adds up to the
    // account — and the sentence beside Export is about the FILTERED set anyway now.
    const { container, calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?search=ram&limit=100": leadList([lead()], {
          total: 1,
          status_counts_matching_search: {
            new: 1,
            contacted: 0,
            interested: 0,
            hot: 0,
            won: 0,
            lost: 0,
          },
        }),
        "/v1/leads/facets?search=ram": { facets: [], omitted_field_count: 0 },
      }),
    );

    fireEvent.change(screen.getByLabelText("Search leads"), { target: { value: "ram" } });
    // The box is debounced by 300ms, so this also asserts the debounce still fires — and
    // that the search is a SERVER-side filter rather than a slice of a capped page.
    // WAIT FOR THE REQUEST, not for a sentence that renders near it. This awaited the
    // sentence and then read `calls` SYNCHRONOUSLY, which is a race, and CI lost it:
    // TanStack keeps the previous page's data, so "matching your search" can render off
    // the PRE-search response while the 300ms debounce has not yet fired. Probed both
    // ways on this machine — the assertion sits exactly on the boundary, which is why it
    // passed here and failed there. `adminImpersonationGrant.test.tsx` documents the
    // idiom: "these tests assert on the REQUESTS, so the wait has to be explicit or they
    // pass by inspecting an empty list."
    await vi.waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/leads?search=ram&limit=100")).toBe(true);
    });
    await screen.findByText(/matching your search/);

    // Awaited rather than read off `container` synchronously: the searched page is a
    // second request, and the sentence is about ITS total.
    await screen.findByText(/The CSV export contains this 1 lead/);
    expect(container.textContent).not.toContain("every lead in the account");
    // The searched population is still stated — as the search's own count, where it is
    // true — so dropping the account figure does not leave the client with nothing.
    expect(container.textContent).toContain("Matching your search, by stage:");
  });

  it("does not count the assignee filter off the page either", async () => {
    // The stage badges are the server's, over the server's scope — which now includes
    // the owner. A screen that filtered rows in the browser would show the ACCOUNT's
    // tally beside two rows, which is the §52 shape in a new costume.
    const { container, calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?assigned_to=u1&limit=100": leadList([lead({ assigned_to: "u1" })], {
          total: 1,
          status_counts_matching_search: {
            new: 1,
            contacted: 0,
            interested: 0,
            hot: 0,
            won: 0,
            lost: 0,
          },
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Assigned to me" }));
    // `keepPreviousData` leaves the OLD page on screen while the filtered one is in
    // flight — which is the point of it — so the assertion has to wait for the new
    // answer rather than reading whatever is there the moment the chip is clicked.
    await vi.waitFor(() => {
      expect(container.textContent).toContain("Showing 1 of 1 lead");
    });
    expect(calls.some((c) => c.path === "/v1/leads?assigned_to=u1&limit=100")).toBe(true);
  });

  it("renders no page heading, because the shell already prints one", async () => {
    // The shell renders the title from the nav list (layout.tsx). A second "Leads" here
    // is a visible duplicate, and the copy that drifts when the nav entry is renamed.
    const { container } = await renderClientPage(<LeadsPage />, routes());

    await screen.findByText(/by stage/);
    expect(container.querySelectorAll("h1")).toHaveLength(0);
  });
});

/**
 * LEAD OWNERSHIP (ROADMAP M3). `leads.assigned_to` existed from the first migration and
 * nothing read or wrote it; this is the screen half of closing that.
 *
 * The three things worth a test here are the three that would be invisible in review:
 * the filter is a REQUEST and not a slice, the unassignment is an explicit `null` in the
 * body, and a dead `/v1/members` refuses rather than rendering an empty team.
 */
describe("who owns a lead", () => {
  const ASSIGNED = leadList([lead({ assigned_to: "u2", assigned_to_name: "Kiran Babu" })], {
    total: 1,
    status_counts_matching_search: { new: 1, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
  });

  it("offers the account's team, and shows the current owner as the selected one", async () => {
    await renderClientPage(<LeadsPage />, routes({ "/v1/leads?limit=100": ASSIGNED }));

    const select = await screen.findByLabelText("Owner of Ramesh Kumar");
    expect((select as HTMLSelectElement).value).toBe("u2");
    const options = Array.from((select as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options).toEqual(["Unassigned", "Priya Nair", "Kiran Babu"]);
  });

  it("assigns by sending the member's id to the server", async () => {
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([lead()], {
          total: 1,
          status_counts_matching_search: {
            new: 1,
            contacted: 0,
            interested: 0,
            hot: 0,
            won: 0,
            lost: 0,
          },
        }),
        "/v1/leads/lead-a": lead({ assigned_to: "u2", assigned_to_name: "Kiran Babu" }),
      }),
    );

    fireEvent.change(await screen.findByLabelText("Owner of Ramesh Kumar"), {
      target: { value: "u2" },
    });

    await vi.waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.path === "/v1/leads/lead-a");
      expect(patch, "no PATCH reached the server").toBeTruthy();
      expect(JSON.parse(patch!.body ?? "{}")).toEqual({ assigned_to: "u2" });
    });
  });

  it("UNASSIGNS with an explicit null rather than by omitting the key", async () => {
    /**
     * The one that a helper stripping empty values would break silently. The API tells
     * "unassign" from "leave the owner alone" by whether `assigned_to` is PRESENT in the
     * body (`crm.routes.patch_lead` reads Pydantic's `model_fields_set`), so a dropped
     * key answers 200 and changes nothing — a button that looks like it worked.
     */
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": ASSIGNED, "/v1/leads/lead-a": lead() }),
    );

    fireEvent.change(await screen.findByLabelText("Owner of Ramesh Kumar"), {
      target: { value: "" },
    });

    await vi.waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH" && c.path === "/v1/leads/lead-a");
      expect(patch).toBeTruthy();
      // Parsed, not string-matched: `"assigned_to":null` and an absent key both render
      // as "no owner" on screen and only one of them reaches the column.
      const body = JSON.parse(patch!.body ?? "{}");
      expect("assigned_to" in body).toBe(true);
      expect(body.assigned_to).toBeNull();
    });
  });

  it("names an owner who has left rather than snapping the row to Unassigned", async () => {
    // `assigned_to_name` is null for an unassigned lead AND for a member this account
    // can no longer name. Collapsing the two would make the next change the client made
    // look like they had removed somebody they never saw.
    await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([lead({ assigned_to: "u9", assigned_to_name: null })], {
          total: 1,
          status_counts_matching_search: {
            new: 1,
            contacted: 0,
            interested: 0,
            hot: 0,
            won: 0,
            lost: 0,
          },
        }),
      }),
    );

    const select = (await screen.findByLabelText("Owner of Ramesh Kumar")) as HTMLSelectElement;
    expect(select.value).toBe("u9");
    expect(select.selectedOptions[0].textContent).toContain("No longer on this account");
  });

  it("disables the control WITH the reason for a role that may not assign", async () => {
    const staff = { ...ME, role: "staff", permissions: ["leads:read", "calls:read"] };
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": staff, "/v1/leads?limit=100": ASSIGNED }),
    );

    const select = (await screen.findByLabelText("Owner of Ramesh Kumar")) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    // The reason is ON the control, and also said once above the table — a refusal a
    // screenful away from the dead control is the defect §52 records.
    expect(select.title).toContain("account owner");
    // "edit a lead", not "change who owns a lead": ONE `leads:write` gate now covers the
    // owner select and the status select. The second one used to be gated on a separate
    // `Boolean(me.data?.impersonating)`, which read a failed `/v1/me` as "not read-only"
    // and left it open to a 403 — and two gates on one permission is where the drift was.
    expect(container.textContent).toContain("Only an account owner can edit a lead");
    // The status select is dead for the same reason and under the same sentence.
    expect(
      (screen.getByLabelText(/Status for Ramesh Kumar/) as HTMLSelectElement).disabled,
    ).toBe(true);
  });

  it("refuses rather than rendering an empty team when /v1/members fails", async () => {
    /**
     * `?? []` on this fetch would draw a dropdown containing only "Unassigned", which
     * says "you have no colleagues" from a request that never landed. The owner is still
     * NAMED, because that came down with the row and is the server's own answer.
     */
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": ASSIGNED,
        "/v1/members": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your team.",
        }),
      }),
    );

    await screen.findByRole("alert");
    expect(screen.queryByLabelText("Owner of Ramesh Kumar")).toBeNull();
    expect(container.textContent).toContain("Kiran Babu");
    expect(container.textContent).toContain("We could not read your team");
  });

  it("sends the owner filter to the SERVER and never slices the loaded page", async () => {
    /**
     * The assertion is on the REQUEST, deliberately. A screen that filtered `items` in
     * the browser would render the same two rows and pass any assertion about them —
     * while being wrong about every lead past the 100-row cap.
     */
    const { calls } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/leads?limit=100": leadList([lead(), lead({ id: "lead-b", name: "Priya's lead" })]),
        "/v1/leads?assigned_to=u1&limit=100": leadList([lead({ assigned_to: "u1" })], {
          total: 1,
          status_counts_matching_search: {
            new: 1,
            contacted: 0,
            interested: 0,
            hot: 0,
            won: 0,
            lost: 0,
          },
        }),
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Assigned to me" }));

    await vi.waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/leads?assigned_to=u1&limit=100")).toBe(true);
    });
    // …and clicking it again clears the filter, rather than leaving the client stuck in
    // a view they cannot get out of without a reload.
    fireEvent.click(screen.getByRole("button", { name: "Assigned to me" }));
    await vi.waitFor(() => {
      expect(
        calls.filter((c) => c.path === "/v1/leads?limit=100").length,
        "the unfiltered list was asked for again",
      ).toBeGreaterThan(1);
    });
  });

  it("tells an impersonating operator why the filter will be empty", async () => {
    // D-22: leads belong to the client's team, never to us. The chip works — it just
    // matches nothing — so the sentence is beside it rather than a dead control.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/me": { ...ME, impersonating: true } }),
    );

    await screen.findByRole("button", { name: "Assigned to me" });
    expect(container.textContent).toContain("as Calevate operations");
  });

  it("links each lead to its own screen by id, never by number", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": leadList([lead()]) }),
    );

    const link = (await screen.findByRole("link", { name: /Ramesh Kumar/ })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/c/acme/leads/lead-a");
    // A URL reaches browser history, referrers and access logs — hard rule 6 is stricter
    // for a link than for text.
    for (const anchor of Array.from(container.querySelectorAll("a"))) {
      expect(anchor.getAttribute("href") ?? "").not.toContain("9876543210");
    }
  });
});

/**
 * The "Call with AI" control, and the two reads it stands on.
 *
 * `(agents.data ?? []).filter(canDial)` made an EMPTY dialer list out of a failed
 * `/v1/agents`, and `Boolean(me.data && me.data.permissions.includes("leads:dispatch")
 * && …)` read a failed `/v1/me` as "no". Either one deleted the Call column, the agent
 * picker and every row button with nothing said — a client who has the feature shown a
 * screen identical to one where it was never built. §52: failure is a refusal, and
 * silence is not a refusal.
 *
 * The sentence is asserted PRESENT in both, because "the button is gone" is also true of
 * a screen that rendered nothing at all.
 */
describe("dispatching a call from the table, when a read did not answer", () => {
  it("says why, rather than silently withdrawing the control, when /v1/agents fails", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/agents": problem(503, { title: "Service unavailable", retryable: true }),
        "/v1/leads?limit=100": leadList([lead()]),
      }),
    );

    await screen.findByRole("link", { name: /Ramesh Kumar/ });
    expect(container.textContent).toContain("We could not read your agents just now");
    expect(container.textContent).toContain("no call can be placed from this table");
    expect(screen.queryByRole("button", { name: /Call with AI/ })).toBeNull();
    expect(container.textContent).not.toContain("Calls from this table are placed by");
  });

  it("says why when /v1/me fails, and does not read a dead permission check as a refusal", async () => {
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/me": problem(503, { title: "Service unavailable", retryable: true }),
        "/v1/leads?limit=100": leadList([lead()]),
      }),
    );

    await screen.findByRole("link", { name: /Ramesh Kumar/ });
    expect(container.textContent).toContain("We could not check who you are signed in as");
    expect(screen.queryByRole("button", { name: /Call with AI/ })).toBeNull();
    // The owner filter goes with it, and the same sentence covers it — the chip used to
    // vanish on its own, which reads as "there is no such filter".
    expect(screen.queryByRole("button", { name: "Assigned to me" })).toBeNull();
    expect(container.textContent).toContain("“Assigned to me” filter are closed");
  });

  it("still offers the control when both reads answered", async () => {
    // The premise of the two above. Without this they pass on a screen that never
    // renders a call button at all.
    const { container } = await renderClientPage(
      <LeadsPage />,
      routes({ "/v1/leads?limit=100": leadList([lead()]) }),
    );

    expect(await screen.findByRole("button", { name: /Call with AI/ })).toBeDefined();
    expect(container.textContent).toContain("Calls from this table are placed by");
    expect(container.textContent).not.toContain("We could not read your agents just now");
  });

  it("keeps the status select shut, not open, when the permission read fails", async () => {
    // `readOnly` was `Boolean(me.data?.impersonating)` — §52's `?? false` in another
    // costume. A dead `/v1/me` answered "you are NOT read-only" and re-opened every
    // status select to a 403 on click.
    await renderClientPage(
      <LeadsPage />,
      routes({
        "/v1/me": problem(503, { title: "Service unavailable", retryable: true }),
        "/v1/leads?limit=100": leadList([lead()]),
      }),
    );

    const select = (await screen.findByLabelText(/Status for Ramesh Kumar/)) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(screen.getByText(/We could not check whether you can edit a lead/)).toBeDefined();
  });
});
