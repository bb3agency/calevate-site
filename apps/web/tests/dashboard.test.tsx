import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DashboardPage from "@/app/c/[slug]/page";
import type { Stats } from "@/lib/api/analytics";
import type { CallSummary, Dashboard, Me } from "@/lib/api/client";
import type { AccountReadiness } from "@/lib/api/readiness";
import type { UsagePanel } from "@/lib/api/hooks";
import type { Wallet } from "@/lib/api/wallet";

import { activeTrialBlock, agentRow } from "./fixtures/sharedReads";
import {
  NO_BUSINESS_COPY,
  browserOffline,
  problem,
  renderClientPage,
  stillLoading,
} from "./harness";
import { businessProfileFixture } from "./businessProfileFixture";
import { NO_FORWARDING_ROUTES } from "./fixtures/forwarding";
import { COST_PER_RESULT, COST_PER_RESULT_ROUTE } from "./fixtures/proof";

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
 * 3. The recent-calls rail prints `caller_e164` in full (D-436) and never puts it in a
 *    URL — the rail is the fastest route from "somebody rang" to ringing them back, and
 *    a link target is still the one place a number may not go (hard rule 6).
 * 4. The after-hours tile says WHICH definition produced its number, because a guess
 *    and a fact must not render identically (`after_hours_basis`).
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

/** A dashboard where nothing has happened yet — the state most likely to be faked. */
const EMPTY_DASHBOARD: Dashboard = {
  calls_today: 0,
  calls_7d: 0,
  leads_new_7d: 0,
  hot_leads_open: 0,
  calls_prev_7d: 0,
  calls_connected_7d: 0,
  calls_not_connected_7d: 0,
  leads_new_prev_7d: 0,
  avg_duration_s_7d: null,
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
  {
    ist_date: "2026-08-07",
    total: 4,
    completed: 3,
    no_answer: 1,
    failed: 0,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-08",
    total: 0,
    completed: 0,
    no_answer: 0,
    failed: 0,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-09",
    total: 6,
    completed: 4,
    no_answer: 1,
    failed: 1,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-10",
    total: 0,
    completed: 0,
    no_answer: 0,
    failed: 0,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-11",
    total: 2,
    completed: 2,
    no_answer: 0,
    failed: 0,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-12",
    total: 9,
    completed: 7,
    no_answer: 1,
    failed: 1,
    in_flight: 0,
  },
  {
    ist_date: "2026-08-13",
    total: 3,
    completed: 1,
    no_answer: 0,
    failed: 0,
    in_flight: 2,
  },
];

/** The last 7 IST days against the 7 before, as `/v1/analytics/stats` sends them. */
function stats(
  over: Partial<Record<Stats["metrics"][number]["key"], Partial<Stats["metrics"][number]>>> = {},
): Stats {
  const metric = (
    key: Stats["metrics"][number]["key"],
    value: string | null,
    previous: string | null,
    change: string | null,
    higher = true,
  ) => ({ key, value, previous, change_pct: change, higher_is_better: higher, ...over[key] });
  return {
    window: { days: 7, from_date: "2026-08-07", to_date: "2026-08-13", timezone: "Asia/Kolkata" },
    previous_window: { days: 7, from_date: "2026-07-31", to_date: "2026-08-06", timezone: "Asia/Kolkata" },
    metrics: [
      metric("calls", "0", "0", null),
      metric("answered", "0", "0", null),
      metric("answer_rate_pct", null, null, null),
      metric("leads", "0", "0", null),
      metric("hot_leads", "0", "0", null),
      metric("avg_duration_s", null, null, null),
      metric("talk_minutes", "0.0", "0.0", null),
    ],
  };
}

/** No agent scored yet: the account's readiness read with nothing on the roster. */
const NO_READINESS: AccountReadiness = {
  score: null,
  agents: [],
  top_fixes: [],
  computed_at: "2026-08-13T05:00:00Z",
};

const USAGE: UsagePanel = {
  month: "2026-08",
  minutes_used: "120.5",
  calls: 41,
  // Both voice qualities, always, named by the server (D-547).
  clear_minutes: "120.50",
  clear_charges_inr: "602.50",
  clear_label: "Clear",
  studio_minutes: "0.00",
  studio_charges_inr: "0.00",
  studio_label: "Studio",
  included_minutes: 500,
  overage_minutes: "0",
  // BOTH SPELLINGS: the wire carries the deprecated pair beside the new one
  // for one release (hard rule 8 step 1, D-558), with identical figures.
  overage_minutes_base_rung: "0",
  overage_minutes_second_rung: "0",
  overage_minutes_premium: "0",
  overage_minutes_value: "0",
  overage_cost_inr: "10159.00",
  overage_rate_inr: "6.5000",
  overage_rate_second_inr: null,
  overage_rate_value_inr: null,
  // D-455: the model surcharge, unset on every plan today.
  llm_surcharge_rate_inr: null,
  llm_surcharge_minutes: "0.00",
  llm_surcharge_inr: "0.00",
  llm_surcharge_tiers: [],
  monthly_fee_inr: "4999.00",
  // The server's total: ₹4,999.00 retainer + ₹10,159.00 overage + ₹0.00 upgrade.
  month_charges_inr: "15158.00",
  cap_minutes: null,
  minutes_left: null,
  capped: false,
  spend_used_inr: "10159.00",
  trial: { active: false, days_remaining: null, ends_at: null },
  trial_absorbed_inr: "0.00",
  plan_tier: "managed",
  credit_balance_inr: null,
};

/**
 * A prepaid wallet with money on it — the state most accounts are in, now that prepaid is
 * what an account gets unless an operator deliberately puts it on a retainer.
 */
