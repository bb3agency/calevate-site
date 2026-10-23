import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PerformancePage from "@/app/c/[slug]/performance/page";
import { todayIST } from "@/components/arc/ist-dates";
import type { Durations, Heatmap, Stats, Timeline } from "@/lib/api/analytics";
import type { Me } from "@/lib/api/client";
import type { Performance } from "@/lib/api/performance";

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
  performance: "/v1/performance?days=30",
};

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
    ...over,
  };
}

/** A figure of the stats band: its label's parent holds the value, change and hint. */
async function figure(label: string): Promise<string> {
  const band = await screen.findByRole("region", { name: "This period at a glance" });
  return (within(band).getByText(label).parentElement?.textContent ?? "").replace(/\s+/g, " ");
}

describe("the performance report", () => {
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

  it("draws the funnel and the outcomes for a range that ends today", async () => {
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
      }),
    );
    const toggle = await screen.findByRole("switch", { name: "Include my test calls" });
    await act(async () => fireEvent.click(toggle));
    await waitFor(() => expect(calls.some((call) => call.path === `/v1/analytics/stats?${without}`)).toBe(true));
    // The funnel's read cannot leave them out, and says so rather than implying it did.
    await screen.findAllByText("Your test calls are counted here.");
  });

  it("explains a missing permission instead of answering with an error", async () => {
    const { container } = await renderClientPage(page, {
      "/v1/me": { ...ME, permissions: ["leads:read"] },
      [PATHS.stats]: problem(403, { title: "Forbidden" }),
      [PATHS.heatmap]: problem(403, { title: "Forbidden" }),
      [PATHS.durations]: problem(403, { title: "Forbidden" }),
      [PATHS.timeline]: problem(403, { title: "Forbidden" }),
      [PATHS.performance]: problem(403, { title: "Forbidden" }),
    });
    await screen.findByText(/permission to read call records/);
    expect(screen.queryByRole("alert"), "a permission is not a fault").toBeNull();
    expect(container.textContent).not.toContain("Answer rate");
  });
});
