import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadsPage from "@/app/c/[slug]/leads/page";
import type { Agent } from "@/lib/api/agents";
import type { CallLeadResult, Lead, LeadList, Me } from "@/lib/api/client";

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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
} as unknown as Me;

/** Published, live and able to dial out — the three things `canDial` asks for. */
const DIALER: Agent = {
  id: "agent-1",
  name: "Follow-up agent",
  published: true,
  status: "live",
  direction: "outbound",
} as unknown as Agent;

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
    ...over,
  } as Lead;
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
    columns: [],
    total: items.length,
    limit: 100,
    offset: 0,
    status_counts_matching_search: { new: 0, contacted: 0, interested: 0, hot: 0, won: 0, lost: 0 },
    ...over,
  } as LeadList;
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/agents": [DIALER],
    "/v1/leads?limit=100": leadList([]),
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
      name: /Export all as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("account owner");
  });

  it("enables it for a session the server would accept", async () => {
    await renderClientPage(<LeadsPage />, routes());
    const button = (await screen.findByRole("button", {
      name: /Export all as CSV/,
    })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
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
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "hot" }));
    return rendered;
  }

  it("renders the server's stage counts, not a tally of the rows it happens to hold", async () => {
    const { calls } = await filterToHot();

    const tally = (await screen.findByText(/by stage/)).parentElement;
    // The chips filter SERVER-side — that is the behaviour the counts have to survive.
    expect(calls.some((c) => c.path === "/v1/leads?status=hot&limit=100")).toBe(true);

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

  it("does not print a filtered total under the words 'every lead in the account'", async () => {
    const { container } = await filterToHot();

    await screen.findByText(/by stage/);
    // 12+3+4+2+1+0 = 22 leads in the account; `total` is 2 because a chip is on. The
    // export ignores the chip, so 22 is the figure the sentence is about — the old copy
    // printed `total` here and told a client their whole-account export held 2 rows.
    expect(container.textContent).toContain("every lead in the account (22)");
    expect(container.textContent).not.toContain("account (2),");
  });

  it("names no account total while a search is on, because the response holds none", async () => {
    // The other half of the same fix. `status_counts_matching_search` follows the SEARCH
    // (crm/service.py), so once the box has text nothing in the response adds up to the
    // account — and the export still ignores the search. A number here would be the
    // searched population wearing the account's label.
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
      }),
    );

    fireEvent.change(screen.getByLabelText("Search leads"), { target: { value: "ram" } });
    // The box is debounced by 300ms, so this also asserts the debounce still fires — and
    // that the search is a SERVER-side filter rather than a slice of a capped page.
    await screen.findByText(/matching your search/);
    expect(calls.some((c) => c.path === "/v1/leads?search=ram&limit=100")).toBe(true);

    expect(container.textContent).toContain("the export ignores this filter");
    expect(container.textContent).not.toContain("account (");
    // The searched population is still stated — as the search's own count, where it is
    // true — so dropping the account figure does not leave the client with nothing.
    expect(container.textContent).toContain("Matching your search, by stage:");
  });

  it("renders no page heading, because the shell already prints one", async () => {
    // The shell renders the title from the nav list (layout.tsx). A second "Leads" here
    // is a visible duplicate, and the copy that drifts when the nav entry is renamed.
    const { container } = await renderClientPage(<LeadsPage />, routes());

    await screen.findByText(/by stage/);
    expect(container.querySelectorAll("h1")).toHaveLength(0);
  });
});
