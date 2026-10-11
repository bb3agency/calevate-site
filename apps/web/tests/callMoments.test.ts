import { describe, expect, it } from "vitest";

import {
  momentClock,
  momentLinkSeconds,
  momentSeekMs,
  momentsByTurn,
  parseStartAt,
  turnClock,
  type CallMoment,
} from "@/lib/callMoments";

/**
 * Where a key moment sends the listener. The voice platform's turn times are approximate
 * (founder, 11 Oct 2026), so an approximate moment is written "~0:21" and played from two
 * seconds earlier; an exact one is neither.
 */
function moment(over: Partial<CallMoment> = {}): CallMoment {
  return {
    at_ms: 21_000,
    turn_idx: 2,
    kind: "complaint",
    category: "attention",
    label: "Complained about the wait",
    source: "model",
    precision: "approximate",
    importance: 3,
    ...over,
  };
}

describe("key moment times", () => {
  it("marks an approximate time and starts two seconds early", () => {
    expect(momentClock(moment())).toBe("~0:21");
    expect(momentSeekMs(moment())).toBe(19_000);
    expect(momentLinkSeconds(moment())).toBe(19);
  });

  it("leaves an exact time alone", () => {
    const exact = moment({ precision: "exact" });
    expect(momentClock(exact)).toBe("0:21");
    expect(momentSeekMs(exact)).toBe(21_000);
  });

  it("never seeks before the start of the recording", () => {
    expect(momentSeekMs(moment({ at_ms: 900 }))).toBe(0);
  });

  it("writes a turn's time the same way", () => {
    expect(turnClock(65_000, true)).toBe("~1:05");
    expect(turnClock(65_000, false)).toBe("1:05");
  });
});

describe("moments on transcript lines", () => {
  it("groups by turn and skips moments with no turn", () => {
    const byTurn = momentsByTurn([
      moment({ turn_idx: 2 }),
      moment({ turn_idx: 2, kind: "frustrated" }),
      moment({ turn_idx: null }),
    ]);
    expect([...byTurn.keys()]).toEqual([2]);
    expect(byTurn.get(2)?.map((m) => m.kind)).toEqual(["complaint", "frustrated"]);
  });
});

describe("?t= links", () => {
  it("reads whole seconds and ignores anything else", () => {
    expect(parseStartAt("19")).toBe(19);
    expect(parseStartAt("19.8")).toBe(19);
    expect(parseStartAt("-3")).toBeNull();
    expect(parseStartAt("soon")).toBeNull();
    expect(parseStartAt("")).toBeNull();
    expect(parseStartAt(undefined)).toBeNull();
  });
});
