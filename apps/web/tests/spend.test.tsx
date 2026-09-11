import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FleetSpendPage from "@/app/admin/spend/page";
import TenantSpendPage from "@/app/admin/tenants/[tenantId]/spend/page";
import type { Me } from "@/lib/api/client";
import type {
  FleetSpend,
  Spend,
  TenantSpend,
  TtsSpeakingRate,
} from "@/lib/api/spend";

import { renderAdminRoute } from "./adminRoute";
import { renderBillingHub } from "./billingHub";
import { problem, stillLoading } from "./harness";

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
  withheld_acts: [],
  // `billing:read` is what `GET /v1/billing/spend` requires — owners hold it, staff do
  // not (SEC-COMP §5).
  permissions: ["org:read", "wallet:read", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const STAFF: Me = {
  ...ME,
  role: "staff",
  permissions: ["org:read", "wallet:read"],
};

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
  // No vendor row: the API omits a month nobody has attested rather than sending a zero
  // fee, and the board renders that absence in words (D-547 Phase D.3).
  tts_plan: [],
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
  const term = [...container.querySelectorAll("p")].find(
    (el) => el.textContent === label,
  );
  expect(term, `no StatTile labelled ${JSON.stringify(label)}`).toBeDefined();
  return term?.nextElementSibling?.textContent ?? "";
}

/**
 * WHAT THE HUB AROUND THIS PANEL READS. The per-agent breakdown is the second half of the
 * Usage tab of `/c/{slug}/billing` now (D-525), so the screen also reads the month's
 * totals, the spending limit, the wallet, its history and the pack rate card — whatever
 * tab is open. Routed with the emptiest honest answer, because an unrouted request throws
 * in this harness: a hole in a test's premise should say so rather than render an error
 * state that happens to contain the string it was looking for.
 */
function clientRoutes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    [CLIENT_ROUTE]: CLIENT_SPEND,
    "/v1/usage": HUB_USAGE,
    "/v1/billing/caps": HUB_CAPS,
    "/v1/billing/wallet": HUB_WALLET,
    "/v1/billing/wallet/ledger?limit=50": { entries: [], payments: [] },
    "/v1/billing/topups/packs": { list_rate_inr_per_min: "8.00", packs: [] },
    ...over,
  };
}

/** An INVOICED account with no month's charges of its own: this file is about the
 *  breakdown, and a balance or a second set of totals in every assertion below would be
 *  noise `tests/usage.test.tsx` and `tests/credits.test.tsx` already own. */
const HUB_WALLET = {
  tenant_id: "o1",
  prepaid: false,
  balance_inr: "0.00",
  is_low: false,
  low_balance_threshold_inr: "200.00",
  outbound_stopped: false,
  runway: {
    basis: "empty",
    days: null,
    daily_burn_inr: null,
    history_days: 0,
    beyond_horizon: false,
    window_days: 30,
    min_history_days: 7,
    max_days: 365,
  },
  minutes_left: null,
  drawdown: {
    calls_inr: "0.00",
    ai_assist_inr: "0.00",
    adjustments_inr: "0.00",
    spent_inr: "0.00",
    added_inr: "0.00",
    refunded_inr: "0.00",
  },
};

const HUB_USAGE = {
  month: IST_MONTH,
  plan_tier: "managed",
  calls: 0,
  minutes_used: "0.0000",
  included_minutes: 0,
  minutes_left: null,
  month_charges_inr: "0.00",
  monthly_fee_inr: null,
  overage_minutes: "0.0000",
  // BOTH SPELLINGS: the wire carries the deprecated pair beside the new one
  // for one release (hard rule 8 step 1, D-558), with identical figures.
  overage_minutes_base_rung: "0.0000",
  overage_minutes_second_rung: "0.0000",
  overage_minutes_premium: "0.0000",
  overage_minutes_value: "0.0000",
  overage_cost_inr: "0.00",
  overage_rate_inr: "0.0000",
  overage_rate_second_inr: null,
  overage_rate_value_inr: null,
  llm_surcharge_inr: "0.00",
  llm_surcharge_minutes: "0.0000",
  llm_surcharge_rate_inr: null,
  llm_surcharge_models: [],
  capped: false,
  cap_minutes: null,
  credit_balance_inr: null,
  // THE TWO QUALITIES, required on `UsagePanelOut` since D-547. A month with no calls has
  // none on either, and the panel prints no row for a quality with no minutes.
  sarvam_minutes: "0.0000",
  sarvam_charges_inr: "0.00",
  sarvam_label: "Clear",
  cartesia_minutes: "0.0000",
  cartesia_charges_inr: "0.00",
  cartesia_label: "Studio",
};

