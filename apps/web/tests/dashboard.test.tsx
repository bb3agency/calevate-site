import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DashboardPage from "@/app/c/[slug]/page";
import type { CallSummary, Dashboard, Me } from "@/lib/api/client";
import type { UsagePanel } from "@/lib/api/hooks";

import { problem, renderClientPage } from "./harness";

/**
 * The dashboard — the screen a client looks at to decide whether the product is
 * working, and therefore the screen where a comfortable lie does the most damage.
 *
 * The design this was built from arrived full of mock numbers, and the first wiring
 * pass kept them as FALLBACKS (`dashboard.data?.calls_7d ?? 5430`). That is the exact
 * failure this file exists to prevent: a client whose calls have stopped, or whose
 * session has expired, would have been shown 5,430 calls and a healthy trend. The
 * assertions below are therefore mostly NEGATIVE — they are about what must not be on
 * screen when the server has not said it.
 *
 * Four claims, in falling order of what a wrong answer costs:
 *
 * 1. A failed dashboard request renders a refusal, never figures. "Some number" is
 *    indistinguishable from "your number" to the person reading it.
 * 2. A zero is rendered as zero. The tile that says 0 calls today is the tile that
 *    makes an owner ring us, which is the entire point of the screen.
 * 3. No raw phone number reaches the DOM (hard rule 6) — the list renders
 *    `caller_masked` and nothing else, and the mock printed full numbers here.
 * 4. The after-hours tile says WHICH definition produced its number, because a guess
 *    and a fact must not render identically (`after_hours_basis`).
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
} as unknown as Me;

/** A dashboard where nothing has happened yet — the state most likely to be faked. */
const EMPTY_DASHBOARD: Dashboard = {
  calls_today: 0,
  calls_7d: 0,
  leads_new_7d: 0,
  hot_leads_open: 0,
  avg_duration_s: null,
  sentiment_split: {},
  outcome_split: {},
  after_hours_captured_7d: 0,
  after_hours_basis: "default_window",
  minutes_used_month: null,
  daily_7d: [],
} as unknown as Dashboard;

/** Seven IST days, oldest first, as the API zero-fills them. */
const WEEK: Dashboard["daily_7d"] = [
  { ist_date: "2026-08-07", total: 4, completed: 3, no_answer: 1, failed: 0, in_flight: 0 },
  { ist_date: "2026-08-08", total: 0, completed: 0, no_answer: 0, failed: 0, in_flight: 0 },
  { ist_date: "2026-08-09", total: 6, completed: 4, no_answer: 1, failed: 1, in_flight: 0 },
  { ist_date: "2026-08-10", total: 0, completed: 0, no_answer: 0, failed: 0, in_flight: 0 },
  { ist_date: "2026-08-11", total: 2, completed: 2, no_answer: 0, failed: 0, in_flight: 0 },
  { ist_date: "2026-08-12", total: 9, completed: 7, no_answer: 1, failed: 1, in_flight: 0 },
  { ist_date: "2026-08-13", total: 3, completed: 1, no_answer: 0, failed: 0, in_flight: 2 },
];

const USAGE: UsagePanel = {
  month: "2026-08",
  minutes_used: "120.5",
  calls: 41,
  included_minutes: 500,
  overage_minutes: "0",
  overage_minutes_premium: "0",
  overage_minutes_value: "0",
  overage_cost_inr: "10159.00",
  overage_rate_inr: "6.5000",
  overage_rate_value_inr: null,
  monthly_fee_inr: "4999.00",
  cap_minutes: null,
  minutes_left: null,
  capped: false,
  spend_used_inr: "10159.00",
  plan_tier: "managed",
  credit_balance_inr: null,
} as unknown as UsagePanel;

const page = <DashboardPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/dashboard": EMPTY_DASHBOARD,
    "/v1/usage": USAGE,
    "/v1/calls?limit=6": [],
    ...over,
  };
}

describe("the dashboard renders what the server said, or says it could not", () => {
  it("shows a refusal instead of figures when the dashboard request fails", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/dashboard": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your call history.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // The specific mock figures the design shipped with. If any of them ever appears
    // again, a fallback has crept back in.
    for (const invented of ["5,430", "3,482", "2,317", "13.6%", "$0.042", "286"]) {
      expect(container.textContent, `invented figure on a failed dashboard: ${invented}`).not.toContain(
        invented,
      );
    }
  });

  it("renders a zero as zero rather than substituting a healthier number", async () => {
    const { container } = await renderClientPage(page, routes());

    const tile = (await screen.findByText("Calls today")).parentElement;
    expect(tile?.textContent).toContain("0");
    expect(container.textContent).not.toContain("5,430");
    expect(container.textContent).toContain("No calls yet");
  });

  it("never puts a caller's number on screen unmasked (hard rule 6)", async () => {
    const RAW = "+919876543210";
    const call = {
      id: "c1",
      agent_id: "a1",
      agent_name: "Reception",
      direction: "inbound",
      status: "completed",
      caller_masked: "+9198765•••10",
      started_at: "2026-08-13T04:30:00Z",
      duration_s: 92,
      outcome_tag: "booked",
      sentiment: "positive",
      summary: null,
      lead_id: null,
    } as unknown as CallSummary;

    const { container } = await renderClientPage(
      page,
      routes({ "/v1/calls?limit=6": [call] }),
    );

    expect(await screen.findByText("+9198765•••10")).toBeTruthy();
    expect(container.textContent).not.toContain(RAW);
    // Not merely "the raw string is absent" — the last ten digits in sequence are what
    // would identify the person, and a partial leak is still a leak.
    expect(container.textContent).not.toContain("9876543210");
  });

  it("says which definition of after-hours produced the number", async () => {
    const { container: guessed } = await renderClientPage(page, routes());
    // Wait for the query to answer before reading the DOM: these screens paint a
    // skeleton first, and an empty container would pass a `not.toContain` for the
    // wrong reason.
    await screen.findByText("Captured after hours");
    expect(guessed.textContent).toContain("add your opening hours");

    const { container: measured } = await renderClientPage(
      page,
      routes({
        "/v1/dashboard": { ...EMPTY_DASHBOARD, after_hours_basis: "business_hours" },
      }),
    );
    await screen.findByText("Using your recorded opening hours");
    expect(measured.textContent).toContain("Using your recorded opening hours");
    expect(measured.textContent).not.toContain("add your opening hours");
  });

  it("draws one column per IST day the API sent, silent days included", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/dashboard": { ...EMPTY_DASHBOARD, daily_7d: WEEK } }),
    );
    await screen.findByText("Calls each day");

    // Seven labels, including the two days nothing happened: a silent day is a fact
    // about that day, and dropping it would slide the week and misdate every bar.
    for (const label of ["7 Aug", "8 Aug", "9 Aug", "10 Aug", "11 Aug", "12 Aug", "13 Aug"]) {
      expect(container.textContent, `missing day label ${label}`).toContain(label);
    }

    // The date label is read out of the API's string, never through `new Date(...)`:
    // parsing "2026-08-13" gives midnight UTC, which renders as 12 Aug for a reader in
    // IST — the previous day's label over the correct day's bar.
    expect(container.textContent).not.toContain("6 Aug");
  });

  it("prints rupees from the string the API sent, without going through a float", async () => {
    const { container } = await renderClientPage(page, routes());
    await screen.findByText("Spend this month");
    // `Number("10159.00")` formats as 10,158.999999999998 on some paths; the exact
    // grouped string is the assertion, and the currency is INR, not the design's "$".
    expect(container.textContent).toContain("₹10,159.00");
    expect(container.textContent).not.toContain("$");
  });
});