function wallet(over: Partial<Wallet> = {}): Wallet {
  return {
    tenant_id: "o1",
    prepaid: true,
    balance_inr: "3400.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    low_balance_alert_chosen: false,
    granted_inr: "0.00",
    paid_inr: "2500.00",
    trial: null,
    outbound_stopped: false,
    runway: {
      basis: "projected",
      days: 10,
      daily_burn_inr: "340.00",
      history_days: 30,
      beyond_horizon: false,
      window_days: 30,
      min_history_days: 7,
      max_days: 365,
    },
    // Per QUALITY since D-547: one balance over one live rate is wrong for every
    // client whose lots were not bought at today's card.
    minutes_left: [
      { voice_tier: "clear", label: "Clear", minutes: 240 },
      { voice_tier: "studio", label: "Studio", minutes: 171 },
    ],
    drawdown: {
      calls_inr: "8400.00",
      ai_assist_inr: "0.00",
      number_rental_inr: "0.00",
      adjustments_inr: "0.00",
      spent_inr: "8400.00",
      added_inr: "12100.00",
      refunded_inr: "0.00",
      expired_inr: "0.00",
    },
    ...over,
  };
}

const page = <DashboardPage params={Promise.resolve({ slug: "acme" })} />;

/**
 * EVERY read the screen makes, answered. An unanswered route is not a neutral default:
 * the harness throws, the app renders a transport-failure `role="alert"`, and a test
 * asserting on "the" alert then passes or fails on which of two failures resolved first.
 * The attention queue and the knowledge-gaps card were both missing here, so every test
 * in this file rendered two failures it was not about. `setup.ts` now fails any test that
 * leaves a read unanswered; the fixture test below also pins that none of them alerts.
 */
/** `GET /v1/go-live` for an account owed no guide: it has not paid (D-859). */
const NOT_OWED_GUIDE = {
  due: false,
  owed_at: null,
  finished_at: null,
  dismissed_at: null,
  current: "move",
  move: { state: "waiting_for_account", agents: [], total: 0 },
  verify: "todo",
  number: "locked",
  numbers: 0,
  switch_on: "todo",
  live_agents: 0,
};

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    ...NO_FORWARDING_ROUTES,
    "/v1/dashboard": EMPTY_DASHBOARD,
    // No charts pinned from the assistant (D-934): the section renders nothing.
    "/v1/copilot/pins": { pins: [], max_pins: 12 },
    // An account that has not paid is owed no go-live guide (D-859).
    "/v1/go-live": NOT_OWED_GUIDE,
    // A first run put aside: the dashboard neither sends the owner on nor hides the checklist.
    "/v1/first-run": {
      due: false,
      jobs: [],
      questions: { status: "idle", items: [], disclosure: null },
      build: { status: "idle", steps: [], disclosure: null, builds_left: 3 },
    },
    "/v1/usage": USAGE,
    "/v1/billing/wallet": wallet(),
    "/v1/calls?limit=6": [],
    "/v1/agents": [],
    "/v1/agents/stats": [],
    "/v1/campaigns": [],
    "/v1/campaigns/numbers": [],
    "/v1/attention": { counts: {}, items: [], total: 0 },
    "/v1/knowledge-gaps?status=open&limit=20": { items: [], open_count: 0, total: 0 },
    "/v1/business-profile": businessProfileFixture(),
    "/v1/healer/incidents?days=30&limit=20": { open: 0, items: [] },
    "/v1/business-copy": NO_BUSINESS_COPY,
    "/v1/analytics/stats": stats(),
    "/v1/readiness": NO_READINESS,
    // D-944: the owner's daily summary (already on, so no offer) and rupees per result.
    "/v1/notifications/daily-summary": { enabled: true, email_addresses: 1, whatsapp: false },
    [COST_PER_RESULT_ROUTE]: COST_PER_RESULT,
    ...over,
  };
}


describe("the fixture this file renders against", () => {
  it("answers every read the screen makes, so no test inherits a failure it is not about", async () => {
    const table = routes();
    const { calls, container } = await renderClientPage(page, table);
    // Settled means no skeleton left anywhere: every read has answered or failed.
    await waitFor(() => expect(container.querySelector(".animate-pulse")).toBeNull());
    const unanswered = calls
      .filter((c) => !Object.hasOwn(table, c.path) && !c.path.startsWith("/v1/auth/"))
      .map((c) => `${c.method} ${c.path}`);
    expect(unanswered).toEqual([]);
    expect(container.querySelectorAll('[role="alert"]').length).toBe(0);
  });
});

