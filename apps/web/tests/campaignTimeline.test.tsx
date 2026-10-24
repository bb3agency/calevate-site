import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { sinceLaunch } from "@/app/c/[slug]/campaigns/CampaignTimeline";
import type { Me } from "@/lib/api/client";

import {
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  detailRoutes,
  progressFixture,
  timelinePath,
} from "./campaignFixtures";
import { problem, renderClientPage } from "./harness";

/**
 * A launched campaign's day-by-day chart (`GET /v1/analytics/campaigns`): the days since
 * launch, one measure drawn at a time, and all three measures said in words for the days
 * the window covers.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch", "calls:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const day = (ist_date: string, dials: number, connected: number, leads: number) => ({ ist_date, dials, connected, leads });

function routes(timeline: unknown) {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({ status: "running", launched_at: "2026-10-14T04:30:00Z" }),
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    [timelinePath()]: timeline,
  };
}

describe("the days a campaign chart draws", () => {
  const days = Array.from({ length: 20 }, (_, i) => day(`2026-10-${String(i + 1).padStart(2, "0")}`, 0, 0, 0));

  it("starts on the launch day, in India time", () => {
    // 04:30 UTC on the 14th is 10:00 IST on the 14th.
    expect(sinceLaunch(days, "2026-10-14T04:30:00Z")[0].ist_date).toBe("2026-10-14");
    // 20:00 UTC on the 13th is already the 14th in India.
    expect(sinceLaunch(days, "2026-10-13T20:00:00Z")[0].ist_date).toBe("2026-10-14");
  });

  it("keeps at least the last week, so a new campaign still has a line", () => {
    expect(sinceLaunch(days, "2026-10-19T04:30:00Z")).toHaveLength(7);
    expect(sinceLaunch(days, null)).toHaveLength(7);
  });
});

describe("a launched campaign's day-by-day chart", () => {
  it("draws one measure and says all three for the days shown", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      routes({
        window: { days: 366, from_date: "2025-10-25", to_date: "2026-10-24", timezone: "Asia/Kolkata" },
        campaigns: [
          {
            campaign_id: CAMPAIGN_ID,
            name: "Diwali offer",
            status: "running",
            dials: 30,
            connected: 12,
            leads: 3,
            days: [day("2026-10-13", 0, 0, 0), day("2026-10-14", 10, 4, 1), day("2026-10-15", 20, 8, 2)],
          },
        ],
      }),
    );
    await screen.findByRole("heading", { name: "Day by day" });
    expect(await screen.findByText(/In the days shown/)).toBeTruthy();
    expect(container.textContent).toContain("30 calls made, 12 answered, 3 new leads.");
    fireEvent.click(screen.getByRole("radio", { name: "Leads" }));
    expect(container.textContent).toContain("New leads per day");
  });

  it("says nothing has gone out rather than drawing a flat line", async () => {
    await renderClientPage(
      campaignPage(),
      routes({
        window: { days: 366, from_date: "2025-10-25", to_date: "2026-10-24", timezone: "Asia/Kolkata" },
        campaigns: [],
      }),
    );
    expect(await screen.findByText(/No calls have gone out yet/)).toBeTruthy();
  });

  it("says the read failed in words, never as zeros", async () => {
    await renderClientPage(campaignPage(), routes(problem(503, { title: "Unavailable" })));
    expect(await screen.findByText(/could not load this campaign's day-by-day figures/)).toBeTruthy();
  });
});
