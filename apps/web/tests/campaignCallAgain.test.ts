import { describe, expect, it } from "vitest";

import { callAgainHeld } from "@/app/c/[slug]/campaigns/CampaignBoosters";

/**
 * "Make a draft for the unanswered" copies a campaign's unreached people, which the server
 * allows only from a finished campaign (`campaign_still_running` otherwise). Stop on the
 * campaign screen is a pause, so a stopped campaign is not finished: the button is held with
 * the move that opens it, rather than offered and refused.
 */
describe("calling the unanswered again", () => {
  it("is open for a finished campaign", () => {
    expect(callAgainHeld("completed")).toBeUndefined();
    expect(callAgainHeld("cancelled")).toBeUndefined();
  });

  it("is open while the status is not known yet, leaving the answer to the server", () => {
    expect(callAgainHeld(null)).toBeUndefined();
    expect(callAgainHeld(undefined)).toBeUndefined();
  });

  it("is held for a stopped campaign, saying to start it and let it finish", () => {
    expect(callAgainHeld("paused")).toMatch(/Start it again and let it finish/);
  });

  it("is held while it calls, and before it has run", () => {
    expect(callAgainHeld("running")).toMatch(/still calling/);
    expect(callAgainHeld("draft")).toMatch(/run and finished/);
    expect(callAgainHeld("scheduled")).toMatch(/run and finished/);
  });
});