const HUB_CAPS = {
  capped: false,
  month: IST_MONTH,
  minutes_used: "0.0",
  spend_used_inr: "0.00",
  client_cap_minutes: null,
  client_cap_spend_inr: null,
  plan_cap_minutes: null,
  plan_cap_spend_inr: null,
  effective_cap_minutes: null,
  effective_cap_spend_inr: null,
};

const tenantPage = (
  <TenantSpendPage params={Promise.resolve({ tenantId: "t1" })} />
);

const CLIENT_ROUTE = `/v1/billing/spend?month=${IST_MONTH}`;
const TENANT_ROUTE = `/v1/admin/tenants/t1/spend?month=${IST_MONTH}`;
const FLEET_ROUTE = `/v1/admin/spend?month=${IST_MONTH}`;
const TTS_ROUTE = "/v1/admin/spend/tts-speaking-rate";

/** Pilot gate 12's number in the MEASURED state — 4-decimal strings, never parsed. */
const TTS_MEASURED: TtsSpeakingRate = {
  // Both voice rungs, ALWAYS — whether a price is attested is not a measurement, so this
  // travels with the measured and the unmeasured shape alike. The two cases below override
  // it with priced rows; here it is the shipped state, where only one voice has a price.
  by_provider: [
    {
      provider: "sarvam",
      tier_label: "Clear",
      price_attested: true,
      inr_per_1k_chars: "3.0000",
      pooled_inr_per_minute: "1.2360",
    },
    {
      provider: "cartesia",
      tier_label: "Studio",
      price_attested: false,
      inr_per_1k_chars: null,
      pooled_inr_per_minute: null,
    },
  ],
  measured: true,
  calls: 41,
  clients: 2,
  minimum_calls: 20,
  reason: null,
  p50: { chars_per_minute: "412.0000", tts_inr_per_minute: "1.2360" },
  p95: { chars_per_minute: "688.5000", tts_inr_per_minute: "2.0655" },
  pooled: { chars_per_minute: "437.1429", tts_inr_per_minute: "1.3114" },
  assumed_low: { chars_per_minute: "360.0000", tts_inr_per_minute: "1.0800" },
  assumed_high: { chars_per_minute: "540.0000", tts_inr_per_minute: "1.6200" },
  tts_inr_per_10k_chars: "30.0000",
  // THE BLOCK THE COST MODEL ACTUALLY READS (D-557). The fields above are the archive,
  // walked one tenant at a time for its percentiles; this is the platform counter, and the
  // floor it produces is the one every Clear rate on the rate card is judged against.
  fleet: {
    measured: true,
    chars_per_minute: "437.1429",
    calls: 41,
    minimum_calls: 20,
    window: "2026-08..2026-09",
    basis: "measured 437.1429 chars/call-min over 41 calls, 2026-08..2026-09",
    cost_floor_inr_per_min: "3.8125",
    refusal_floor_inr_per_min: "4.1211",
    floor_above_refusal: false,
  },
};

/** The refusal: twelve calls, twenty needed, no rate anywhere in the payload. */
const TTS_UNMEASURED: TtsSpeakingRate = {
  ...TTS_MEASURED,
  measured: false,
  calls: 12,
  clients: 1,
  reason:
    "12 calls with a transcript; a figure is published from 20 or more. TRD §10.1's assumed band stays in force.",
  p50: null,
  p95: null,
  pooled: null,
  // The counter is short too, and says so with the sample rather than a placeholder rate:
  // the assumed band is what the cost model is still divided by.
  fleet: {
    measured: false,
    chars_per_minute: "540",
    calls: 12,
    minimum_calls: 20,
    window: null,
    basis:
      "assumed 540 chars/call-min (TRD 10.1, unmeasured - pilot gate 12); 12 of 20 calls measured",
    cost_floor_inr_per_min: "4.1211",
    refusal_floor_inr_per_min: "4.1211",
    floor_above_refusal: false,
  },
};

