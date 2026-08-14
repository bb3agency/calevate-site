import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import type { Agent } from "@/lib/api/agents";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import { scheduleStartAt } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * Scheduling a campaign start, from the screen.
 *
 * The launch panel authorises; this is the same authorisation with a delay on it, and
 * the delay is where the two mistakes live:
 *
 * 1. **The time the client picks could be sent as the wrong instant.** The pickers give
 *    a local wall clock. Sent without an offset, or with the VIEWER's offset, "10:00"
 *    becomes 10:00 wherever the browser happens to be — 15:30 IST for an operator
 *    viewing the account from London (D-22 makes that a real session). The wire body is
 *    asserted character for character for that reason: it is the only place in the whole
 *    feature where the client's intent is turned into an instant.
 *
 * 2. **A scheduled campaign could become a status and nothing else.** It is neither a
 *    draft nor running, so it falls between the two cards this screen was built from. A
 *    client would see the word "scheduled", no date, no way to cancel, and — when the
 *    gate refuses the start — no reason. §52: loading is a skeleton, failure is a
 *    refusal, and neither is a state.
 */

const CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";
const AGENT_ID = "0192f0aa-3333-7000-8000-000000000002";

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT = {
  id: AGENT_ID,
  name: "Outbound follow-up",
  direction: "outbound",
  status: "live",
  language_primary: "te",
} as unknown as Agent;

const CAMPAIGN: CampaignSummary = {
  id: CAMPAIGN_ID,
  name: "Diwali offer",
  status: "draft",
  classification: "promotional",
  contacts: 120,
  connected: 0,
  launched_at: null,
  consent_provenance_blocker: null,
} as unknown as CampaignSummary;

const READY: LaunchCheck = { ready: true, blockers: [] } as unknown as LaunchCheck;

function progress(extra: Record<string, unknown>): CampaignProgress {
  return { contacts: {}, total: 0, concurrency: 3, ...extra } as unknown as CampaignProgress;
}

async function openCampaign(
  routes: Record<string, unknown>,
  waitFor: string,
): Promise<Awaited<ReturnType<typeof renderClientPage>>> {
  const rendered = await renderClientPage(<CampaignsPage />, {
    "/v1/me": ME,
    "/v1/campaigns": [CAMPAIGN],
    "/v1/agents": [AGENT],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: READY,
    ...routes,
  });
  fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
  await screen.findByText(waitFor);
  return rendered;
}

describe("turning a picked time into an instant", () => {
  it("attaches IST, not the viewer's offset, so 10:00 means 10:00 in India", () => {
    // The whole point of the helper, and the one assertion that would still hold if the
    // machine running these tests were in another timezone: the string carries +05:30.
    expect(scheduleStartAt("2026-08-17", "10:00")).toBe("2026-08-17T10:00:00+05:30");
    expect(scheduleStartAt("2026-08-17", "22:00")).toBe("2026-08-17T22:00:00+05:30");
  });

  it("refuses to guess at an incomplete pair rather than inventing a start", () => {
    expect(scheduleStartAt("", "10:00")).toBeNull();
    expect(scheduleStartAt("2026-08-17", "")).toBeNull();
    expect(scheduleStartAt("not-a-date", "10:00")).toBeNull();
  });
});

describe("scheduling from the launch card", () => {
  it("sends the picked time with its IST offset attached", async () => {
    const { calls } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: {
          start_at: "2026-08-17T04:30:00+00:00",
          first_dial_not_before: "2026-08-17T04:30:00+00:00",
        },
      },
      "Before you launch",
    );

    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    fireEvent.change(screen.getByLabelText("Start time (IST)"), { target: { value: "10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Schedule start" }));

    const sent = await vi.waitUntil(
      () => calls.find((c) => c.method === "POST" && c.path.endsWith("/schedule")),
      { timeout: 2000 },
    );
    // Character for character: a body of `{"start_at":"2026-08-17T10:00:00"}` is the
    // bug this test exists for, and it is one the server would refuse — but only after
    // the client had already been shown a working-looking form.
    expect(sent.body).toBe('{"start_at":"2026-08-17T10:00:00+05:30"}');
  });

  it("keeps the button dead until both halves of the time are picked", async () => {
    await openCampaign(
      { [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }) },
      "Before you launch",
    );
    const button = screen.getByRole("button", { name: "Schedule start" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    expect(button.disabled).toBe(false);
  });

  it("says the gate runs again at the start, not only now", async () => {
    // "Everything checks out" is true about this second. A client who read it as a
    // promise about Monday would treat a refused start as a malfunction.
    const { container } = await openCampaign(
      { [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }) },
      "Before you launch",
    );
    expect(container.textContent).toContain(
      "We check every one of these requirements again at the moment it starts",
    );
  });
});

describe("a campaign waiting for its start", () => {
  it("says WHEN, and offers the way out", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: [],
        }),
      },
      "Scheduled",
    );

    // 04:30Z rendered in IST is 10:00 — the hour the client picked, given back to them
    // in the only timezone this product runs in.
    expect(container.textContent).toContain("10:00");
    expect(screen.getByRole("button", { name: "Cancel scheduled start" })).toBeTruthy();
    // And the launch gate's list is still on screen, because it is still the question:
    // the server re-runs exactly this check when the schedule fires.
    expect(container.textContent).toContain("Before it starts");
  });

  it("says the start was refused rather than letting it expire in silence", async () => {
    const { container } = await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
          status: "scheduled",
          launched_at: null,
          scheduled_start_at: "2026-08-17T04:30:00+00:00",
          schedule_blocked_rules: ["dlt_template_not_approved"],
        }),
      },
      "Scheduled",
    );
    expect(container.textContent).toContain("We tried to start this campaign and could not");
    expect(container.textContent).toContain("goes back to draft");
    // The rule NAME is the gate's vocabulary, never the client's reading.
    expect(container.textContent).not.toContain("dlt_template_not_approved");
  });

  it("shows a skeleton while the start time is still loading, never a bare status", async () => {
    // The card is reached through the campaign LIST, which already carries the status;
    // the date comes from a second request. Rendering "Starts —" in the gap is a
    // sentence about a campaign that is not true yet.
    const rendered = await renderClientPage(<CampaignsPage />, {
      "/v1/me": ME,
      "/v1/campaigns": [{ ...CAMPAIGN, status: "scheduled" }],
      "/v1/agents": [AGENT],
      "/v1/campaigns/numbers": [],
      "/v1/campaigns/templates": [],
      [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: READY,
      [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({
        status: "scheduled",
        launched_at: null,
        scheduled_start_at: "2026-08-17T04:30:00+00:00",
        schedule_blocked_rules: [],
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: CAMPAIGN.name }));
    await screen.findByText("Scheduled");
    expect(rendered.container.textContent).toContain("10:00");
  });

  it("renders the server's refusal when a schedule is rejected", async () => {
    // §52: failure is a refusal. A start in the past, or a campaign somebody launched
    // from another tab, comes back as problem+json and has to reach the screen — a form
    // that simply does not change is the client pressing the button again.
    await openCampaign(
      {
        [`/v1/campaigns/${CAMPAIGN_ID}`]: progress({ status: "draft", launched_at: null }),
        [`POST /v1/campaigns/${CAMPAIGN_ID}/schedule`]: problem(422, {
          title: "Start time is in the past",
          detail: "A campaign can only be scheduled to start in the future.",
        }),
      },
      "Before you launch",
    );
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-08-17" } });
    fireEvent.click(screen.getByRole("button", { name: "Schedule start" }));
    expect(
      await screen.findByText("A campaign can only be scheduled to start in the future."),
    ).toBeTruthy();
  });
});
