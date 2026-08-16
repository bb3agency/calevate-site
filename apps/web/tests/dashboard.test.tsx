import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DashboardPage from "@/app/c/[slug]/page";
import type { CallSummary, Dashboard, Me } from "@/lib/api/client";
import type { UsagePanel } from "@/lib/api/hooks";

import { browserOffline, problem, renderClientPage, stillLoading } from "./harness";

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
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

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
  // A decimal AS A STRING (hard rule 7) and required — never null. This fixture said
  // `null`, so the "minutes used" tile was only ever rendered in its absent state.
  minutes_used_month: "0",
  daily_7d: [],
};

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
};

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
    const call: CallSummary = {
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
    };

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

/**
 * "Spend this month" — the one tile on this screen fed by a SECOND query, and the one
 * that had no ladder of its own.
 *
 * `formatINR(usage.data?.overage_cost_inr)` returns "—" for undefined, which is honest
 * for a moment and a lie forever: on a failed `/v1/usage` the money tile sat at "—" with
 * no skeleton, no notice and no way to retry, so an owner could not tell "nothing billed
 * yet" from "we could not read it". §52's first two clauses, on the tile that decides
 * whether somebody rings us about their bill.
 */
describe("the money tile says which kind of nothing it is showing", () => {
  it("refuses, rather than sitting on a dash, when the usage read fails", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/usage": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your usage.",
        }),
      }),
    );

    // The refusal is PRESENT, retryable, and IN THE TILE — "no rupee figure" is also
    // true of a blank card, and an alert somewhere else on the page is not this tile
    // explaining itself. Awaited on the ALERT rather than on the tile heading, which is
    // on screen during the loading branch as well.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("We could not read your usage");
    expect(alert.closest("section")?.querySelector("h2")?.textContent).toBe("Spend this month");
    expect(container.textContent).not.toContain("₹");
    // The rest of the screen is unaffected: this tile's failure is not the page's.
    expect(container.textContent).toContain("Calls today");
  });

  it("shows a skeleton, not a dash, while the usage read is in flight", async () => {
    const { container } = await renderClientPage(page, routes({ "/v1/usage": stillLoading() }));

    // Scoped to the tile: this page has other skeletons, and a page-level count would
    // pass on any one of them.
    const tile = (await screen.findByText("Spend this month")).closest("section");
    expect(
      tile!.querySelectorAll(".animate-pulse").length,
      "no skeleton in the Spend tile while /v1/usage is in flight",
    ).toBeGreaterThan(0);
    expect(container.textContent).not.toContain("₹");
  });

  it("says it is loading, and not only draws it", async () => {
    // §52's first clause has an audience the pixels do not reach. `Skeleton` rendered
    // `<div aria-hidden>` of pulsing bars and nothing else, so across ~96 sites a
    // screen-reader user got SILENCE during every load — and silence and "there is
    // nothing here" are the same thing in that modality. `tests/a11y.ts:42` says out loud
    // that the axe sweep cannot see this: axe checks markup that exists, not an
    // announcement that never happens, so it is asserted here.
    await renderClientPage(page, routes({ "/v1/usage": stillLoading() }));

    const tile = (await screen.findByText("Spend this month")).closest("section")!;
    const live = tile.querySelector('[role="status"]');
    expect(live, "the skeleton is not a live region, so nothing is announced").not.toBeNull();
    expect(live!.getAttribute("aria-live")).toBe("polite");
    expect(live!.textContent).toContain("Loading");
    // …and the bars stay out of the accessibility tree: they are the drawing of that
    // sentence, and reading them out is an announcement of nothing, per row.
    expect(tile.querySelector(".animate-pulse")!.closest("[aria-hidden]")).not.toBeNull();
  });

  /**
   * THE PAUSED QUERY — the state that is neither loading nor failed.
   *
   * TanStack does not start a fetch it believes cannot succeed: with the default
   * `networkMode: "online"` it parks the query (`fetchStatus: "paused"`), so
   * `isLoading` — which is `isPending && isFetching` — is FALSE, `error` is null and
   * `data` is undefined. A two-armed ladder therefore walks past both arms into its data
   * branch with nothing in it. `browserOffline()` flips the library's own switch rather
   * than mocking anything, so this is the branch a dropped connection actually produces.
   */
  it("states nothing about the business over a read the browser never made", async () => {
    browserOffline();
    const { container } = await renderClientPage(page, routes());

    // Neither empty state, and no tile pretending to a figure.
    expect(container.textContent).not.toContain("No call history yet");
    expect(container.textContent).not.toContain("No calls yet");
    expect(container.textContent).toContain("We could not reach Calevate");
  });

});
