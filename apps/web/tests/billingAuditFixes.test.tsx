import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CostPerResult } from "@/app/c/[slug]/billing/CostPerResult";
import { monthTiles } from "@/app/c/[slug]/billing/UsageTab";
import { toTier } from "@/app/c/[slug]/billing/VoiceTiers";
import { UNNAMED_STATUS_LABEL, stateLabel } from "@/app/c/[slug]/verify-business/copy";
import type { UsagePanel } from "@/lib/api/hooks";
import type { KycRecord } from "@/lib/api/kyc";
import type { VoiceTierCompare } from "@/lib/api/voiceTiers";
import { useClientRealm } from "@/lib/api/session";

import { renderClientPage } from "./harness";
import { OWNER_ME } from "./fixtures/sharedReads";

/** E2E audit 5 Nov 2026, lane F: billing figures that told an owner something untrue. */

function usage(over: Partial<UsagePanel>): UsagePanel {
  return {
    plan_tier: "self_serve",
    minutes_used: "12.5000",
    calls: 6,
    included_minutes: 0,
    overage_minutes: "12.5000",
    overage_cost_inr: "0.00",
    overage_rate_inr: "0.00",
    month_charges_inr: "56.25",
    trial: { active: false, days_remaining: null, ends_at: null },
    ...over,
  } as UsagePanel;
}

describe("the month's tiles (OB-4)", () => {
  it("shows a prepaid wallet what it spent, never plan overage", () => {
    const tiles = monthTiles(usage({}));
    expect(tiles.map((tile) => tile.label)).toEqual(["Minutes used", "Calls", "Spent this month"]);
    expect(tiles[2].value).toBe("₹56.3");
    expect(tiles[2].hint).toBe("Taken from your credit");
  });

  it("says a trial charged nothing", () => {
    const tiles = monthTiles(usage({ month_charges_inr: "0.00", trial: { active: true, days_remaining: 3, ends_at: null } }));
    expect(tiles[2].hint).toBe("Free trial: nothing charged");
  });

  it("keeps the overage tiles for an invoiced plan", () => {
    const labels = monthTiles(usage({ plan_tier: "managed", included_minutes: 500 })).map((tile) => tile.label);
    expect(labels).toContain("Extra charges");
  });
});

const CLOSED_TIER: VoiceTierCompare = {
  tier: "clear",
  label: "Clear",
  offered: false,
  from_inr_per_min: "4.0000",
  to_inr_per_min: "5.0000",
  your_inr_per_min: null,
  minutes_left: null,
  minutes_this_month: "0.0000",
  charged_this_month_inr: "0.00",
  includes: ["The lowest price per minute"],
  best_for: "Most businesses: enquiries, bookings, reminders and follow-ups.",
};

describe("a voice tier that cannot be chosen (OB-5)", () => {
  it("offers no benefits, no 'best for', and its reason behind a tap", () => {
    const tier = toTier(CLOSED_TIER, "Not open yet: we are still confirming what this voice costs to run.");
    expect(tier.includes).toEqual([]);
    expect(tier.bestFor).toBe("");
    render(<>{tier.summary}</>);
    expect(screen.getByText("Not open yet.")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/vendor/i);
  });
});

function CostCard() {
  const { session } = useClientRealm();
  return <CostPerResult session={session} allowed goalsHref="/c/acme/settings/lead-details" />;
}

describe("what each result cost (OB-14)", () => {
  it("does not say a lead cost ₹0 when nothing was charged", async () => {
    const window = {
      days: 30,
      from_date: "2026-10-07",
      to_date: "2026-11-05",
      spent_inr: "0.00",
      answered_calls: 6,
      leads: 3,
      goals_reached: 0,
      per_answered_call_inr: "0.00",
      per_lead_inr: "0.00",
      per_goal_inr: null,
    };
    await renderClientPage(<CostCard />, {
      "/v1/me": OWNER_ME,
      "/v1/analytics/cost-per-result": {
        billing_step_seconds: 30,
        goal_labels: [],
        windows: [window, { ...window, days: 7 }],
      },
    });
    expect((await screen.findAllByText("No charges in this period")).length).toBe(2);
    expect(screen.getAllByText("—")).toHaveLength(2);
  });
});

describe("a verification status this build cannot name (OB-28)", () => {
  it("reads as a plain word, never the code", () => {
    const record = { recorded: true, status: "manual_hold_v3" } as unknown as KycRecord;
    expect(stateLabel(record)).toBe(UNNAMED_STATUS_LABEL);
  });
});
