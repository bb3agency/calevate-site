import { describe, expect, it } from "vitest";

import { callAgainHeld, callAgainTakes } from "@/components/improve/CallAgainCard";

/**
 * "Make a draft for the unanswered" copies a campaign's unreached people. The server allows
 * it from a finished campaign, and from a stopped one with only the people whose tries ran
 * out (`campaign_still_running` otherwise), so the button is held only while it calls or
 * before it has run, with the move that opens it.
 */
describe("calling the unanswered again", () => {
  it("is open for a finished or stopped campaign", () => {
    expect(callAgainHeld("completed")).toBeUndefined();
    expect(callAgainHeld("cancelled")).toBeUndefined();
    expect(callAgainHeld("paused")).toBeUndefined();
  });

  it("is open while the status is not known yet, leaving the answer to the server", () => {
    expect(callAgainHeld(null)).toBeUndefined();
    expect(callAgainHeld(undefined)).toBeUndefined();
  });

  it("is held while it calls, and before it has run", () => {
    expect(callAgainHeld("running")).toMatch(/still calling/);
    expect(callAgainHeld("draft")).toMatch(/has run/);
    expect(callAgainHeld("scheduled")).toMatch(/has run/);
  });

  it("says a stopped campaign gives only the people whose tries ran out", () => {
    expect(callAgainTakes("paused")).toMatch(/tries ran out/);
    expect(callAgainTakes("completed")).toMatch(/never reached/);
  });
});
