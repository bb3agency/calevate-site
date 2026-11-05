import { describe, expect, it } from "vitest";

import { businessLabels, statItems } from "@/app/c/[slug]/analyticsFigures";
import { KIND_COPY } from "@/app/c/[slug]/attention/rows";
import { HOME } from "@/app/c/[slug]/_ui/copy";
import type { Stats } from "@/lib/api/analytics";
import { UNKNOWN_CAPABILITIES } from "@/lib/businessCapabilities";
import { OUTCOME_KIND_WORDS } from "@/lib/callReview";
import { GOAL_STAGE, stageLabel } from "@/lib/goalStage";

const metric = (key: Stats["metrics"][number]["key"], value: string) => ({
  key,
  value,
  previous: value,
  change_pct: "0",
  higher_is_better: true,
});

const STATS = {
  metrics: [metric("calls", "4"), metric("answer_rate_pct", "100"), metric("leads", "2"), metric("hot_leads", "1")],
} as unknown as Stats;

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
    expect(businessLabels(UNKNOWN_CAPABILITIES)).toEqual({});
  });

  it("says an answer is a pick-up, so a hang-up during the greeting is not called a conversation (L3-04)", () => {
    const [rate] = statItems(STATS, ["answer_rate_pct"], { context: "vs before" });
    expect(rate!.hint).toBe("Calls someone picked up");
  });

  it("names the Needs you queue item (L3-03)", () => {
    expect(KIND_COPY.call_needs_you).toMatchObject({ label: "Needs you", action: "Open the call" });
  });
});
