import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PerformancePage from "@/app/c/[slug]/performance/page";
import { clampRange } from "@/app/c/[slug]/performance/PerformanceScreen";
import { todayIST } from "@/components/arc/ist-dates";
import type { CallGroups, Durations, Heatmap, Stats, Summary, Timeline } from "@/lib/api/analytics";
import type { Me } from "@/lib/api/client";
import type { Performance } from "@/lib/api/performance";

import { REPLY_SPEED_FIXTURE } from "./fixtures/proof";
import { problem, renderClientPage } from "./harness";

/**
 * The performance report — the screen an owner uses to decide whether the agent is worth
 * paying for. Every number on it is an argument, so a wrong one is not a cosmetic defect.
 *
 * Ranked by what a wrong render costs:
 *
 * 1. **A rate with nothing to measure rendered as 0%.** The server sends null, never 0,
 *    when there were no calls; "0% answered" tells a client who has not launched yet that
 *    their agent is failing.
 * 2. **A real 0% rendered as "no data".** Calls that happened and never connected are the
 *    bad news this report exists to deliver.
 * 3. **Figures under a failed request.** A refusal, never a zero.
 * 4. **A weekday off by one.** The server numbers weekdays 1 (Monday) to 7; the chart
 *    counts from 0, and a slip would move every call a day.
 * 5. **A median re-derived from the drawing.** The ridgeline is drawn from bins; the
 *    median and 90th percentile it states are the server's.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const TODAY = todayIST();
const WINDOW = { days: 30, from_date: "2026-09-25", to_date: TODAY, timezone: "Asia/Kolkata" as const };

/** The default range: the last 30 IST days ending today, test calls included. */
const Q = `days=30&to=${TODAY}&test_calls=true`;
const PATHS = {
  stats: `/v1/analytics/stats?${Q}`,
  heatmap: `/v1/analytics/heatmap?${Q}&metric=calls`,
  durations: `/v1/analytics/durations?${Q}&group_by=agent&bin_s=30`,
  timeline: `/v1/analytics/timeline?days=90&to=${TODAY}&test_calls=true`,
  performance: `/v1/performance?days=30&to=${TODAY}`,
  summary: `/v1/analytics/summary?${Q}&bucket=week`,
  groups: `/v1/analytics/call-groups?days=30&to=${TODAY}&test_calls=false&by=caller&min_calls=2&limit=25`,
};

function summary(over: Partial<Summary> = {}): Summary {
  return {
    window: WINDOW,
    bucket: "week",
    rows: [
      { from_date: "2026-10-19", to_date: "2026-10-25", calls: 12, answered: 9, leads: 3, spent_inr: "1240.50" },
      { from_date: "2026-10-26", to_date: TODAY, calls: 4, answered: 4, leads: 1, spent_inr: "310.00" },
    ],
    calls: 16,
    answered: 13,
    leads: 4,
    spent_inr: "1550.50",
    spend_withheld: null,
    ...over,
  };
}

function groups(over: Partial<CallGroups> = {}): CallGroups {
  return {
    window: WINDOW,
    by: "caller",
    calls: 16,
    groups_total: 2,
    repeat_groups: 2,
    min_calls: 2,
    groups: [
      { key: "l1", label: "Ravi Kumar", lead_id: "0192f0aa-0000-7000-8000-00000000000a", number_tail: "42", calls: 3, answered: 2, latest_at: "2026-10-26T09:30:00Z", latest_outcome: "call_back_booked" },
      { key: "number", label: null, lead_id: null, number_tail: "07", calls: 2, answered: 0, latest_at: "2026-10-25T05:00:00Z", latest_outcome: "missed" },
    ],
    ...over,
  };
}

type MetricKey = Stats["metrics"][number]["key"];

function stats(values: Partial<Record<MetricKey, [string | null, string | null, string | null]>> = {}): Stats {
  const keys: MetricKey[] = ["calls", "answered", "answer_rate_pct", "leads", "hot_leads", "avg_duration_s", "talk_minutes"];
  return {
    window: WINDOW,
    previous_window: { ...WINDOW, from_date: "2026-08-26", to_date: "2026-09-24" },
    metrics: keys.map((key) => {
      const [value, previous, change_pct] = values[key] ?? ["0", "0", null];
      return { key, value, previous, change_pct, higher_is_better: true };
    }),
  };
}

/** 168 cells, Monday 00:00 first, with 5 calls on Monday 10:00 and 2 on Sunday 18:00. */
function heatmap(): Heatmap {
  const cells = [];
  for (let weekday = 1; weekday <= 7; weekday += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      cells.push({ weekday, hour, count: weekday === 1 && hour === 10 ? 5 : weekday === 7 && hour === 18 ? 2 : 0 });
    }
  }
  return { metric: "calls", cells, max_count: 5, total: 7, window: WINDOW };
}

