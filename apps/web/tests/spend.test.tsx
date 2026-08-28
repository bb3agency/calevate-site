import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FleetSpendPage from "@/app/admin/spend/page";
import TenantSpendPage from "@/app/admin/tenants/[tenantId]/spend/page";
import ClientSpendPage from "@/app/c/[slug]/spend/page";
import type { Me } from "@/lib/api/client";
import type { FleetSpend, Spend, TenantSpend } from "@/lib/api/spend";

import { renderAdminRoute } from "./adminRoute";
import { problem, renderClientPage, stillLoading } from "./harness";

/**
 * PER-RUPEE ATTRIBUTION, in both realms — and the wall between them.
 *
 * Four things can be wrong on these screens, in falling order of what a wrong render
 * costs:
 *
 * 1. **Our supplier cost or margin reaching a client.** `unit_cost_paid` is what we pay,
 *    and a client who can see it is a client negotiating against it. The server makes this
 *    a property of the response TYPE — `SpendOut` declares no cost-shaped field and is
 *    `extra="forbid"` — and this file is the frontend half of that guarantee: the client
 *    screen is driven with a payload carrying cost and margin keys the model does not
 *    declare, and asserted not to print them. A screen that read an undeclared field would
 *    be invisible to `tsc` (the generated type simply lacks it) and invisible to the
 *    server's own test (which reads the model, not the DOM).
 * 2. **Money parsed into a float.** Every rupee crosses as an exact decimal STRING (hard
 *    rule 7). `Number("10159.00")` is how ₹10,159.00 becomes ₹10,158.999999999998, and a
 *    type checker is happy either way because `string` and `number` both render. The
 *    fixtures below use figures whose float round-trip is visibly wrong.
 * 3. **A total re-derived in the browser.** The server publishes `itemised_charge_inr` and
 *    `itemisation_residual_inr` precisely so nothing downstream has to add or subtract two
 *    rupee strings. A screen that summed `by_agent` would be a second implementation of a
 *    bill.
 * 4. **§52** — a skeleton is not a number and a failed read is not ₹0.00. "You spent
 *    nothing this month" is a claim about a month's business and a 503 is not evidence for
 *    it.
 */

/** Grouped the way an Indian reader groups a rupee: 10,15,900.00 and not 1,015,900.00. */
const LAKHS = "1015900.10";
const LAKHS_RENDERED = "₹10,15,900.10";