describe("the home screen ranks the day's work (ux-audit D2)", () => {
  it("links to Needs attention when something is waiting, with the server's count", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": { counts: { lead_blocked: 3 }, items: [], total: 3 },
      }),
    );
    const link = await screen.findByRole("link", {
      name: /things need you/,
    });
    expect(link.getAttribute("href")).toContain("/c/acme/attention");
    expect(container.textContent).toContain("3");
  });

  it("says nothing about the queue on zero, and says it could not check on a failure", async () => {
    // Zero: a banner about nothing is noise.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/attention": { counts: {}, items: [], total: 0 } }),
    );
    await screen.findByRole("heading", { name: "This week" });
    expect(container.textContent).not.toContain("needs your attention");
    expect(container.textContent).not.toContain("could not check");

    // UNMOUNT BEFORE RENDERING THE SECOND CASE. Testing-library cleans up BETWEEN tests,
    // not within one, so without this the zero-case app stays mounted while the failure
    // case renders beside it — one test holding two whole dashboards. It cost this test
    // four intermittent failures in a single day, in TWO different disguises: a
    // "Found multiple elements" when a document-wide query
    // matched both trees, and a `waitFor` TIMEOUT when the second render had to settle
    // against twice the DOM under a loaded CPU. Both read as flakiness, both passed
    // standalone every time, and both were called contention — by three separate readers,
    // me included — before anyone noticed the test was simply doing twice the work it
    // needed to. The assertions above have already read `container`; nothing below wants
    // it.
    cleanup();

    // Failed: NOT an all-clear. Dropping the banner silently would offer the client
    // neither the action nor a reason for its absence, which is the defect BUILD-LOG
    // §52 exists for (and `surfaceStatesGuard` enforces): failure is a refusal, never
    // an empty state. It names what could not be read and offers the retry.
    const failed = await renderClientPage(
      page,
      routes({
        "/v1/attention": problem(503, { title: "Service unavailable" }),
      }),
    );
    // SCOPED, like the `Try again` assertion below and for its stated reason: the
    // zero-case render above is still mounted, so `screen.findByText` matches BOTH and
    // throws "Found multiple elements". It did — intermittently, four times in one day,
    // once per full-suite run and never standalone, which reads exactly like CPU
    // contention and was misdiagnosed as such three times before somebody read the two
    // queries side by side. The comment six lines down already knew the rule; it just
    // was not applied one line up.
    await within(failed.container).findByRole("heading", { name: "This week" });
    expect(failed.container.textContent).toContain(
      "Couldn't check your to-do list",
    );
    // `findAllByRole`, because a transport-level failure banner carries its own "Try
    // again" and the singular query throws on two matches rather than on an absent one —
    // which is how this assertion kept failing for a reason that was never about the page.
    // What it asserts is unchanged: the refusal offers a retry.
    expect(
      (await within(failed.container).findAllByRole("button", { name: "Try again" })).length,
    ).toBeGreaterThan(0);
  });
});

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
    for (const invented of [
      "5,430",
      "3,482",
      "2,317",
      "13.6%",
      "$0.042",
      "286",
    ]) {
      expect(
        container.textContent,
        `invented figure on a failed dashboard: ${invented}`,
      ).not.toContain(invented);
    }
  });

  it("renders a zero as zero rather than substituting a healthier number", async () => {
    const { container } = await renderClientPage(page, routes());

    // A week with no calls is said as none, not drawn as a healthier number.
    const week = (await screen.findByRole("heading", { name: "This week" })).closest("section");
    expect(week?.textContent).toContain("No calls this week");
    expect(container.textContent).not.toContain("5,430");
    expect(container.textContent).toContain("No calls yet");
  });

  it("prints the caller's number and keeps it out of every link target", async () => {
    const PHONE = "+919876543210";
    const call: CallSummary = {
      id: "c1",
      agent_id: "a1",
      agent_name: "Reception",
      direction: "inbound",
      status: "completed",
      caller_e164: PHONE,
      started_at: "2026-08-13T04:30:00Z",
      duration_s: 92,
      outcome_tag: "call_back_booked",
      summary_state: "empty",
      test_call: false,
      sentiment: "positive",
      summary: null,
      lead_id: null,
    };

    const { container } = await renderClientPage(
      page,
      routes({ "/v1/calls?limit=6": [call] }),
    );

    // WAS `not.toContain(RAW)`. D-436 reversed it: the rail exists to be acted on.
    // Printed grouped for reading (`formatPhone`); the E.164 form stays the value.
    expect(await screen.findByText("+91 98765 43210")).toBeTruthy();
    // The half that did NOT change — URLs reach logs, referrers and browser history.
    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toContain("9876543210");
    }
  });

  it("shows what each recent call captured and, for an owner, what it cost", async () => {
    const call: CallSummary = {
      id: "c2",
      agent_id: "a1",
      agent_name: "Reception",
      direction: "inbound",
      status: "completed",
      caller_e164: "+919876543211",
      started_at: "2026-08-13T04:30:00Z",
      duration_s: 92,
      outcome_tag: "answered",
      summary_state: "ready",
      test_call: false,
      sentiment: "positive",
      summary: "Asked about rice.",
      lead_id: null,
      credits_used_inr: "12.50",
      captured_preview: [
        { label: "What they want", value: "Two kilos of rice" },
        { label: "Preferred time", value: "Saturday" },
      ],
    };

    await renderClientPage(page, routes({ "/v1/calls?limit=6": [call] }));

    expect(
      await screen.findByText("What they want: Two kilos of rice · Preferred time: Saturday"),
    ).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Cost" })).toBeTruthy();
    expect(screen.getByText("₹12.5")).toBeTruthy();
  });

  it("shows no cost column when the server sent no cost, as it does for staff", async () => {
    const call: CallSummary = {
      id: "c3",
      agent_id: "a1",
      agent_name: "Reception",
      direction: "inbound",
      status: "completed",
      caller_e164: "+919876543212",
      started_at: "2026-08-13T04:30:00Z",
      duration_s: 30,
      outcome_tag: "answered",
      summary_state: "empty",
      test_call: false,
      sentiment: null,
      summary: null,
      lead_id: null,
    };

    await renderClientPage(page, routes({ "/v1/calls?limit=6": [call] }));

    expect(await screen.findByText("+91 98765 43212")).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Cost" })).toBeNull();
  });

  it("says which definition of after-hours produced the number", async () => {
    const { container: guessed } = await renderClientPage(page, routes());
    // Wait for the query to answer before reading the DOM: these screens paint a
    // skeleton first, and an empty container would pass a `not.toContain` for the
    // wrong reason.
    await screen.findByText("Captured after hours");
    expect(guessed.textContent).toContain("Using 9am–9pm");
    // The fix is a button to the hours step of business setup, offered only to a role that
    // may edit it: this reader holds no `org:manage`.
    expect(screen.queryByRole("link", { name: "Add your hours" })).toBeNull();
    cleanup();
    await renderClientPage(page, routes({ "/v1/me": { ...ME, permissions: [...ME.permissions, "org:manage"] } }));
    expect((await screen.findByRole("link", { name: "Add your hours" })).getAttribute("href")).toBe(
      "/c/acme/setup?step=hours",
    );
    cleanup();

    const { container: measured } = await renderClientPage(
      page,
      routes({
        "/v1/dashboard": {
          ...EMPTY_DASHBOARD,
          after_hours_basis: "business_hours",
        },
      }),
    );
    await screen.findByText("Using your opening hours");
    expect(measured.textContent).toContain("Using your opening hours");
    expect(measured.textContent).not.toContain("Add your hours");
  });

  it("draws one column per IST day the API sent, silent days included", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/dashboard": { ...EMPTY_DASHBOARD, daily_7d: WEEK } }),
    );
    await screen.findByRole("heading", { name: "Calls each day" });

    // Seven labels, including the two days nothing happened: a silent day is a fact
    // about that day, and dropping it would slide the week and misdate every bar.
    for (const label of [
      "7 Aug",
      "8 Aug",
      "9 Aug",
      "10 Aug",
      "11 Aug",
      "12 Aug",
      "13 Aug",
    ]) {
      expect(container.textContent, `missing day label ${label}`).toContain(
        label,
      );
    }

    // The date label is read out of the API's string, never through `new Date(...)`:
    // parsing "2026-08-13" gives midnight UTC, which renders as 12 Aug for a reader in
    // IST — the previous day's label over the correct day's bar.
    expect(container.textContent).not.toContain("6 Aug");
  });

  it("prints rupees from the string the API sent, without going through a float", async () => {
    const { container } = await renderClientPage(page, routes());
    await screen.findByText("Spend this month");
    // The RETAINER PLUS the extra minutes: ₹4,999.00 + ₹10,159.00. The tile used to print
    // `overage_cost_inr` alone under the word "spend", which was a fraction of the month
    // wearing the label of the whole of it.
    //
    // `Number("10159.00")` formats as 10,158.999999999998 on some paths; the exact
    // grouped string is the assertion, and the currency is INR, not the design's "$".
    expect(container.textContent).toContain("₹15,158");
    expect(container.textContent).not.toContain("$");
  });

  /**
   * THE MODEL UPGRADE IS PART OF WHAT THIS MONTH COST (D-455), ON THE HOME SCREEN TOO.
   *
   * The sharp case is an account INSIDE its minute allowance: `overage_cost_inr` is
   * ₹0.00, so the tile as it stood said "Spend this month ₹0.00" while the invoice
   * carried an "AI model upgrade" line for the dearer model the client had chosen. The
   * fixture is exactly that shape, and the figure asserted is the retainer plus the
   * surcharge with no overage in it at all.
   */
  it("includes the model surcharge for an account inside its allowance", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/usage": {
          ...USAGE,
          overage_minutes: "0",
          overage_cost_inr: "0.00",
          llm_surcharge_rate_inr: "1.5000",
          llm_surcharge_minutes: "120.50",
          llm_surcharge_inr: "180.75",
          llm_surcharge_tiers: ["Plus"],
          // ₹4,999.00 retainer + ₹180.75 upgrade, and NO overage — the whole point of
          // this case is that the total is neither ₹0.00 nor the retainer alone.
          month_charges_inr: "5179.75",
        },
      }),
    );

    await screen.findByText("Spend this month");
    // ₹4,999.00 retainer + ₹180.75 upgrade. Never ₹4,999.00, and never ₹0.00.
    expect(container.textContent).toContain("₹5,179.8");
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
describe("a held number (D-860)", () => {
  const held = (release_at: string | null) => ({
    id: "number-held",
    e164: "+918012345671",
    series: "standard",
    dlt_status: "pending",
    supplied_by_us: true,
    answerable: false,
    agent_id: null,
    direction: "both",
    held: true,
    release_at,
  });

  it("leads with calls stopped and the IST release day, with credit the one action", async () => {
    await renderClientPage(page, routes({ "/v1/campaigns/numbers": [held("2026-11-06T18:30:00Z")] }));
    expect(await screen.findByText("Calls stopped. Top up to keep your number.")).toBeTruthy();
    expect(screen.getByText("Released on Saturday, 7 November.")).toBeTruthy();
    expect(screen.getByText("Once released, we can't get it back.")).toBeTruthy();
    const links = screen.getAllByRole("link", { name: "Add credit" });
    expect(links.some((link) => link.getAttribute("href")?.endsWith("/billing?tab=credits"))).toBe(true);
  });

  it("names the earliest day when several numbers are held", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/campaigns/numbers": [
          { ...held("2026-11-09T18:30:00Z"), id: "n2" },
          held("2026-11-06T18:30:00Z"),
        ],
      }),
    );
    expect(await screen.findByText("Calls stopped. Top up to keep your numbers.")).toBeTruthy();
    expect(screen.getByText("The first is released on Saturday, 7 November.")).toBeTruthy();
  });

  it("says it could not check, rather than nothing, when the numbers do not load", async () => {
    await renderClientPage(page, routes({ "/v1/campaigns/numbers": problem(503) }));
    expect(
      await screen.findByText("Couldn't check your numbers"),
    ).toBeTruthy();
  });

  it("says nothing when no number is held", async () => {
    await renderClientPage(page, routes());
    expect(screen.queryByText(/^Calls stopped\./)).toBeNull();
  });
});

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
    const tile = alert.closest("section");
    expect(tile?.querySelector("h2")?.textContent).toBe("Spend this month");
    // SCOPED TO THIS TILE, not to the page: the calling-credit tile beside it is a
    // different read that succeeded, and its balance is not this tile's failure.
    expect(tile?.textContent).not.toContain("₹");
    // The rest of the screen is unaffected: this tile's failure is not the page's.
    expect(container.textContent).toContain("This week");
  });

  it("shows a skeleton, not a dash, while the usage read is in flight", async () => {
    await renderClientPage(page, routes({ "/v1/usage": stillLoading() }));

    // Scoped to the tile: this page has other skeletons, and a page-level count would
    // pass on any one of them.
    const tile = (await screen.findByText("Spend this month")).closest(
      "section",
    );
    expect(
      tile!.querySelectorAll(".animate-pulse").length,
      "no skeleton in the Spend tile while /v1/usage is in flight",
    ).toBeGreaterThan(0);
    // Scoped for the same reason as the refusal above: a rupee figure elsewhere on the
    // page belongs to a read that answered.
    expect(tile!.textContent).not.toContain("₹");
  });

  it("says it is loading, and not only draws it", async () => {
    // §52's first clause has an audience the pixels do not reach. `Skeleton` rendered
    // `<div aria-hidden>` of pulsing bars and nothing else, so across ~96 sites a
    // screen-reader user got SILENCE during every load — and silence and "there is
    // nothing here" are the same thing in that modality. `tests/a11y.ts:42` says out loud
    // that the axe sweep cannot see this: axe checks markup that exists, not an
    // announcement that never happens, so it is asserted here.
    await renderClientPage(page, routes({ "/v1/usage": stillLoading() }));

    const tile = (await screen.findByText("Spend this month")).closest(
      "section",
    )!;
    const live = tile.querySelector('[role="status"]');
    expect(
      live,
      "the skeleton is not a live region, so nothing is announced",
    ).not.toBeNull();
    expect(live!.getAttribute("aria-live")).toBe("polite");
    expect(live!.textContent).toContain("Loading");
    // …and the bars stay out of the accessibility tree: they are the drawing of that
    // sentence, and reading them out is an announcement of nothing, per row.
    expect(
      tile.querySelector(".animate-pulse")!.closest("[aria-hidden]"),
    ).not.toBeNull();
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
    expect(container.textContent).toContain("If it keeps happening, contact us.");
  });
});

