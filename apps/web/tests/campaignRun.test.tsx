import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { campaignRun } from "@/app/c/[slug]/campaigns/campaignProgress";
import type { Me } from "@/lib/api/client";

import {
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  detailRoutes,
  progressFixture,
} from "./campaignFixtures";
import { renderClientPage } from "./harness";

/**
 * A launched campaign's progress as steps (founder, 15 Oct 2026: the steps stay on screen
 * while the campaign runs). The steps are read from the progress response alone, so the
 * premises here are counts the server sends and the step each one must land on.
 */

const LAUNCHED = { status: "running", launched_at: "2026-10-14T04:30:00Z" } as const;

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

describe("where a campaign is in its run", () => {
  it("is calling everyone once while anyone has never been tried", () => {
    const run = campaignRun(
      progressFixture({
        ...LAUNCHED,
        contacts: { pending: 60, dialing: 2, connected: 30, failed: 6, dnc_blocked: 2 },
        total: 100,
        retries_waiting: 10,
      }),
    );
    expect(run.steps[run.current].id).toBe("first");
    expect(run.hold).toBeUndefined();
    // 2 on do-not-call are not callable; 50 never tried; the rest are called.
    expect(run.callable).toBe(98);
    expect(run.notCalled).toBe(50);
    expect(run.called).toBe(48);
    expect(run.steps.slice(0, run.current).map((s) => s.id)).toEqual(["list", "checks"]);
  });

  it("moves on to retrying once everyone has had a first try", () => {
    const run = campaignRun(
      progressFixture({ ...LAUNCHED, contacts: { pending: 8, connected: 80, failed: 12 }, total: 100, retries_waiting: 8 }),
    );
    expect(run.steps[run.current].id).toBe("retry");
    expect(run.called).toBe(100);
  });

  it("has no retry step for a campaign that tries each person once", () => {
    const run = campaignRun(
      progressFixture({ ...LAUNCHED, retry_policy: { max_attempts: 1, gaps_minutes: [] } }),
    );
    expect(run.steps.map((s) => s.id)).not.toContain("retry");
  });

  it("holds a paused or blocked campaign on its step instead of spinning", () => {
    const paused = campaignRun(
      progressFixture({ ...LAUNCHED, status: "paused", pause_reason: "out_of_credit", contacts: { pending: 5 }, total: 5 }),
    );
    expect(paused.hold).toBe("paused");
    const blocked = campaignRun(
      progressFixture({
        ...LAUNCHED,
        contacts: { pending: 5 },
        total: 5,
        not_calling: [{ rule: "agent_not_published", reason: "The agent is not live." }],
      }),
    );
    expect(blocked.hold).toBe("paused");
  });

  it("ends stopped for good, or with every step done", () => {
    const stopped = campaignRun(progressFixture({ ...LAUNCHED, status: "cancelled", contacts: { pending: 4, connected: 1 }, total: 5 }));
    expect(stopped.hold).toBe("stopped");
    expect(stopped.steps[stopped.current].label).toBe("Stopped for good");
    const done = campaignRun(progressFixture({ ...LAUNCHED, status: "completed", contacts: { connected: 5 }, total: 5 }));
    expect(done.current).toBe(done.steps.length);
  });
});

describe("a running campaign's page", () => {
  it("opens on its progress, with the steps, ahead of its results", async () => {
    const { container } = await renderClientPage(campaignPage(), {
      "/v1/me": ME,
      ...detailRoutes(),
      [`/v1/campaigns/${CAMPAIGN_ID}`]: progressFixture({
        ...LAUNCHED,
        contacts: { pending: 60, dialing: 2, connected: 38 },
        total: 100,
      }),
      [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    });
    const steps = await screen.findByRole("list", { name: "Where this campaign is" });
    const current = within(steps).getAllByRole("listitem").find((li) => li.getAttribute("aria-current") === "step");
    expect(current?.textContent).toContain("Calling everyone once");
    const headings = Array.from(container.querySelectorAll("h2")).map((h) => h.textContent);
    expect(headings.indexOf("Progress")).toBeGreaterThanOrEqual(0);
    expect(headings.indexOf("Progress")).toBeLessThan(headings.indexOf("Results"));
    expect(container.textContent).toContain("of 100 people called");
  });
});