describe("the client's spend screen", () => {
  it("prints the server's rupee digits, grouped Indian-style and never parsed", async () => {
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
      }),
      "Usage",
    );

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
    expect(tileValue(container, `Minutes used · ${IST_MONTH}`)).toBe("42.5000");
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
      by_agent: [
        {
          ...CLIENT_SPEND.by_agent[0],
          cost_inr: "300000.00",
          margin_inr: "715850.00",
        },
      ],
    };
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: spiked,
      }),
      "Usage",
    );

    await screen.findByText(LAKHS_RENDERED);
    const text = container.textContent ?? "";
    for (const leaked of [
      "₹3,00,000.00",
      "₹7,20,899.00",
      "₹7,15,850.00",
      "70.61",
    ]) {
      expect(
        text,
        `the client screen printed ${leaked}, which is ours and not theirs`,
      ).not.toContain(leaked);
    }
    // …and the LABELS the admin screens use, in case a future layout renders one with an
    // empty value. Matched exactly rather than case-folded: "Your costliest calls" contains
    // "our cost" as a substring, and a check that cannot tell those apart is a check that
    // gets deleted the first time somebody renames a heading.
    for (const label of ["Our cost", "Margin", "Charged"]) {
      expect(
        text,
        `the client screen rendered the operator's "${label}" column`,
      ).not.toContain(label);
    }
  });

  it("says WHICH kind of number the per-call figure is", async () => {
    // A fact and a share are different claims. On a prepaid account the figure beside a
    // call is what it took off the balance; on a managed plan it is that call's share of a
    // month priced as a whole, and labelling one as the other is a claim the server never
    // made.
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
      }),
      "Usage",
    );
    await screen.findByText(LAKHS_RENDERED);
    expect(container.textContent).toContain("Each call's share of this month");
  });

  it("calls a prepaid debit what it is, rather than a share of a month", async () => {
    /* Its own test rather than a second render inside the one above. `screen` queries the
       whole document and RTL does not unmount between renders, so two hubs in one test
       body means two tab strips and `findByRole("tab", { name: "Usage" })` matching both —
       a failure about the harness, on an assertion about money. */
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: { ...CLIENT_SPEND, charge_basis: "wallet_debit" },
      }),
      "Usage",
    );
    await screen.findByText(LAKHS_RENDERED);
    expect(container.textContent).toContain(
      "What each call took off your balance",
    );
  });

  it("explains a residual rather than letting the columns quietly disagree", async () => {
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
      }),
      "Usage",
    );
    await screen.findByText(LAKHS_RENDERED);
    // The server's own subtraction, printed — not one this screen performed. The float
    // answer to the same question is 50.09999999997672, which renders ₹50.09.
    expect(container.textContent).toContain("₹50.10");
    expect(
      container.textContent,
      "the residual was subtracted in the browser",
    ).not.toContain("₹50.09");
    expect(container.textContent).toContain(
      "nothing to split this month's charge across",
    );
  });

  it("says nothing at all about a residual the server calls zero", async () => {
    // `residual_reason` is null whenever the residual IS zero. A panel that appeared anyway
    // would be an explanation of a discrepancy that does not exist.
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: {
          ...CLIENT_SPEND,
          itemised_charge_inr: LAKHS,
          itemisation_residual_inr: "0.00",
          residual_reason: null,
        },
      }),
      "Usage",
    );
    await screen.findByText(LAKHS_RENDERED);
    expect(container.textContent).not.toContain("add up to");
  });

  /* THE TWO §52 TESTS HOLD THE REST OF THE TAB IN FLIGHT. The breakdown shares the Usage
     tab with the month's own totals and the spending limit now (D-525), and both of those
     legitimately print ₹0.00 on an account with no charges — so a document-wide "no ₹0.00"
     assertion would be answered by a panel this file is not about. Parking their two reads
     leaves the breakdown as the only thing on screen, which is what the claim is about. */
  it("shows a skeleton while the month is in flight, and no figures", async () => {
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        "/v1/usage": stillLoading(),
        "/v1/billing/caps": stillLoading(),
        [CLIENT_ROUTE]: stillLoading(),
      }),
      "Usage",
    );
    expect(
      await screen.findByText("Loading this month's breakdown"),
    ).toBeTruthy();
    expect(container.textContent).not.toContain("₹0.00");
  });

  it("refuses out loud when the month cannot be read, and prints no ₹0.00", async () => {
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        "/v1/usage": stillLoading(),
        "/v1/billing/caps": stillLoading(),
        [CLIENT_ROUTE]: problem(503, {
          title: "Spend is unavailable",
          // `ProblemNotice` prints the problem's `detail` — `ApiProblem.message` is
          // `detail ?? title` — so this is the sentence the client actually reads.
          detail: "We could not read this month's usage.",
        }),
      }),
      "Usage",
    );
    await screen.findByText("We could not read this month's usage.");
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("No calls this month");
  });

  it("splits the month by voice quality, from the lot splits, with no total added here", async () => {
    // WHAT REPLACED THE PLAN'S "REDUCED RATE" PAIR (plan §5 F1). `overage_rate_value_inr`
    // is NULL on every plan that has ever existed, so the second rung it drove was a row
    // no client could ever see. What a client's minutes actually cost at two prices is now
    // a real fact and a different one: the two VOICE QUALITIES (D-547), whose minutes and
    // charges the server reads off the ledger's own lot splits — so this panel and the
    // credit history cannot disagree about a month.
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
        "/v1/usage": {
          ...HUB_USAGE,
          minutes_used: "140.5000",
          month_charges_inr: "902.50",
          sarvam_minutes: "120.50",
          sarvam_charges_inr: "602.50",
          sarvam_label: "Clear",
          cartesia_minutes: "20.00",
          cartesia_charges_inr: "300.00",
          cartesia_label: "Studio",
        },
      }),
      "Usage",
    );

    await screen.findByText("Clear voice (120.50 min)");
    expect(screen.getByText("Studio voice (20.00 min)")).toBeTruthy();
    expect(screen.getByText("₹602.50")).toBeTruthy();
    expect(screen.getByText("₹300.00")).toBeTruthy();
    // NO TOTAL IS COMPUTED IN THE BROWSER (D-458): the month's figure is the server's
    // `month_charges_inr`, and ₹902.50 is deliberately NOT ₹602.50 + ₹300.00 dressed up —
    // a screen that added the two rupee strings would agree with itself and disagree with
    // the statement the client is sent.
    expect(screen.getByText("₹902.50")).toBeTruthy();
    // The vendors are never named; the qualities are named by the server.
    for (const vendor of ["Sarvam", "sarvam", "Cartesia", "cartesia"]) {
      expect(container.textContent).not.toContain(vendor);
    }
    // And the retired pair is gone from the screen entirely.
    expect(container.textContent).not.toContain("reduced rate");
  });

  it("quotes 'minutes left this month' only where it means a cap, never a prepaid wallet", async () => {
    // ONE FIELD, TWO MEANINGS (`billing/service.py::usage_summary`): what is left of a
    // monthly CAP for a plan that has one, and — for a prepaid wallet —
    // `prepaid_minutes_left`, the balance divided by the LIST rate. D-547 made that second
    // reading untrue of everybody: credit is spent at the rates frozen on each purchase,
    // and the answer differs by voice quality as well. So the line stays for a capped plan
    // and goes for a prepaid one, whose honest pair is on the Overview tab.
    const capped = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
        "/v1/usage": {
          ...HUB_USAGE,
          plan_tier: "managed",
          cap_minutes: 500,
          minutes_left: 380,
        },
      }),
      "Usage",
    );
    await screen.findByText(/of calling left this month/);
    expect(capped.container.textContent).toContain("380 minutes");

    capped.unmount();

    const prepaid = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
        "/v1/usage": { ...HUB_USAGE, plan_tier: "prepaid", minutes_left: 380 },
      }),
      "Usage",
    );
    await screen.findByText("Total so far");
    expect(prepaid.container.textContent).not.toContain(
      "of calling left this month",
    );
    expect(prepaid.container.textContent).not.toContain("380 minutes");
  });

  it("says nothing per voice for a month with no minutes on either quality", async () => {
    // REWRITTEN when the six per-quality fields became required. The case this used to
    // cover — an API build that sent none of them — is no longer expressible, and the case
    // that replaces it is the one clients actually meet: a quiet month, where both
    // qualities arrive at "0.0000" and neither gets a ₹0.00 row inviting a question about
    // nothing. The month's totals are all still true and still on screen.
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": ME,
        [CLIENT_ROUTE]: CLIENT_SPEND,
      }),
      "Usage",
    );

    await screen.findByText("Total so far");
    expect(container.textContent).not.toContain("voice (");
    expect(container.textContent).not.toContain("Clear");
    expect(container.textContent).not.toContain("Studio");
  });

  it("tells a staff member why the screen is not theirs instead of collecting a 403", async () => {
    const { container } = await renderBillingHub(
      clientRoutes({
        "/v1/me": STAFF,
      }),
      "Usage",
    );
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
    const { container } = await renderAdminRoute(tenantPage, {
      [TENANT_ROUTE]: TENANT_SPEND,
    });
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
    const { container } = await renderAdminRoute(tenantPage, {
      [TENANT_ROUTE]: TENANT_SPEND,
    });
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
    expect(container.textContent).not.toContain(
      "AI assistant — cost we absorb",
    );
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
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Vasavi Dental");
    // Worst margin first is the SERVER's order and is rendered as sent — a second sort
    // here would be a second opinion about priority.
    const rows = container.querySelectorAll("tbody tr");
    expect(
      within(rows[0] as HTMLElement).getByText("Vasavi Dental"),
    ).toBeTruthy();
    // Colour is the one signal the a11y sweep cannot check and a colour-blind operator may
    // not have.
    expect(container.textContent).toContain("Losing money:");
  });

  it("refuses out loud when the walk fails, and reports no fleet total", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: problem(504, {
        title: "The walk timed out",
        detail: "Try a smaller month.",
      }),
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Try a smaller month.");
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("No live clients this month");
  });

  it("publishes the measured TTS speaking rate with the band it replaced", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("TTS speaking rate — measured");
    const text = container.textContent ?? "";
    // The server's digits, trailing zeros trimmed by string surgery and never re-rounded:
    // 437.1429 stays 437.1429 (a float path would print 437.14290000000005 somewhere).
    expect(text).toContain("437.1429");
    expect(text).toContain("₹1.3114/min");
    expect(text).toContain("412");
    expect(text).toContain("688.5");
    expect(text).toContain("₹2.0655/min");
    expect(text).toContain("41 calls with a transcript across 2 clients");
    // The band is labelled as the figure this REPLACED, and is still on the card.
    expect(text).toContain(
      "Replaces the assumed 360–540 chars/min (₹1.0800–₹1.6200/min)",
    );
    expect(text).not.toContain("Not enough calls");
  });

  it("refuses to print a figure below the threshold and says how many calls it needs", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: TTS_UNMEASURED,
    });
    await screen.findByText("Not enough calls to measure yet:");
    const text = container.textContent ?? "";
    expect(text).toContain("12 of 20 needed (across 1 client)");
    expect(text).toContain(TTS_UNMEASURED.reason);
    // The band is printed as an ASSUMPTION, and none of the measured-state figures leak
    // in from the null fields or from a placeholder.
    expect(text).toContain("assumption and not a reading");
    expect(text).toContain("360–540 chars/min");
    expect(text).not.toContain("437.1429");
    expect(text).not.toContain("₹1.3114");
    expect(text).not.toContain("Replaces the assumed");
  });
});