/**
 * CALLING CREDIT ON THE HOME SCREEN.
 *
 * The dashboard showed what the month has COST and nothing about what is left to spend,
 * which was the right pair while every account was invoiced against a retainer and no
 * balance could stop anything. Prepaid is now what an account gets unless an operator
 * deliberately says otherwise, so the number that decides whether the product works
 * tomorrow belongs on the screen a client opens first — and the first they hear of an
 * empty wallet must not be a campaign that did not go out.
 */
describe("the calling credit tile", () => {
  it("shows the balance the server sent, with somewhere to act on it", async () => {
    await renderClientPage(page, routes());

    const tile = (await screen.findByText("Calling credit left")).parentElement;
    expect(tile?.textContent).toContain("₹3,400");
    const link = within(tile as HTMLElement).getByRole("link");
    expect(link.getAttribute("href")).toContain("/c/acme/billing?tab=credits");
  });

  it("says what stopped and what did not when the wallet is empty", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": wallet({
          balance_inr: "0.00",
          is_low: true,
          outbound_stopped: true,
          minutes_left: [
            { voice_tier: "clear", label: "Clear", minutes: 0 },
            { voice_tier: "studio", label: "Studio", minutes: 1 },
          ],
        }),
      }),
    );

    const tile = (await screen.findByText("Calling credit left")).parentElement;
    // NEVER THE FIGURE ALONE. "₹0.00" on a dashboard is a number a skimming owner reads
    // past; "calls have stopped" is not — and since D-551 the INCOMING half travels with
    // it, because a client who does not know their phone has gone quiet loses a day.
    expect(tile?.textContent).toContain(
      "Calls in and out stopped. Add credit",
    );
    expect(tile?.textContent).not.toContain("still get through");
  });

  it("shows an invoiced account no balance at all", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": wallet({ prepaid: false, minutes_left: null }),
      }),
    );

    await screen.findByRole("heading", { name: "This week" });
    // A tenant with no wallet is not a tenant whose wallet is empty. A zero here would be
    // the same false alarm the credit screen refuses to raise.
    expect(container.textContent).not.toContain("Calling credit left");
  });

  it("says calls are on us until the trial ends instead of warning about a low balance", async () => {
    /* The founder's screenshot (7 Oct 2026): a trial running, ₹0.00 in the wallet, and the
       tile said "Running low — top up before outgoing calls stop" — false, because during
       a trial an empty wallet stops nothing (D-536). */
    await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": wallet({
          balance_inr: "0.00",
          is_low: true,
          outbound_stopped: false,
          minutes_left: null,
          trial: activeTrialBlock(),
        }),
      }),
    );

    const tile = (await screen.findByText("Calling credit left")).parentElement;
    expect(tile?.textContent).toContain(
      "Free trial until 10 Oct, 10:58 pm IST",
    );
    expect(tile?.textContent).not.toContain("Running low");
    expect(tile?.textContent).not.toContain("stopped");
  });

  it("asks for a top-up on the last day of the trial", async () => {
    const endsAt = new Date(Date.now() + 5 * 3_600_000).toISOString();
    await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": wallet({
          balance_inr: "0.00",
          is_low: true,
          minutes_left: null,
          trial: activeTrialBlock({ days_remaining: 1, ends_at: endsAt }),
        }),
      }),
    );

    const tile = (await screen.findByText("Calling credit left")).parentElement;
    expect(tile?.textContent).toMatch(/Trial: (5|6) hours left\. Add credit/);
    expect(within(tile as HTMLElement).getByRole("link", { name: /Add credit/ })).toBeTruthy();
  });

  it("says this month's calling is free during a trial, and what it was worth", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/usage": {
          ...USAGE,
          month_charges_inr: "0.00",
          trial: { active: true, days_remaining: 3, ends_at: "2026-10-10T17:28:00Z" },
          trial_absorbed_inr: "602.50",
        },
      }),
    );

    const tile = (await screen.findByText("Spend this month")).parentElement;
    expect(tile?.textContent).toContain("₹0");
    expect(tile?.textContent).toContain("120.5 min free in trial (worth ₹602.5)");
  });

  it("refuses rather than printing a dash when the balance cannot be read", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/billing/wallet": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your balance just now.",
        }),
      }),
    );

    await screen.findByText("We could not read your balance just now.");
    // A failed read is not an empty wallet, and it is certainly not a stopped account.
    expect(container.textContent).not.toContain("Outgoing calls have stopped");
  });
});

