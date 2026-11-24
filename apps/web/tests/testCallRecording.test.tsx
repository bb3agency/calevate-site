import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TestCallList } from "@/app/c/[slug]/campaigns/TestCallList";

import { FIXTURE_CAMPAIGN_ID } from "./campaignFixtures";
import { OWNER_ME } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/**
 * A test call's recording, played under the campaign's Test call form, re-mints its expired
 * link the way the call's own page does: the player stays while it re-mints, and a refused
 * re-mint is the player's own refusal, not an unhandled rejection with the player gone.
 */

const REC_PATH = "/v1/calls/call-1/recording";

beforeEach(() => {
  Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: vi.fn().mockResolvedValue(undefined) });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value: vi.fn() });
});

describe("a test call's recording", () => {
  it("keeps the player and says playback stopped when the fresh link is refused", async () => {
    let mints = 0;
    const { container } = await renderClientPage(<TestCallList slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, {
      "/v1/me": OWNER_ME,
      [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/test-calls`]: [
        { call_id: "call-1", placed_at: "2026-11-16T04:00:00Z", status: "completed", duration_s: 40, has_recording: true },
      ],
      [REC_PATH]: () =>
        ++mints === 1
          ? { url: "https://cdn.example.test/rec.mp3?sig=1", expires_in_s: 600, duration_s: 40 }
          : problem(503, { title: "Storage did not answer", detail: "Try again in a moment." }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Play recording/ }));
    await vi.waitFor(() => expect(container.querySelector("audio")).not.toBeNull());
    fireEvent.error(container.querySelector("audio") as HTMLAudioElement);
    await vi.waitFor(() => expect(mints).toBe(2));
    await vi.waitFor(() =>
      expect(screen.getAllByRole("alert").some((el) => /Playback stopped/i.test(el.textContent ?? ""))).toBe(true),
    );
    expect(container.querySelector("audio")).not.toBeNull();
  });
});