/**
 * WHAT THE VOICE VENDORS COST US (D-547, plan Phase D) — two figures that must stay apart.
 *
 * Worst consequence first:
 *
 * 1. **A plan fee defaulted to zero.** Under BYOK the call platform bills us nothing for the
 *    synthesizer leg, so a board that could not read the vendor's plan spend and printed
 *    ₹0.00 would show a fleet margin that does not exist. The absence is stated instead.
 * 2. **A difference computed in the browser.** The unused allotment is the SERVER's
 *    subtraction; two rupee strings subtracted here would be float arithmetic on money and a
 *    second answer to what we paid.
 * 3. **An unattested price read as a margin.** A vendor with no confirmed price attributes
 *    no cost at all, and the row has to say so rather than showing a healthy-looking zero.
 * 4. **The measured speaking rate is now the BILLED QUANTITY on a BYOK voice**, not only a
 *    check on TRD §10.1's band, so the card says what those characters cost per vendor.
 */

const TTS_PLAN = [
  {
    provider: "cartesia",
    tier_label: "Studio",
    month: IST_MONTH,
    plan_inr: "4312.00",
    attributed_inr: "1873.55",
    unused_inr: "2438.45",
    chars: "543100",
    inr_per_1k_chars: "3.4496",
  },
];

const BY_PROVIDER = [
  {
    provider: "sarvam",
    tier_label: "Clear",
    price_attested: false,
    inr_per_1k_chars: "3.0000",
    pooled_inr_per_minute: "1.3114",
  },
  {
    provider: "cartesia",
    tier_label: "Studio",
    price_attested: true,
    inr_per_1k_chars: "3.4496",
    pooled_inr_per_minute: "1.5080",
  },
];