describe("this week", () => {
  /** An owner: may add credit, create agents and run campaigns. */
  const OWNER: Me = { ...ME, permissions: ["calls:read", "leads:read", "org:manage", "leads:dispatch"] };

  async function recap(over: Record<string, unknown>) {
    await renderClientPage(page, routes({ "/v1/me": OWNER, ...over }));
    const heading = await screen.findByRole("heading", { name: "This week" });
    const card = heading.closest("section") as HTMLElement;
    return card;
  }

  /** The card's buttons, in order; the first is the filled primary. */
  async function actions(card: HTMLElement) {
    // `/v1/me` answers after the dashboard, so wait for the permission-gated buttons.
    await waitFor(() => expect(within(card).queryAllByRole("link").length).toBeGreaterThan(0));
    return within(card)
      .getAllByRole("link")
      .filter((link) => link.className.includes("rounded-md"))
      .map((link) => ({ name: link.textContent, primary: link.className.includes("bg-brand-strong") }));
  }

  /** One figure of the band: its label's parent holds the value, the change and the hint. */
  async function figure(card: HTMLElement, label: string) {
    return ((await within(card).findByText(label)).parentElement?.textContent ?? "").replace(/\s+/g, " ");
  }

  const BUSY_WEEK = {
    ...EMPTY_DASHBOARD,
    calls_today: 4,
    calls_7d: 29,
    calls_prev_7d: 17,
    calls_connected_7d: 20,
    calls_not_connected_7d: 7,
    leads_new_7d: 6,
    leads_new_prev_7d: 2,
    avg_duration_s_7d: 94,
    daily_7d: WEEK,
  };

  it("reads a busy week as the page's one block of figures, each against the week before", async () => {
    const card = await recap({
      "/v1/dashboard": BUSY_WEEK,
      "/v1/analytics/stats": stats({
        calls: { value: "29", previous: "17", change_pct: "70.6" },
        answer_rate_pct: { value: "69.0", previous: "64.5" },
        leads: { value: "6", previous: "2", change_pct: "200.0" },
        avg_duration_s: { value: "94", previous: "120", change_pct: "-21.7" },
      }),
      "/v1/agents": [agentRow()],
      "/v1/campaigns": [{ id: "c1", name: "Recall", status: "completed" }],
    });
    expect(await figure(card, "Calls")).toContain("29↑ +70.6% vs the previous 7 days");
    // A rate moves in points, not as a percentage of a percentage.
    expect(await figure(card, "Answer rate")).toContain("69%↑ +4.5 points");
    expect(await figure(card, "New leads")).toContain("6↑ +200%");
    expect(await figure(card, "Average call length")).toContain("1:34↓ −21.7%");
    // Nothing urgent: the week's calls lead; an inbound agent cannot dial, so no campaign.
    expect(await actions(card)).toEqual([
      { name: "See calls", primary: true },
      { name: "Add credit", primary: false },
      { name: "Add an agent", primary: false },
    ]);
  });

  it("does not invent a comparison in a first week", async () => {
    const card = await recap({
      "/v1/dashboard": { ...EMPTY_DASHBOARD, calls_7d: 8, calls_connected_7d: 8 },
      "/v1/analytics/stats": stats({ calls: { value: "8", previous: "0", change_pct: null } }),
      "/v1/agents": [agentRow()],
    });
    expect(await figure(card, "Calls")).toContain("None in the previous 7 days");
    expect(card.textContent).not.toContain("vs the previous 7 days");
  });

  it("says the figures could not load rather than showing zeros", async () => {
    const card = await recap({
      "/v1/dashboard": BUSY_WEEK,
      "/v1/analytics/stats": problem(503, { title: "Service unavailable" }),
      "/v1/agents": [agentRow()],
    });
    await within(card).findByRole("alert");
    expect(within(card).queryByText("Calls")).toBeNull();
  });

  it("says a quiet week in a few chips instead of a row of zeroes", async () => {
    const card = await recap({
      "/v1/dashboard": { ...EMPTY_DASHBOARD, calls_prev_7d: 5 },
      "/v1/agents": [agentRow()],
    });
    expect(card.textContent).toContain("No calls this week");
    expect(card.textContent).toContain("5 calls last week");
    expect(within(card).queryByText("Connected")).toBeNull();
    // Nothing calls for an action, so nothing is filled.
    expect(await actions(card)).toEqual([
      { name: "Add credit", primary: false },
      { name: "Add an agent", primary: false },
    ]);
  });

  it("leads with creating an agent when there is none", async () => {
    const card = await recap({ "/v1/agents": [] });
    expect(card.textContent).toContain("No agent yet");
    const buttons = await actions(card);
    expect(buttons[0]).toEqual({ name: "Meet your agent", primary: true });
    expect(buttons.map((b) => b.name)).not.toContain("Open campaigns");
  });

  it("invites an owner with no agent to meet their first one (D-855)", async () => {
    await recap({ "/v1/agents": [] });
    const invite = (await screen.findByRole("heading", { name: "Meet your agent", level: 2 })).closest(
      "section",
    ) as HTMLElement;
    expect(within(invite).getByRole("link", { name: /Build my agent/ }).getAttribute("href")).toBe("/c/acme/agents/first");
  });

  it("offers a first run already begun before any setup list", async () => {
    await recap({
      "/v1/agents": [],
      "/v1/first-run": {
        due: true,
        jobs: ["answer_calls"],
        questions: { status: "idle", items: [], disclosure: null },
        build: { status: "idle", steps: [], disclosure: null, builds_left: 3 },
      },
    });
    const invite = (await screen.findByRole("heading", { name: "Meet your agent", level: 2 })).closest(
      "section",
    ) as HTMLElement;
    expect(await within(invite).findByRole("link", { name: /Continue/ })).toBeTruthy();
    expect(screen.queryByText(/Set up your business/)).toBeNull();
  });

  it("leads with the agent when none is switched on", async () => {
    const card = await recap({
      "/v1/agents": [agentRow({ status: "paused" })],
    });
    const buttons = await actions(card);
    expect(buttons[0]).toEqual({ name: "Open agent", primary: true });
    expect(within(card).getAllByRole("link", { name: "Open agent" })[0]!.getAttribute("href")).toContain(
      "/agents/agent-1",
    );
  });

  it("leads with starting a campaign when an agent can dial and there is no campaign yet", async () => {
    const card = await recap({
      "/v1/agents": [agentRow({ direction: "outbound" })],
      "/v1/campaigns": [],
      "/v1/campaigns/numbers": [],
    });
    expect((await actions(card))[0]).toEqual({ name: "Start a campaign", primary: true });
  });

  it("leads with credit when calls have stopped", async () => {
    const card = await recap({
      "/v1/agents": [agentRow({ direction: "outbound" })],
      "/v1/billing/wallet": wallet({ is_low: true, outbound_stopped: true }),
    });
    expect((await actions(card))[0]).toEqual({ name: "Add credit", primary: true });
  });

  it("on a test-calls trial leads with credit and offers no campaign, which could not launch", async () => {
    const card = await recap({
      "/v1/agents": [agentRow({ direction: "outbound" })],
      "/v1/billing/wallet": wallet({
        balance_inr: "0.00",
        minutes_left: null,
        trial: activeTrialBlock({ test_calls_only: true }),
      }),
    });
    const buttons = await actions(card);
    expect(buttons[0]).toEqual({ name: "Add credit", primary: true });
    expect(buttons.map((b) => b.name)).not.toContain("Start a campaign");
  });

  it("offers staff only what their role may do", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/dashboard": { ...EMPTY_DASHBOARD, calls_7d: 3, calls_connected_7d: 3 },
        "/v1/agents": [agentRow({ direction: "outbound" })],
      }),
    );
    const card = (await screen.findByRole("heading", { name: "This week" })).closest("section") as HTMLElement;
    const buttons = await actions(card);
    expect(buttons.map((b) => b.name)).toEqual(["See calls"]);
  });
});