function durations(): Durations {
  const counts = Array.from({ length: 20 }, (_, i) => (i === 2 ? 6 : i === 4 ? 3 : i === 19 ? 1 : 0));
  return {
    group_by: "agent",
    bin_s: 30,
    bin_edges_s: Array.from({ length: 20 }, (_, i) => i * 30),
    groups: [{ key: "a1", label: "Front desk", calls: 10, counts, median_s: 95, p90_s: 151 }],
    other_calls: 0,
    window: WINDOW,
  };
}

function timeline(): Timeline {
  return { calls: 0, answered: 0, leads: 0, days: [], window: { ...WINDOW, days: 90 } };
}

function performance(over: Partial<Performance> = {}): Performance {
  return {
    days: 30,
    funnel: { calls: 51, connected: 39, qualified: 14 },
    connect_rate_pct: 76,
    qualify_rate_pct: 36,
    inbound: 30,
    outbound: 21,
    avg_duration_s: 154,
    outcomes: { appointment_booked: 14, no_answer: 8, enquiry: 29 },
    busiest_hours_ist: Array.from({ length: 24 }, () => 0),
    ...over,
  };
}

const page = <PerformancePage />;

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    [PATHS.stats]: stats(),
    [PATHS.heatmap]: heatmap(),
    [PATHS.durations]: durations(),
    [PATHS.timeline]: timeline(),
    [PATHS.performance]: performance(),
    [PATHS.summary]: summary(),
    [PATHS.groups]: groups(),
    [REPLY_SPEED_PATH]: REPLY_SPEED,
    ...over,
  };
}

const REPLY_SPEED_PATH = "/v1/analytics/reply-speed?weeks=4";
const REPLY_SPEED = REPLY_SPEED_FIXTURE;

/** A figure of the stats band: its label's parent holds the value, change and hint. */
async function figure(label: string): Promise<string> {
  const band = await screen.findByRole("region", { name: "This period at a glance" });
  return (within(band).getByText(label).parentElement?.textContent ?? "").replace(/\s+/g, " ");
}

describe("the performance report", () => {
  it("cuts a picked range to the last 366 days, which is all the figures cover", () => {
    // The reads cap at 366 days while the header named the whole picked range.
    expect(clampRange({ start: "2025-03-01", end: "2026-10-26" })).toEqual({
      start: "2025-10-26",
      end: "2026-10-26",
    });
    const short = { start: "2026-10-01", end: "2026-10-26" };
    expect(clampRange(short)).toBe(short);
  });

  it("says there is nothing to measure rather than reporting 0%", async () => {
    await renderClientPage(page, routes({ [PATHS.stats]: stats({ answer_rate_pct: [null, null, null] }) }));
    const rate = await figure("Answer rate");
    expect(rate).toContain("—");
    expect(rate, "a null rate must never render as a percentage").not.toContain("0%");
  });

  it("reports a real 0% as 0%, because that is bad news the owner has to see", async () => {
    await renderClientPage(
      page,
      routes({ [PATHS.stats]: stats({ calls: ["12", "0", null], answer_rate_pct: ["0.0", null, null] }) }),
    );
    expect(await figure("Answer rate")).toContain("0%");
  });

  it("shows a refusal instead of figures when the figures fail", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ [PATHS.stats]: problem(503, { title: "Service unavailable", detail: "We could not read your call history." }) }),
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "This period at a glance" })).toBeNull();
    expect(container.textContent).not.toContain("Answer rate");
  });

  it("puts the server's Monday on the chart's Monday", async () => {
    await renderClientPage(page, routes());
    const table = await screen.findByRole("table", { name: "Calls by day and hour" });
    const monday = within(table).getByRole("rowheader", { name: "Mon" }).closest("tr") as HTMLElement;
    const sunday = within(table).getByRole("rowheader", { name: "Sun" }).closest("tr") as HTMLElement;
    // Column 0 is the day; 10:00 is column 11, 18:00 column 19.
    expect(monday.children[11]?.textContent).toBe("5");
    expect(sunday.children[19]?.textContent).toBe("2");
  });

  it("states the server's median and 90th percentile, not ones re-derived from the bins", async () => {
    await renderClientPage(page, routes());
    const table = await screen.findByRole("table", { name: "Call length by agent" });
    const row = within(table).getByRole("rowheader", { name: "Front desk" }).closest("tr") as HTMLElement;
    expect(row.textContent).toContain("1:35");
    expect(row.textContent).toContain("2:31");
    expect(row.textContent).toContain("10");
  });

  it("draws the funnel and the outcomes for the chosen range", async () => {
    await renderClientPage(page, routes());
    const funnel = await screen.findByRole("table", { name: "From calls to customers" });
    expect(funnel.textContent).toContain("51");
    expect(funnel.textContent).toContain("14");
    const outcomes = await screen.findByRole("table", { name: "How calls ended" });
    expect(outcomes.textContent).toContain("Appointment booked");
  });

  it("asks again without test calls when the owner leaves them out", async () => {
    const without = `days=30&to=${TODAY}&test_calls=false`;
    const { calls } = await renderClientPage(
      page,
      routes({
        [`/v1/analytics/stats?${without}`]: stats(),
        [`/v1/analytics/heatmap?${without}&metric=calls`]: heatmap(),
        [`/v1/analytics/durations?${without}&group_by=agent&bin_s=30`]: durations(),
        [`/v1/analytics/timeline?days=90&to=${TODAY}&test_calls=false`]: timeline(),
        [`/v1/performance?days=30&to=${TODAY}&test_calls=false`]: performance(),
        [`/v1/analytics/summary?${without}&bucket=week`]: summary(),
      }),
    );
    const toggle = await screen.findByRole("switch", { name: "Include my test calls" });
    await act(async () => fireEvent.click(toggle));
    await waitFor(() => expect(calls.some((call) => call.path === `/v1/analytics/stats?${without}`)).toBe(true));
    // The funnel and outcomes leave them out too.
    await waitFor(() =>
      expect(calls.some((call) => call.path === `/v1/performance?days=30&to=${TODAY}&test_calls=false`)).toBe(true),
    );
  });

  it("explains a missing permission instead of answering with an error", async () => {
    const { container } = await renderClientPage(page, {
      "/v1/me": { ...ME, permissions: ["leads:read"] },
      [PATHS.stats]: problem(403, { title: "Forbidden" }),
      [PATHS.heatmap]: problem(403, { title: "Forbidden" }),
      [PATHS.durations]: problem(403, { title: "Forbidden" }),
      [PATHS.timeline]: problem(403, { title: "Forbidden" }),
      [PATHS.performance]: problem(403, { title: "Forbidden" }),
      [PATHS.summary]: problem(403, { title: "Forbidden" }),
      [PATHS.groups]: problem(403, { title: "Forbidden" }),
      [REPLY_SPEED_PATH]: problem(403, { title: "Forbidden" }),
    });
    await screen.findByText(/access to call records/);
    expect(screen.queryByRole("alert"), "a permission is not a fault").toBeNull();
    expect(container.textContent).not.toContain("Answer rate");
  });
});