describe("the voice vendors' bill on the money board", () => {
  it("shows plan spend beside attributed spend, with the vendor named", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: { ...FLEET, tts_plan: TTS_PLAN },
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Voice vendors — plan spend against attributed");
    const text = container.textContent ?? "";
    expect(text).toContain("Cartesia · Studio");
    expect(text).toContain("₹4,312.00");
    expect(text).toContain("₹1,873.55");
    // The SERVER's difference, rendered as sent.
    expect(text).toContain("₹2,438.45");
    expect(text).toContain("543100");
    expect(text).toContain("₹3.4496 per 1,000 characters");
  });

  it("says nothing rather than ₹0 when the plan spend was not published", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Voice vendors — plan spend against attributed");
    const text = container.textContent ?? "";
    expect(text).toContain("did not publish what the voice vendors billed");
    expect(text).not.toContain("Cartesia · Studio");
  });

  it("prints no unused figure when the server sent none, rather than subtracting here", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: {
        ...FLEET,
        tts_plan: [{ ...TTS_PLAN[0], unused_inr: null }],
      },
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Voice vendors — plan spend against attributed");
    // 4312.00 - 1873.55 is 2438.4500000000003 in IEEE-754; the absence of any such figure
    // is the assertion.
    expect(container.textContent).not.toContain("2,438.45");
    expect(container.textContent).not.toContain("2438.45");
  });

  it("warns that an unpriced vendor attributes no cost at all", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: {
        ...FLEET,
        tts_plan: [
          { ...TTS_PLAN[0], inr_per_1k_chars: null, attributed_inr: "0.00" },
        ],
      },
      [TTS_ROUTE]: TTS_MEASURED,
    });
    await screen.findByText("Voice vendors — plan spend against attributed");
    expect(container.textContent).toContain(
      "its calls attribute no cost at all",
    );
  });

  it("says what the measured speaking rate costs on each voice, and where there is no price", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: { ...TTS_MEASURED, by_provider: BY_PROVIDER },
    });
    await screen.findByText("What that rate costs on each voice");
    const text = container.textContent ?? "";
    expect(text).toContain(
      "Cartesia (Studio): ₹3.4496 per 1,000 characters → ₹1.5080/min",
    );
    // The vendor with no confirmed price gets the consequence, not a figure — even though
    // the payload carried a catalogue rate for it.
    expect(text).toContain("Sarvam (Clear): no confirmed price");
    expect(text).not.toContain("Sarvam (Clear): ₹3.0000");
  });

  it("still says which voices have no price when the rate itself is unmeasured", async () => {
    const { container } = await renderAdminRoute(<FleetSpendPage />, {
      [FLEET_ROUTE]: FLEET,
      [TTS_ROUTE]: { ...TTS_UNMEASURED, by_provider: BY_PROVIDER },
    });
    await screen.findByText("Not enough calls to measure yet:");
    expect(container.textContent).toContain(
      "What that rate costs on each voice",
    );
  });
});
