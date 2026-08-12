import { describe, expect, it } from "vitest";

import {
  HOLD_RULES,
  WAIT_BREACH_HOURS,
  WAIT_WARN_HOURS,
  holdRule,
  hoursWaiting,
  waitBand,
  waitedFor,
} from "@/lib/api/holds";

/**
 * The ops queue FAILS VISIBLE — the opposite direction from `firstCampaignState`, on
 * purpose, and that opposition is the thing worth pinning down.
 *
 * The client's screen must never render a held account as clear, so its unknown case
 * stays held. The operator's queue must never render a held account as gone, so its
 * unknown case keeps the row and says the console cannot name the rule. Both are
 * "fail safe"; safe points in different directions depending on who is reading, and a
 * type checker sees `HoldRule | null` either way.
 */

const HOUR = 3_600_000;
const NOW = Date.parse("2026-08-12T12:00:00Z");

function agoHours(hours: number): string {
  return new Date(NOW - hours * HOUR).toISOString();
}

describe("holdRule", () => {
  it("returns null for a rule this build has never heard of", () => {
    // Null is the signal the queue renders as "we do not know what clears this" — the
    // row survives. Returning a plausible-looking default would be the failure that
    // matters: an account silently dropped off the work list because a gate was renamed.
    expect(holdRule("a_gate_this_build_predates")).toBeNull();
  });

  it("returns null for inherited Object properties, rather than the prototype's value", () => {
    // `rule` arrives as a plain string from the API, and the lookup is a bare object.
    // `"constructor" in HOLD_RULES` is TRUE — the `in` operator walks the prototype
    // chain — so a membership test spelled that way hands back `Object` itself, typed
    // as a `HoldRule`. The queue then calls `copy.screen(tenantId)` on it and the whole
    // ops screen dies with a TypeError: the fail-VISIBLE contract inverted into the one
    // failure an operator cannot see past.
    for (const inherited of ["constructor", "toString", "hasOwnProperty", "__proto__"]) {
      expect(holdRule(inherited), inherited).toBeNull();
    }
  });

  it("names each gate rule with the screen that clears it", () => {
    for (const [rule, copy] of Object.entries(HOLD_RULES)) {
      const found = holdRule(rule);
      expect(found, rule).not.toBeNull();
      expect(found?.screen("t-1"), rule).toContain("/admin/tenants/t-1/");
      expect(copy.remedy.length, rule).toBeGreaterThan(0);
    }
  });

  it("keeps `kyc_missing` and `kyc_not_verified` as two rules on one screen", () => {
    // Different work — "we have never heard from them" versus "we owe them a review" —
    // so collapsing them would lose the distinction the queue is triaged on.
    expect(holdRule("kyc_missing")?.label).not.toBe(holdRule("kyc_not_verified")?.label);
    expect(holdRule("kyc_missing")?.screen("t-1")).toBe(holdRule("kyc_not_verified")?.screen("t-1"));
  });
});

describe("hoursWaiting", () => {
  it("clamps a future signup to zero instead of counting backwards", () => {
    // Clock skew between an operator's laptop and the database, not a negative wait.
    // "in 2 hours" in a waiting column discredits the whole screen.
    expect(hoursWaiting(agoHours(-2), NOW)).toBe(0);
  });

  it("reads an unparseable timestamp as zero rather than NaN", () => {
    expect(hoursWaiting("not a date", NOW)).toBe(0);
  });

  it("floors to whole hours", () => {
    expect(hoursWaiting(agoHours(3.9), NOW)).toBe(3);
  });
});

describe("waitedFor", () => {
  it("says 'under an hour' rather than rendering a future-tensed zero", () => {
    expect(waitedFor(agoHours(0.5), NOW)).toBe("under an hour");
    expect(waitedFor(agoHours(0.5), NOW)).not.toContain("in ");
  });

  it("never renders a wait in the future tense", () => {
    for (const hours of [0, 0.9, 1, 23, 24, 47, 200]) {
      expect(waitedFor(agoHours(hours), NOW), `${hours}h`).not.toMatch(/^in /);
    }
  });

  it("switches from hours to days at a full day, and drops the 'ago'", () => {
    expect(waitedFor(agoHours(5), NOW)).toBe("5 hours");
    expect(waitedFor(agoHours(72), NOW)).toBe("3 days");
  });
});

describe("waitBand", () => {
  it("escalates at the two thresholds and nowhere else", () => {
    expect(waitBand(agoHours(WAIT_WARN_HOURS - 1), NOW)).toBe("neutral");
    expect(waitBand(agoHours(WAIT_WARN_HOURS), NOW)).toBe("warn");
    expect(waitBand(agoHours(WAIT_BREACH_HOURS - 1), NOW)).toBe("warn");
    expect(waitBand(agoHours(WAIT_BREACH_HOURS), NOW)).toBe("stop");
  });
});