/** Finding 15: one vocabulary for an agent's state, the roster's and the agent page's. */
describe("your agents", () => {
  const agentsCard = async () =>
    (await screen.findByRole("heading", { name: "Your agents" })).closest("section") as HTMLElement;

  it("says each agent's state in the roster's words, with a way to it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/agents": [
          agentRow(),
          agentRow({ id: "agent-2", name: "Sales", status: "paused" }),
          agentRow({ id: "agent-3", name: "Follow-ups", status: "draft", published: false }),
        ],
      }),
    );
    const card = await agentsCard();
    const row = (name: string) => within(card).getByRole("link", { name }).closest("li") as HTMLElement;
    expect(row("Reception").textContent).toContain("Live");
    expect(row("Sales").textContent).toContain("Ready, not taking calls");
    expect(row("Follow-ups").textContent).toContain("Being set up");
    expect(within(card).getByRole("link", { name: "Reception" }).getAttribute("href")).toContain("/agents/agent-1");
  });

  it("says a switched-off agent is on for test calls during a trial, from the dashboard's own read", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/dashboard": {
          ...EMPTY_DASHBOARD,
          trial: {
            on_trial: true,
            status: "active",
            ends_at: "2026-10-20T17:28:00Z",
            days_remaining: 3,
            free_minutes: 30,
            minutes_used: 4,
            minutes_left: 26,
            calls_today: 0,
            daily_cap: 10,
            max_call_seconds: 180,
            pledge_accepted: true,
            can_call: true,
            blocked_reason: null,
          },
        },
        "/v1/agents": [agentRow({ status: "paused" })],
      }),
    );
    expect((await agentsCard()).textContent).toContain("On for test calls");
    expect(calls.some((call) => call.path === "/v1/trial")).toBe(false);
  });
});