const ME: Me = {
  impersonating: false,
  // `billing:read` is what `GET /v1/billing/spend` requires — owners hold it, staff do
  // not (SEC-COMP §5).
  permissions: ["org:read", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const STAFF: Me = { ...ME, role: "staff", permissions: ["org:read"] };

const IST_MONTH = new Date()
  .toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
  .slice(0, 7);

const CLIENT_SPEND: Spend = {
  month: IST_MONTH,
  charge_basis: "allocated",
  calls: 3,
  minutes_used: "42.5000",
  retainer_inr: "4999.00",
  period_charge_inr: LAKHS,
  // CHOSEN SO THE FLOAT IS VISIBLY WRONG, which most pairs of rupee figures are not:
  // `1015900.10 - 1015850.00` is 50.09999999997672 in IEEE-754, and `formatINR` keeps two
  // decimals — so a browser-side subtraction prints ₹50.09 where the server says ₹50.10.
  // A pair that happened to subtract exactly would make this test pass over the defect.
  itemised_charge_inr: "1015850.00",
  itemisation_residual_inr: "50.10",
  residual_reason: "no_billable_minutes",
  by_agent: [
    {
      agent_id: "agent-1",
      agent_name: "Front desk",
      calls: 3,
      minutes: "42.5000",
      charged_inr: "1015850.00",
    },
  ],
  top_calls: [
    {
      call_id: "call-1",
      agent_id: "agent-1",
      agent_name: "Front desk",
      started_at: "2026-08-12T09:00:00Z",
      direction: "inbound",
      minutes: "20.0000",
      charged_inr: "700000.00",
    },
  ],
  top_calls_truncated: false,
};

const TENANT_SPEND: TenantSpend = {
  ...CLIENT_SPEND,
  plan_tier: "managed",
  revenue_inr: "1020899.00",
  cost_inr: "300000.00",
  margin_inr: "720899.00",
  margin_pct: "70.61",
  cost_currency: "INR",
  cost_currency_stated: false,
  unattributed: { minutes: "0.0000", cost_inr: "120.00" },
  ai_assist: { used_inr: "412.50", requests: 87 },
  by_unit: [{ unit_type: "telephony_s", qty: "2550", cost_inr: "180000.00" }],
  by_agent: [
    {
      ...CLIENT_SPEND.by_agent[0],
      cost_inr: "300000.00",
      margin_inr: "715850.00",
      cost_currency_assumed: true,
    },
  ],
  top_calls: [
    {
      ...CLIENT_SPEND.top_calls[0],
      cost_inr: "200000.00",
      margin_inr: "500000.00",
      cost_currency_assumed: true,
    },
  ],
};

const FLEET: FleetSpend = {
  month: IST_MONTH,
  clients: 2,
  revenue_inr: LAKHS,
  cost_inr: "1200000.00",
  margin_inr: "-184100.00",
  margin_pct: null,
  tenants: [
    {
      tenant_id: "t2",
      name: "Vasavi Dental",
      slug: "vasavi",
      plan_tier: "prepaid",
      minutes_used: "80.0000",
      calls: 12,
      revenue_inr: "0.00",
      cost_inr: "184100.00",
      margin_inr: "-184100.00",
      margin_pct: null,
    },
    {
      tenant_id: "t1",
      name: "Sri Traders",
      slug: "sri-traders",
      plan_tier: "managed",
      minutes_used: "42.5000",
      calls: 3,
      revenue_inr: LAKHS,
      cost_inr: "1015900.10",
      margin_inr: "0.00",
      margin_pct: "0.00",
    },
  ],
};

/**
 * The figure inside one `StatTile`, found by its label.
 *
 * A tile is `<p>label</p><p>value</p>`, and several figures on this screen legitimately
 * repeat elsewhere on the page — the same minutes string appears in the agent table — so
 * `container.textContent` cannot tell "the headline is right" from "the number exists
 * somewhere". `money.test.tsx::rowValue` makes the same distinction for `<dl>` rows.
 */
function tileValue(container: HTMLElement, label: string): string {
  const term = [...container.querySelectorAll("p")].find((el) => el.textContent === label);
  expect(term, `no StatTile labelled ${JSON.stringify(label)}`).toBeDefined();
  return term?.nextElementSibling?.textContent ?? "";
}

const clientPage = <ClientSpendPage params={Promise.resolve({ slug: "acme" })} />;
const tenantPage = <TenantSpendPage params={Promise.resolve({ tenantId: "t1" })} />;

const CLIENT_ROUTE = `/v1/billing/spend?month=${IST_MONTH}`;
const TENANT_ROUTE = `/v1/admin/tenants/t1/spend?month=${IST_MONTH}`;
const FLEET_ROUTE = `/v1/admin/spend?month=${IST_MONTH}`;

describe("the client's spend screen", () => {
  it("prints the server's rupee digits, grouped Indian-style and never parsed", async () => {
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: CLIENT_SPEND,
    });

    await screen.findByText(LAKHS_RENDERED);
    const text = container.textContent ?? "";
    // The float round-trip of this figure, which is what a `Number()` anywhere on the
    // path would put on screen.
    expect(text).not.toContain("10158");
    expect(text).not.toContain("1015900.10"); // ungrouped, symbol-less: not formatted at all
    // Minutes are the server's own decimal string, at the precision the invoice bills.
    // Asserted on the TILE by its own label: the agent row below carries the same string,
    // so a bare `toContain` was answered by the table and would have passed over a parsed
    // headline figure (`String(Number("42.5000"))` is "42.5").
    expect(tileValue(container, "Minutes used")).toBe("42.5000");
  });

  it("carries no cost or margin, even when the payload does", async () => {
    /**
     * The wall, driven from the wrong side. The server's model declares no cost-shaped
     * field, so a widening would have to happen there first — but a SCREEN that reached
     * for an undeclared key would compile (the property is simply absent from the
     * generated type until someone adds it) and would leak the moment the field appeared.
     *
     * So the response is spiked with exactly the keys the admin model carries. Nothing on
     * the client screen may print them.
     */
    const spiked = {
      ...CLIENT_SPEND,
      cost_inr: "300000.00",
      margin_inr: "720899.00",
      margin_pct: "70.61",
      by_agent: [{ ...CLIENT_SPEND.by_agent[0], cost_inr: "300000.00", margin_inr: "715850.00" }],
    };
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: spiked,
    });

    await screen.findByText(LAKHS_RENDERED);
    const text = container.textContent ?? "";
    for (const leaked of ["₹3,00,000.00", "₹7,20,899.00", "₹7,15,850.00", "70.61"]) {
      expect(text, `the client screen printed ${leaked}, which is ours and not theirs`)
        .not.toContain(leaked);
    }
    // …and the LABELS the admin screens use, in case a future layout renders one with an
    // empty value. Matched exactly rather than case-folded: "Your costliest calls" contains
    // "our cost" as a substring, and a check that cannot tell those apart is a check that
    // gets deleted the first time somebody renames a heading.
    for (const label of ["Our cost", "Margin", "Charged"]) {
      expect(text, `the client screen rendered the operator's "${label}" column`)
        .not.toContain(label);
    }
  });

  it("says WHICH kind of number the per-call figure is", async () => {
    // A fact and a share are different claims. On a prepaid account the figure beside a
    // call is what it took off the balance; on a managed plan it is that call's share of a
    // month priced as a whole, and labelling one as the other is a claim the server never
    // made.
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: CLIENT_SPEND,
    });
    await screen.findByText(LAKHS_RENDERED);
    expect(container.textContent).toContain("Each call's share of this month");

    const { container: prepaid } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: { ...CLIENT_SPEND, charge_basis: "wallet_debit" },
    });
    await screen.findAllByText(LAKHS_RENDERED);
    expect(prepaid.textContent).toContain("What each call took off your balance");
  });

  it("explains a residual rather than letting the columns quietly disagree", async () => {
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: CLIENT_SPEND,
    });
    await screen.findByText(LAKHS_RENDERED);
    // The server's own subtraction, printed — not one this screen performed. The float
    // answer to the same question is 50.09999999997672, which renders ₹50.09.
    expect(container.textContent).toContain("₹50.10");
    expect(container.textContent, "the residual was subtracted in the browser")
      .not.toContain("₹50.09");
    expect(container.textContent).toContain("nothing to split this month's charge across");
  });

  it("says nothing at all about a residual the server calls zero", async () => {
    // `residual_reason` is null whenever the residual IS zero. A panel that appeared anyway
    // would be an explanation of a discrepancy that does not exist.
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: {
        ...CLIENT_SPEND,
        itemised_charge_inr: LAKHS,
        itemisation_residual_inr: "0.00",
        residual_reason: null,
      },
    });
    await screen.findByText(LAKHS_RENDERED);
    expect(container.textContent).not.toContain("add up to");
  });

  it("shows a skeleton while the month is in flight, and no figures", async () => {
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: stillLoading(),
    });
    expect(await screen.findByText("Loading this month's spend")).toBeTruthy();
    expect(container.textContent).not.toContain("₹0.00");
  });

  it("refuses out loud when the month cannot be read, and prints no ₹0.00", async () => {
    const { container } = await renderClientPage(clientPage, {
      "/v1/me": ME,
      [CLIENT_ROUTE]: problem(503, {
        title: "Spend is unavailable",
        // `ProblemNotice` prints the problem's `detail` — `ApiProblem.message` is
        // `detail ?? title` — so this is the sentence the client actually reads.
        detail: "We could not read this month's usage.",
      }),
    });
    await screen.findByText("We could not read this month's usage.");
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("No calls this month");
  });

  it("tells a staff member why the screen is not theirs instead of collecting a 403", async () => {
    const { container } = await renderClientPage(clientPage, { "/v1/me": STAFF });
    await screen.findByText(/limited to the account owner/);
    expect(container.textContent).not.toContain("₹");
    // What the refusal must NOT do is also render the API's 403 underneath it. The query is
    // declared before the permission is known — `/v1/me` is still in flight on the first
    // paint, and gating the read on it would put every OWNER's spend request behind a
    // second round trip — so the request goes out and is refused, exactly as on `/usage`
    // and `/invoice`. The screen a staff member sees is one sentence they can act on, not
    // that sentence plus a red alert that reads like an outage.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("the operator's half", () => {
  it("shows both directions for one client and marks the assumed cost currency", async () => {
    const { container } = await renderAdminRoute(tenantPage, { [TENANT_ROUTE]: TENANT_SPEND });
    await screen.findByText("₹7,20,899.00");
    const text = container.textContent ?? "";
    expect(text).toContain("₹3,00,000.00");
    expect(text).toContain("70.61%");
    // OPERATIONS §2 gate 7: every cost figure here is scaled by an assumption we made, and
    // an operator quoting a margin is entitled to know that before they quote it.
    expect(text).toContain("Cost is scaled by an assumption");
  });

  it("surfaces the absorbed copilot cost, apart from the call margin", async () => {
    // The reported defect: a client's in-app copilot spend is metered but the money board
    // could not see it, because it is `_NOT_AI_UNITS`-excluded from the call margin. It is
    // published on its own line, and it is marked as absorbed — not billed to the client
    // and not in the revenue/cost/margin above.
    const { container } = await renderAdminRoute(tenantPage, { [TENANT_ROUTE]: TENANT_SPEND });
    await screen.findByText("AI assistant — cost we absorb");
    const text = container.textContent ?? "";
    expect(text).toContain("₹412.50");
    expect(text).toContain("87 assists");
    expect(text).toContain("not billed to the client");
  });

  it("says nothing about AI when the month generated none", async () => {
    // Null, not ₹0.00 — the same "different facts" the margin-% tile draws.
    const { container } = await renderAdminRoute(tenantPage, {
      [TENANT_ROUTE]: { ...TENANT_SPEND, ai_assist: null },
    });
    await screen.findByText("₹7,20,899.00");
    expect(container.textContent).not.toContain("AI assistant — cost we absorb");
  });

  it("says 'not billed yet' rather than 0% when nothing has been billed", async () => {
    // Two different facts, and an operator acts differently on each.
    const { container } = await renderAdminRoute(tenantPage, {
      [TENANT_ROUTE]: { ...TENANT_SPEND, margin_pct: null },
    });
    await screen.findByText("not billed yet");
    expect(container.textContent).not.toContain("0.00%");
  });

  it("walks the whole fleet and marks a losing client in words, not only in colour", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, { [FLEET_ROUTE]: FLEET });
    await screen.findByText("Vasavi Dental");
    // Worst margin first is the SERVER's order and is rendered as sent — a second sort
    // here would be a second opinion about priority.
    const rows = container.querySelectorAll("tbody tr");
    expect(within(rows[0] as HTMLElement).getByText("Vasavi Dental")).toBeTruthy();
    // Colour is the one signal the a11y sweep cannot check and a colour-blind operator may
    // not have.
    expect(container.textContent).toContain("Losing money:");
  });

  it("refuses out loud when the walk fails, and reports no fleet total", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: problem(504, { title: "The walk timed out", detail: "Try a smaller month." }),
    });
    await screen.findByText("Try a smaller month.");
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("No live clients this month");
  });
});
