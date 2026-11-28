import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { sinceWords, todayWords } from "@/app/c/[slug]/agents/Roster";
import { SPEED_COPY, SpeedToLead, compareLines, speedItems } from "@/app/c/[slug]/lead-sources/SpeedToLead";
import { groupsCsv, periodCsv } from "@/app/c/[slug]/performance/Breakdowns";
import { FILTER_COPY } from "@/app/c/[slug]/performance/Filters";
import { LAST_HOUR_COPY } from "@/app/c/[slug]/performance/LastHour";
import { QUALITY_COPY } from "@/app/c/[slug]/performance/QualityWeeks";
import type { CallGroup, SpeedToLead as SpeedData, SummaryRow } from "@/lib/api/analytics";
import { useClientSession } from "@/lib/api/session";
import { tableCsv } from "@/lib/csvDownload";

import { renderClientPage } from "./harness";
import { SHORT_LINE } from "./shortCopy";

/**
 * Wave B analytics (W8.1, W8.2, W8.3, W8.5). What a wrong render costs here is a claim the
 * data does not support: a speed figure with nothing called, a comparison from a handful of
 * leads, or "Today: 0" on a read that failed.
 */

const FIGURES = {
  leads: 12,
  called: 10,
  median_s: 18,
  within_60s: 8,
  reached: 7,
  never_reached: 2,
  waiting: 1,
  interested: 4,
  from_release: 3,
};

const SPEED: SpeedData = {
  window: { period: "7d", start_at: "2026-11-22T00:00:00+05:30", end_at: "2026-11-29T00:00:00+05:30", timezone: "Asia/Kolkata" },
  total: FIGURES,
  sources: [{ ...FIGURES, source_id: "s1", source: "website_form" }],
  other_sources: 0,
  compare: null,
  compare_min_leads: 30,
};

function Card() {
  return <SpeedToLead session={useClientSession()} />;
}

describe("How fast we called", () => {
  it("states the four figures from the server, with the counts beside the share", () => {
    const items = speedItems(FIGURES);
    expect(items.map((i) => [i.label, i.value])).toEqual([
      [SPEED_COPY.wait, "18 seconds"],
      [SPEED_COPY.minute, "80%"],
      [SPEED_COPY.never, "2"],
      [SPEED_COPY.waiting, "1"],
    ]);
    expect(items[1]?.hint).toBe("8 of 10 called");
  });

  it("says nothing about speed when nothing was called", () => {
    const items = speedItems({ ...FIGURES, called: 0, within_60s: 0, median_s: null });
    expect(items[0]?.value).toBe("—");
    expect(items[0]?.hint).toBeUndefined();
    expect(items[1]?.value).toBe("—");
  });

  it("offers the comparison only past the server's floor, and always with both counts", () => {
    expect(compareLines(SPEED)).toEqual(["Shown from 30 called leads. 10 so far."]);
    const lines = compareLines({
      ...SPEED,
      compare: { fast_called: 20, fast_interested: 10, later_called: 10, later_interested: 1 },
    });
    expect(lines).toEqual(["Within a minute: 10 of 20 interested (50%)", "Later: 1 of 10 interested (10%)"]);
  });

  it("renders the card and the by-source row; an empty period says so", async () => {
    await renderClientPage(<Card />, { "/v1/analytics/speed-to-lead?period=7d": SPEED });
    expect(await screen.findByText("Website form")).toBeTruthy();
    // The band and the source row both state the typical wait.
    expect(screen.getAllByText("18 seconds")).toHaveLength(2);

    await renderClientPage(<Card />, {
      "/v1/analytics/speed-to-lead?period=7d": { ...SPEED, total: { ...FIGURES, leads: 0 }, sources: [] },
    });
    await waitFor(() => expect(screen.getByText(SPEED_COPY.empty)).toBeTruthy());
  });
});

describe("agents today", () => {
  it("words today's line and an agent with no call today as zero, from a read that arrived", () => {
    expect(todayWords({ agent_id: "a", calls: 12, answered: 9, interested: 3 })).toBe("Today: 12 calls · 3 interested");
    expect(todayWords(undefined)).toBe("Today: 0 calls · 0 interested");
  });

  it("says how long ago the last call was", () => {
    const now = Date.parse("2026-11-28T10:00:00Z");
    expect(sinceWords("2026-11-28T09:59:40Z", now)).toBe("just now");
    expect(sinceWords("2026-11-28T09:56:00Z", now)).toBe("4 min ago");
    expect(sinceWords("2026-11-28T07:00:00Z", now)).toBe("3 h ago");
  });
});

describe("downloads", () => {
  it("guards a cell a spreadsheet would run as a formula", () => {
    expect(tableCsv(["Name"], [["=HYPERLINK(1)"], ["a,b"]])).toBe("Name\n'=HYPERLINK(1)\n\"a,b\"");
  });

  it("puts spend in the period file only when the screen shows it", () => {
    const rows: SummaryRow[] = [
      { from_date: "2026-11-24", to_date: "2026-11-24", calls: 3, answered: 2, leads: 1, spent_inr: "12.50" },
    ];
    expect(periodCsv(rows, "day", false).split("\n")[0]).toBe("Day,Calls,Answered,New leads");
    expect(periodCsv(rows, "day", true).split("\n")[1]?.endsWith(",12.50")).toBe(true);
  });

  it("writes agent groups, never people", () => {
    const group: CallGroup = {
      key: "a1",
      label: "Reception",
      lead_id: null,
      number_tail: null,
      calls: 4,
      answered: 3,
      latest_at: null,
      latest_call_id: "c1",
      latest_status: "completed",
      latest_outcome: null,
      latest_business_outcome_label: null,
    };
    expect(groupsCsv([group], "agent")).toBe("Agent,Calls,Answered\nReception,4,3");
  });
});

describe("the words are short", () => {
  const screens: Record<string, Record<string, string>> = {
    speed: SPEED_COPY,
    filters: FILTER_COPY,
    quality: QUALITY_COPY,
  };
  for (const [name, copy] of Object.entries(screens)) {
    it(`${name}: every line shown without a tap fits one phone line`, () => {
      const long = Object.entries(copy)
        .filter(([key]) => !/(Why|Tip|^info)$/.test(key))
        .filter(([, line]) => line.length > SHORT_LINE);
      expect(long).toEqual([]);
    });
  }

  it("composed lines stay short at worst-case values", () => {
    const composed = [
      LAST_HOUR_COPY.live(1200),
      LAST_HOUR_COPY.hour(1200),
      todayWords({ agent_id: "a", calls: 12000, answered: 1, interested: 3000 }),
      ...compareLines({
        ...SPEED,
        compare: { fast_called: 12000, fast_interested: 1000, later_called: 12000, later_interested: 1000 },
      }),
    ];
    expect(composed.filter((line) => line.length > SHORT_LINE)).toEqual([]);
  });
});
