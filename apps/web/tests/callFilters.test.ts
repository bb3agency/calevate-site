import { describe, expect, it } from "vitest";

import { callWindow, shiftDay } from "@/lib/callFilters";

/** The call log's date windows: India-time days, always with a zone (REDESIGN-2). */
describe("call log windows", () => {
  it("counts days on the India-time calendar", () => {
    expect(shiftDay("2026-03-01", -1)).toBe("2026-02-28");
    expect(callWindow("today", "2026-10-10")).toEqual({ since: "2026-10-10T00:00:00+05:30" });
    expect(callWindow("7d", "2026-10-10")).toEqual({ since: "2026-10-04T00:00:00+05:30" });
    expect(callWindow("30d", "2026-10-10")).toEqual({ since: "2026-09-11T00:00:00+05:30" });
    expect(callWindow("all", "2026-10-10")).toEqual({});
  });

  it("includes both days of a custom range, and never sends a backwards one", () => {
    expect(callWindow("custom", "2026-10-10", "2026-10-01", "2026-10-03")).toEqual({
      since: "2026-10-01T00:00:00+05:30",
      until: "2026-10-04T00:00:00+05:30",
    });
    expect(callWindow("custom", "2026-10-10", "2026-10-05", "2026-10-01")).toEqual({
      since: "2026-10-05T00:00:00+05:30",
      until: undefined,
    });
  });
});
