import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/api/client";

import {
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  contactsFixture,
  contactsPath,
  detailRoutes,
  progressFixture,
} from "./campaignFixtures";
import { renderClientPage, type Routes } from "./harness";

/**
 * The campaign page's first block changes with the campaign's status: a draft is a launch
 * panel with what pressing Call does beside it, a scheduled campaign leads with when it
 * starts and how to cancel, and a launched one is the live panel with no launch left on
 * the page. Asserted through the rendered page, because the risk is a branch rendering two
 * bands at once or none.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function routes(progress: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    "/v1/agents": [],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    ...extra,
  };
}

const PERSON = {
  id: "cc-1",
  name: "Lakshmi",
  phone_e164: "+919876500007",
  outcome: "not_called" as const,
  attempts: 0,
  last_attempt_at: null,
  will_retry: false,
  next_attempt_at: null,
  call_id: null,
};

describe("the status band", () => {
  it("is a launch panel for a draft, with what pressing Call does beside it", async () => {
    const { container } = await renderClientPage(campaignPage(), routes(progressFixture({ total: 3 })));
    await screen.findByRole("heading", { name: "Before you launch" });
    expect(screen.getByRole("button", { name: "Call 3 people" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "What launching does" }).textContent).toContain("3 people");
    // Starting later and repeating are two option cards, not one hidden panel.
    expect(screen.getByRole("heading", { name: "Start later" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Repeat every week" })).toBeTruthy();
    expect(container.textContent).not.toContain("Right now");
  });

  it("leads a scheduled campaign with its start and the way out, then the same check", async () => {
    await renderClientPage(
      campaignPage(),
      routes(
        progressFixture({
          status: "scheduled",
          total: 3,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: [],
        }),
      ),
    );
    const scheduled = await screen.findByRole("heading", { name: "Scheduled" });
    const before = screen.getByRole("heading", { name: "Before it starts" });
    // The start comes first in the band, the check under it.
    expect(scheduled.compareDocumentPosition(before) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel scheduled start" })).toBeTruthy();
    // A scheduled campaign can only add a repeat; its start is already set.
    expect(screen.queryByRole("heading", { name: "Start later" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Repeat every week" })).toBeTruthy();
  });

  it("is the live panel once launched, with no launch or schedule forms left", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      routes(progressFixture({ status: "running", launched_at: "2026-10-14T04:30:00Z", total: 4, contacts: { pending: 4 } })),
    );
    await screen.findByRole("heading", { name: "Right now" });
    expect(container.textContent).not.toContain("Before you launch");
    expect(screen.queryByRole("button", { name: /^Call \d/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Start later" })).toBeNull();
  });

  it("shows a finished campaign's progress, not a live panel", async () => {
    await renderClientPage(
      campaignPage(),
      routes(
        progressFixture({ status: "completed", launched_at: "2026-10-14T04:30:00Z", total: 4, contacts: { completed: 4 } }),
      ),
    );
    await screen.findByRole("heading", { name: "Progress" });
    expect(screen.queryByRole("heading", { name: "Right now" })).toBeNull();
    expect(screen.getByText("Finished. Every try has been made.")).toBeTruthy();
  });
});

describe("the people before launch", () => {
  it("lists them in a table and takes one off from the row's menu", async () => {
    const rendered = await renderClientPage(
      campaignPage(),
      routes(progressFixture({ total: 1 }), {
        [contactsPath()]: contactsFixture({
          total: 1,
          counts: { ...contactsFixture().counts, not_called: 1 },
          items: [PERSON],
        }),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/contacts/remove`]: { removed: 1 },
      }),
    );
    const table = await screen.findByRole("table", { name: "People on this campaign" });
    expect(within(table).getByText("Lakshmi")).toBeTruthy();
    // No bordered Remove button on every row: one quiet menu per row.
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    fireEvent.click(within(table).getByRole("button", { name: "More actions for Lakshmi" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Take Lakshmi off this campaign" }));
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "POST" && c.path.endsWith("/contacts/remove"));
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent).toEqual({ contact_ids: ["cc-1"] });
  });
});
