import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignNotes, notesTakeEffect } from "@/app/c/[slug]/campaigns/CampaignNotes";

import { FIXTURE_AGENT_ID, FIXTURE_CAMPAIGN_ID, notesFixture } from "./campaignFixtures";
import { problem, renderClientPage } from "./harness";
import { OWNER_ME } from "./fixtures/sharedReads";

/**
 * A campaign's What it notes: when a saved list reaches its calls, and a save the server
 * refused is said in both of the editor's modes.
 */

const notesPath = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/notes`;
const FIELD = {
  key: "visit_day",
  label: "Visit day",
  type: "text" as const,
  reason: "when",
  required: false,
};

describe("a campaign's What it notes", () => {
  it("says when a saved list reaches its calls, by the campaign's state", () => {
    expect(notesTakeEffect(true, "running")).toBe("From its next call.");
    // Running without its own calling agent yet: its next dial makes one.
    expect(notesTakeEffect(false, "running")).toBe("From its next call.");
    expect(notesTakeEffect(false, "paused")).toBe("From its next call.");
    expect(notesTakeEffect(false, "completed")).toBe("From its next Start.");
    expect(notesTakeEffect(false, "cancelled")).toBe("From its next Start.");
    expect(notesTakeEffect(false, "draft")).toBe("From its first call.");
    expect(notesTakeEffect(false, "scheduled")).toBe("From its first call.");
  });

  it("says why going back to the agent's list was refused", async () => {
    await renderClientPage(
      <CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} agentId={FIXTURE_AGENT_ID} status="running" canWrite />,
      {
        "/v1/me": OWNER_ME,
        [notesPath]: notesFixture({ fields: [FIELD], digest: "own" }),
        [`PUT ${notesPath}`]: problem(422, {
          type: "https://calevate.tech/problems/engine_unavailable",
          title: "Saved, but not on its calls yet",
          status: 422,
          detail: "The calling platform did not answer.",
        }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Use .*list$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The calling platform did not answer.")).toBeTruthy();
  });

  it("links Set alerts as a button to its agent's alerts", async () => {
    await renderClientPage(
      <CampaignNotes slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} agentId={FIXTURE_AGENT_ID} canWrite />,
      { "/v1/me": OWNER_ME, [notesPath]: notesFixture({ fields: [FIELD] }) },
    );
    const link = await screen.findByRole("link", { name: "Set alerts" });
    expect(link.getAttribute("href")).toBe(`/c/acme/agents/${FIXTURE_AGENT_ID}?section=settings#team-alerts`);
    // A button, so a thumb can hit it: the shared small button grows to 44 px on touch.
    expect(link.className).toContain("touch:min-h-11");
    await waitFor(() => expect(screen.getByText("From its first call.", { exact: false })).toBeTruthy());
  });
});
