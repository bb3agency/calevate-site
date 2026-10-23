import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityHeatmap } from "@/components/arc/activity-heatmap";
import { BarChart } from "@/components/arc/bar-chart";
import { BrushChart } from "@/components/arc/brush-chart";
import { formatCompact, istShortDay, niceTicks } from "@/components/arc/chart-core";
import { Countdown, formatRemaining } from "@/components/arc/countdown";
import { DonutChart } from "@/components/arc/donut-chart";
import { Gauge } from "@/components/arc/gauge";
import { LineChart } from "@/components/arc/line-chart";
import { Ridgeline } from "@/components/arc/ridgeline";
import { Sparkline } from "@/components/arc/sparkline";
import { StatsBand } from "@/components/arc/stats-band";
import { Timeline, TimelineItem } from "@/components/arc/timeline";
import { UsageMeter } from "@/components/arc/usage-meter";
import { Metric } from "@/components/console/metric";
import { ChartsSection } from "@/app/admin/ops/kit/sections/charts";

/**
 * The kit's charts and figures (docs/design/KIT.md, "Charts and figures"). What is held
 * here is what a screen relies on without restating it: the data is readable as a table,
 * every state says something in words, money and counts read the Indian way, and a score
 * or allowance is a real meter with its value in words.
 */

describe("chart helpers", () => {
  it("ticks on round numbers from zero and groups compactly the Indian way", () => {
    expect(niceTicks(37)).toEqual([0, 10, 20, 30, 40]);
    expect(niceTicks(0)).toEqual([0, 1]);
    expect(formatCompact(123456)).toBe("1.2L");
    expect(formatCompact(950)).toBe("950");
  });

  it("names a day in IST, not the viewer's zone", () => {
    // 20:00 UTC on 23 Oct is 01:30 on 24 Oct in India.
    expect(istShortDay("2026-10-23T20:00:00Z")).toBe("24 Oct");
    expect(istShortDay("not a date")).toBe("—");
  });
});