describe("how fast the agent answered (D-944)", () => {
  it("leads with this week's usual wait, splits it by language, and never shows a zero for an unmeasured week", async () => {
    const { container } = await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "How fast your agent answered" })).toBeTruthy();
    expect(await screen.findByText("Usual wait this week")).toBeTruthy();
    expect(screen.getAllByText("1.4 s").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Too few calls").length).toBeGreaterThan(0);
    expect(container.textContent).toContain("Telugu: 1.3 s");
    expect(container.textContent).toContain("Hindi: 1.7 s");
    expect(screen.getAllByText("Not measured").length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/\b0\.0 s\b/);
  });

  it("shows an empty state when there were no calls in four weeks", async () => {
    await renderClientPage(
      page,
      routes({ [REPLY_SPEED_PATH]: { ...REPLY_SPEED, weeks: REPLY_SPEED.weeks.slice(0, 3) } }),
    );
    expect(await screen.findByText("No calls in the last four weeks.")).toBeTruthy();
  });
});

describe("the period table and who called (D-893 L7)", () => {
  it("shows the server's weeks with spend, newest first, and asks again by month", async () => {
    const monthPath = `/v1/analytics/summary?${Q}&bucket=month`;
    const { calls } = await renderClientPage(
      page,
      routes({ [monthPath]: summary({ bucket: "month", rows: [] }) }),
    );
    const table = await screen.findByRole("table", { name: /by week, newest first/ });
    const rows = within(table).getAllByRole("row");
    // The header, then the newest week first.
    expect(rows[1].textContent).toContain("₹310");
    expect(table.textContent).toContain("₹1,240.5");
    expect(screen.getByText(/16 calls, 13 answered, 4 new leads, ₹1,550.5 spent/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("radio", { name: "Month" })));
    await waitFor(() => expect(calls.some((call) => call.path === monthPath)).toBe(true));
  });

  it("says spend is for people who can see billing when the server withholds it", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        [PATHS.summary]: summary({
          spent_inr: null,
          spend_withheld: "no_billing_access",
          rows: summary().rows.map((row) => ({ ...row, spent_inr: null })),
        }),
      }),
    );
    await screen.findByText("Spend is shown to people who can see billing.");
    expect(container.textContent).not.toContain("₹1,240.5");
  });

  it("counts repeat callers over every call and links each to its lead", async () => {
    await renderClientPage(page, routes());
    await screen.findByText("16 calls. 2 callers called more than once.");
    const link = screen.getByRole("link", { name: /Ravi Kumar · ends 42/ });
    expect(link.getAttribute("href")).toBe("/c/acme/leads/0192f0aa-0000-7000-8000-00000000000a");
    expect(screen.getByText("No lead yet · ends 07")).toBeTruthy();
  });

  it("says nobody called twice rather than showing an empty table", async () => {
    await renderClientPage(
      page,
      routes({ [PATHS.groups]: groups({ repeat_groups: 0, groups_total: 0, groups: [] }) }),
    );
    await screen.findByText("Nobody called more than once in this period.");
  });
});
