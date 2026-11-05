import { describe, expect, it } from "vitest";

import { businessLabels, statItems } from "@/app/c/[slug]/analyticsFigures";
import { KIND_COPY } from "@/app/c/[slug]/attention/rows";
import { insightWords } from "@/app/c/[slug]/calls/[callId]/InsightsCard";
import { listBlockerNote } from "@/app/c/[slug]/campaigns/blockerCopy";
import { SAMPLE_CSV } from "@/app/c/[slug]/campaigns/contactList";
import { HOME } from "@/app/c/[slug]/_ui/copy";
import type { Stats, StatsMetric } from "@/lib/api/analytics";
import { UNKNOWN_CAPABILITIES } from "@/lib/businessCapabilities";
import { OUTCOME_KIND_WORDS } from "@/lib/callReview";
import { clockRange, clockWords } from "@/lib/clock";
import { GOAL_STAGE, stageLabel } from "@/lib/goalStage";

const metric = (key: StatsMetric["key"], value: string): StatsMetric => ({
  key,
  value,
  previous: value,
  change_pct: "0",
  higher_is_better: true,
});

const WINDOW = { days: 7, from_date: "2026-10-30", to_date: "2026-11-05", timezone: "Asia/Kolkata" } as const;

const STATS: Stats = {
  metrics: [metric("calls", "4"), metric("answer_rate_pct", "100"), metric("leads", "2"), metric("hot_leads", "1")],
  window: WINDOW,
  previous_window: WINDOW,
};

describe("the business's own words (E-HOT, founder 5 Nov 2026)", () => {
  it("never names the hot stage by its key", () => {
    expect(stageLabel("hot")).toBe(GOAL_STAGE);
    expect(stageLabel("interested")).toBe("Interested");
    expect(KIND_COPY.lead_hot.label).toBe(GOAL_STAGE);
    expect(OUTCOME_KIND_WORDS.hot).toBe(GOAL_STAGE);
    const words = [
      ...statItems(STATS, ["calls", "answer_rate_pct", "leads", "hot_leads"], { context: "vs before" }).flatMap(
        (item) => [item.label, item.hint ?? ""],
      ),
      HOME.goalReached(2, "user", "users"),
      HOME.goalReachedAction,
    ].join(" ");
    expect(words.toLowerCase()).not.toContain("hot");
  });

  it("calls a non-selling business's leads by its own caller noun", () => {
    const app = { ...UNKNOWN_CAPABILITIES, sells: false, callerNoun: "user" };
    expect(businessLabels(app)).toEqual({ leads: "Interested users" });
    expect(statItems(STATS, ["leads"], { context: "vs before", caps: app })[0]!.label).toBe("Interested users");
    // Unknown is neutral (lane D, `leadWords`): only a business judged to sell reads "New leads".
    expect(businessLabels(UNKNOWN_CAPABILITIES)).toEqual({ leads: "Interested callers" });
    expect(businessLabels({ ...UNKNOWN_CAPABILITIES, sells: true })).toEqual({});
  });

  it("says an answer is a pick-up, so a hang-up during the greeting is not called a conversation (L3-04)", () => {
    const [rate] = statItems(STATS, ["answer_rate_pct"], { context: "vs before" });
    expect(rate!.hint).toBe("Calls someone picked up");
  });

  it("names a call's sales readings in a non-selling business's terms (G6-8)", () => {
    const app = { ...UNKNOWN_CAPABILITIES, sells: false, hasPremises: false, takesBookings: false };
    const words = insightWords(app);
    expect(words.outcome.promise_to_pay).toBe("Promised to follow up");
    expect(words.step.promise_to_pay).toBe("Promise made");
    expect(words.step.visit).toBe("Meet in person");
    // Unjudged keeps the general words (THE UNKNOWN RULE).
    expect(insightWords(UNKNOWN_CAPABILITIES).outcome.promise_to_pay).toBe("Promised to pay");
  });

  it("gives a campaign row the gate's own count, and a bought list its own refusal (L3-07)", () => {
    expect(listBlockerNote({ consent_provenance_blocker: null, launch_blockers: 5 })?.badge).toBe(
      "Can't launch yet: 5 things to fix",
    );
    expect(listBlockerNote({ consent_provenance_blocker: null, launch_blockers: 0 })).toBeUndefined();
    expect(listBlockerNote({ consent_provenance_blocker: "consent_source_refused", launch_blockers: 3 })?.badge).toBe(
      "Can't be launched: bought list",
    );
  });

  it("samples a column every business has, not a booking (L3-22)", () => {
    expect(SAMPLE_CSV.split("\r\n")[0]).toBe("phone,name,preferred_time");
  });

  it("says a calling window the way every other screen does (L3-23)", () => {
    expect(clockRange("09:00", "21:00")).toBe("9am to 9pm");
    expect(clockWords("13:30")).toBe("1:30pm");
    expect(clockWords("00:00")).toBe("12am");
  });

  it("names the Needs you queue item (L3-03)", () => {
    expect(KIND_COPY.call_needs_you).toMatchObject({ label: "Needs you", action: "Open the call" });
  });
});