/** Finding 24: the dashboard says how many questions went unanswered and where to teach them. */
describe("unanswered questions", () => {
  const GAP = {
    id: "gap-1",
    agent_id: "agent-1",
    agent_name: "Reception",
    topic_key: "pricing",
    topic_label: "Pricing",
    status: "open",
    signal: "dont_know",
    occurrence_count: 3,
    call_count: 2,
    example_question: "How much is it?",
    example_answer: "I don't know.",
    first_seen_at: "2026-10-20T04:30:00Z",
    last_seen_at: "2026-10-22T04:30:00Z",
  };
  const needsYou = async () =>
    (await screen.findByRole("heading", { name: "What needs you" })).closest("section") as HTMLElement;

  it("counts one agent's open questions and links to its Training tab", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/knowledge-gaps?status=open&limit=20": { items: [GAP, { ...GAP, id: "gap-2" }], open_count: 2, total: 2 },
      }),
    );
    const card = await needsYou();
    expect(card.textContent).toContain("2 questions not answered");
    // One topic: the list opens on that question, never on a blank page (D-893).
    expect(within(card).getByRole("link", { name: "Teach answers" }).getAttribute("href")).toBe(
      "/c/acme/agents/agent-1?section=training&question=pricing",
    );
  });

  it("opens the questions view of Knowledge when several agents asked several things", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/knowledge-gaps?status=open&limit=20": {
          items: [GAP, { ...GAP, id: "gap-2", agent_id: "agent-2", topic_key: "delivery" }],
          open_count: 2,
          total: 2,
        },
      }),
    );
    const card = await needsYou();
    expect(within(card).getByRole("link", { name: "Teach answers" }).getAttribute("href")).toBe(
      "/c/acme/knowledge?tab=questions",
    );
  });

  it("links to Knowledge when several agents struggled", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/knowledge-gaps?status=open&limit=20": {
          items: [GAP, { ...GAP, id: "gap-2", agent_id: "agent-2" }],
          open_count: 2,
          total: 2,
        },
      }),
    );
    const card = await needsYou();
    expect(within(card).getByRole("link", { name: "Teach answers" }).getAttribute("href")).toBe(
      "/c/acme/knowledge?question=pricing",
    );
  });

  it("says it could not check, with a retry, when the read fails", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/knowledge-gaps?status=open&limit=20": problem(503, { title: "Service unavailable" }) }),
    );
    const card = await needsYou();
    expect(card.textContent).toContain("Couldn't check unanswered questions");
    expect(within(card).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(card.textContent).not.toContain("All clear. Nothing needs you.");
  });
});