describe("LineChart", () => {
  const labels = ["Mon", "Tue", "Wed"];

  it("renders its data as a table, with a gap read as a dash rather than a zero", () => {
    render(<LineChart title="Calls per day" labels={labels} series={[{ label: "Answered", values: [4, null, 9] }]} />);
    const table = screen.getByRole("table", { name: "Calls per day" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[2].textContent).toContain("—");
    expect(screen.getByRole("figure", { name: "Calls per day" })).toBeTruthy();
  });

  it("shows the table on request and says so on the button", () => {
    render(<LineChart title="Calls per day" labels={labels} series={[{ label: "Answered", values: [1, 2, 3] }]} />);
    const toggle = screen.getByRole("button", { name: "Show as table" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide table" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("says loading, empty and failed in words, never as an empty plot", () => {
    const { rerender } = render(<LineChart title="Calls" labels={[]} series={[]} loading />);
    expect(screen.getByRole("status").textContent).toContain("Loading Calls");
    rerender(<LineChart title="Calls" labels={[]} series={[]} empty="No calls this week yet." />);
    expect(screen.getByText("No calls this week yet.")).toBeTruthy();
    rerender(<LineChart title="Calls" labels={labels} series={[{ label: "A", values: [1, 2, 3] }]} error="We could not load your calls." />);
    expect(screen.getByRole("alert").textContent).toBe("We could not load your calls.");
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("BarChart", () => {
  it("prints the screen's own money text, never a re-derived float", () => {
    render(
      <BarChart
        title="Credit used by agent"
        orientation="horizontal"
        showValues
        categories={["Reception", "Follow-up"]}
        series={[{ label: "Spent", values: [1840.5, 742], display: ["₹1,840.50", "₹742.00"] }]}
      />,
    );
    expect(screen.getAllByText("₹1,840.50").length).toBeGreaterThan(0);
    const table = screen.getByRole("table", { name: "Credit used by agent" });
    expect(within(table).getByText("₹742.00")).toBeTruthy();
  });

  it("treats an all-zero series as empty", () => {
    render(<BarChart title="Calls" categories={["Mon"]} series={[{ label: "Calls", values: [0] }]} empty="No calls yet." />);
    expect(screen.getByText("No calls yet.")).toBeTruthy();
  });
});

describe("DonutChart", () => {
  it("folds a seventh part into Other instead of inventing a colour", () => {
    const segments = ["A", "B", "C", "D", "E", "F", "G"].map((label, i) => ({ label, value: 10 - i }));
    render(<DonutChart title="How calls ended" segments={segments} />);
    const rows = within(screen.getByRole("table", { name: "How calls ended" })).getAllByRole("row");
    expect(rows).toHaveLength(7);
    expect(rows[6].textContent).toContain("Other");
    expect(rows[6].textContent).toContain("9");
  });
});

describe("ActivityHeatmap", () => {
  it("adds up the IST buckets into a seven by twenty-four table", () => {
    render(
      <ActivityHeatmap
        title="When callers ring"
        cells={[
          { weekday: 0, hour: 10, count: 3 },
          { weekday: 0, hour: 10, count: 2 },
          { weekday: 6, hour: 23, count: 1 },
        ]}
      />,
    );
    const rows = within(screen.getByRole("table", { name: "When callers ring" })).getAllByRole("row");
    expect(rows).toHaveLength(8);
    expect(within(rows[0]).getAllByRole("columnheader")).toHaveLength(25);
    expect(within(rows[1]).getAllByRole("cell")[10].textContent).toBe("5");
  });
});

describe("Ridgeline", () => {
  it("reports each row's median and middle half", () => {
    render(<Ridgeline title="Call length" series={[{ label: "Reception", values: [60, 120, 180] }]} />);
    const row = within(screen.getByRole("table", { name: "Call length" })).getAllByRole("row")[1];
    expect(row.textContent).toContain("2:00");
    expect(row.textContent).toContain("1:30 – 2:30");
  });
});

describe("Gauge", () => {
  it("is a meter whose value is said with its band", () => {
    render(<Gauge value={64} label="Readiness" fixes={[{ id: "q", label: "Answer 3 questions", points: 12, href: "/x" }]} />);
    const meter = screen.getByRole("meter", { name: "Readiness" });
    expect(meter.getAttribute("aria-valuenow")).toBe("64");
    expect(meter.getAttribute("aria-valuetext")).toBe("64 out of 100, Nearly ready");
    expect(screen.getByRole("link", { name: /Answer 3 questions/ }).getAttribute("href")).toBe("/x");
  });

  it("never shows a missing score as zero", () => {
    render(<Gauge value={null} label="Readiness" pendingText="Run a practice test to get a score" fixes={[]} allDoneText="Nothing left to fix." />);
    // Not a meter at all until there is a reading: an image named by why there is none.
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByRole("img", { name: "Readiness: Run a practice test to get a score" })).toBeTruthy();
    expect(screen.getByText("Nothing left to fix.")).toBeTruthy();
  });
});

describe("UsageMeter", () => {
  it("reads the caller's own figures and caps the bar at the limit", () => {
    render(<UsageMeter label="Spending cap" used={5200} limit={5000} usedText="₹5,200.00" limitText="₹5,000.00" overTone="danger" />);
    const meter = screen.getByRole("meter", { name: "Spending cap" });
    expect(meter.getAttribute("aria-valuenow")).toBe("5000");
    expect(meter.getAttribute("aria-valuetext")).toBe("₹5,200.00 of ₹5,000.00 used");
  });

  it("draws no bar when there is no limit", () => {
    render(<UsageMeter label="Minutes" used={20} limit={0} usedText="20" />);
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByText("20 used · No limit")).toBeTruthy();
  });
});

describe("Metric and StatsBand", () => {
  it("colours a change by whether it is good news, not by its sign", () => {
    render(<Metric label="Missed" value="30" delta={{ text: "−4", direction: "down", good: true }} />);
    expect(screen.getByText("−4").closest("p")?.className).toContain("text-brand-strong");
  });

  it("puts a sparkline beside each figure that has a trend", () => {
    render(<StatsBand label="This week" items={[{ label: "Calls", value: "292", trend: [1, 3, 2] }, { label: "Leads", value: "40" }]} />);
    expect(screen.getByRole("region", { name: "This week" })).toBeTruthy();
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("Calls: from 1 to 2");
  });
});

describe("Sparkline", () => {
  it("says no data rather than drawing a flat line", () => {
    render(<Sparkline values={[]} label="Leads" />);
    expect(screen.getByRole("img", { name: "Leads: no data" }).textContent).toBe("—");
  });
});

describe("Timeline", () => {
  it("is an ordered list of items with their meta line", () => {
    render(
      <Timeline label="Lead history">
        <TimelineItem title="Called back" meta="24 Oct · Calevate" />
        <TimelineItem title="Note added" detail="Prefers Telugu" />
      </Timeline>,
    );
    const list = screen.getByRole("list", { name: "Lead history" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("24 Oct · Calevate")).toBeTruthy();
  });
});

describe("Countdown", () => {
  it("words the time left and drops seconds past an hour", () => {
    expect(formatRemaining(45)).toBe("45 s");
    expect(formatRemaining(125)).toBe("2 min 5 s");
    expect(formatRemaining(2 * 3600 + 14 * 60 + 9)).toBe("2 h 14 min");
    expect(formatRemaining(90000)).toBe("1 d 1 h");
  });

  it("corrects a device clock that is wrong by the server's own now", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-24T10:00:00Z"));
    // The server says it is already 10:50, so a 11:00 target is ten minutes away, not an hour.
    render(<Countdown target="2026-10-24T11:00:00Z" serverNow="2026-10-24T10:50:00Z" />);
    expect(screen.getByRole("timer").textContent).toBe("10 min 0 s");
    vi.useRealTimers();
  });

  it("says the caller's done sentence once the target has passed", () => {
    render(<Countdown target="2020-01-01T00:00:00Z" doneText="Trial has ended" />);
    expect(screen.getByRole("timer").textContent).toBe("Trial has ended");
  });
});

describe("BrushChart", () => {
  it("moves its window from the keyboard and shows only that window in detail", () => {
    const onRangeChange = vi.fn();
    const labels = ["1 Oct", "2 Oct", "3 Oct", "4 Oct", "5 Oct"];
    render(
      <BrushChart
        title="Leads per day"
        seriesLabel="Leads"
        labels={labels}
        values={[1, 2, 3, 4, 5]}
        defaultRange={[1, 3]}
        onRangeChange={onRangeChange}
      />,
    );
    const start = screen.getByRole("slider", { name: "Start of the shown period" });
    expect(start.getAttribute("aria-valuetext")).toBe("2 Oct");
    fireEvent.keyDown(start, { key: "ArrowLeft" });
    expect(onRangeChange).toHaveBeenLastCalledWith([0, 3]);
    expect(screen.getByText("1 Oct to 4 Oct")).toBeTruthy();
    const rows = within(screen.getByRole("table", { name: "Leads per day" })).getAllByRole("row");
    expect(rows).toHaveLength(5);
    fireEvent.keyDown(screen.getByRole("slider", { name: "End of the shown period" }), { key: "End" });
    expect(onRangeChange).toHaveBeenLastCalledWith([0, 4]);
  });
});

describe("the kit page's charts section", () => {
  it("renders every specimen without throwing", () => {
    render(<ChartsSection />);
    expect(screen.getByRole("heading", { name: "Charts and figures" })).toBeTruthy();
    expect(screen.getAllByRole("figure").length).toBeGreaterThan(8);
  });
});