/**
 * ONE PAINT (D-787). The trial card comes with the dashboard read, and the notices above
 * the figures start their reads with it instead of after it, so nothing arrives a round
 * trip late and pushes the page down.
 */
describe("the dashboard arrives in one paint", () => {
  const TRIAL = {
    on_trial: true,
    status: "active",
    ends_at: "2026-10-20T17:28:00Z",
    days_remaining: 3,
    free_minutes: 30,
    minutes_used: 4,
    minutes_left: 26,
    calls_today: 2,
    daily_cap: 10,
    max_call_seconds: 180,
    pledge_accepted: true,
    can_call: true,
    blocked_reason: null,
  };

  it("renders the trial card from the dashboard read, with no read of its own", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/dashboard": { ...EMPTY_DASHBOARD, trial: TRIAL },
        "/v1/billing/wallet": wallet({ trial: activeTrialBlock({ test_calls_only: true }) }),
      }),
    );
    await screen.findByRole("heading", { name: "This week" });
    expect(screen.getByText("Your free trial")).toBeTruthy();
    expect(screen.getByText("26 of 30 minutes left")).toBeTruthy();
    expect(calls.some((call) => call.path === "/v1/trial")).toBe(false);
  });

  it("shows no trial card for an account that is not on one", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/dashboard": { ...EMPTY_DASHBOARD, trial: { on_trial: false } } }),
    );
    await screen.findByRole("heading", { name: "This week" });
    expect(container.textContent).not.toContain("Your free trial");
  });

  it("asks for the notices with the dashboard, not after it", async () => {
    const { calls } = await renderClientPage(page, routes({ "/v1/dashboard": stillLoading() }));
    const asked = new Set(calls.map((call) => call.path));
    for (const path of [
      "/v1/healer/incidents?days=30&limit=20",
      "/v1/business-profile",
      "/v1/forwarding",
      "/v1/knowledge-gaps?status=open&limit=20",
    ]) {
      expect(asked.has(path), path).toBe(true);
    }
  });

  it("holds the skeleton until the notices above the figures are known", async () => {
    const { calls, container } = await renderClientPage(
      page,
      routes({ "/v1/business-profile": stillLoading() }),
    );
    await waitFor(() => expect(calls.some((call) => call.path === "/v1/dashboard")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("heading", { name: "This week" })).toBeNull();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });
});

describe("proof on the home screen (D-944)", () => {
  const OWNER_WITH_BILLING: Me = { ...ME, permissions: [...ME.permissions, "org:manage", "billing:read"] };

  it("shows the owner the rupees per new lead from the server's string", async () => {
    await renderClientPage(page, routes({ "/v1/me": OWNER_WITH_BILLING }));
    expect(await screen.findByText("Cost per new lead, 7 days")).toBeTruthy();
    expect(screen.getByText("₹30")).toBeTruthy();
    expect(screen.getByRole("link", { name: /4 leads for ₹120/ }).getAttribute("href")).toBe(
      "/c/acme/billing?tab=usage",
    );
  });

  it("leaves no endless skeleton when the answer has no 7-day window", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/me": OWNER_WITH_BILLING,
        [COST_PER_RESULT_ROUTE]: {
          ...COST_PER_RESULT,
          windows: COST_PER_RESULT.windows.filter((w) => w.days !== 7),
        },
      }),
    );
    await screen.findByText("Captured after hours");
    await waitFor(() => expect(calls.some((c) => c.path === "/v1/analytics/cost-per-result")).toBe(true));
    await waitFor(() => expect(screen.queryByText("Working out your cost per lead")).toBeNull());
    expect(screen.queryByText("Cost per new lead, 7 days")).toBeNull();
  });

  it("never asks for spend figures without billing:read", async () => {
    const { calls } = await renderClientPage(page, routes());
    await screen.findByText("Captured after hours");
    expect(calls.some((c) => c.path === "/v1/analytics/cost-per-result")).toBe(false);
    expect(screen.queryByText("Cost per new lead, 7 days")).toBeNull();
  });

  it("offers the daily summary to an owner who has it off, with one button that turns it on", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/me": OWNER_WITH_BILLING,
        "/v1/notifications/daily-summary": { enabled: false, email_addresses: 1, whatsapp: false },
        "PUT /v1/notifications/daily-summary": { enabled: true, email_addresses: 1, whatsapp: false },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Send me a daily summary" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ enabled: true });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Send me a daily summary" })).toBeNull(),
    );
  });
});
