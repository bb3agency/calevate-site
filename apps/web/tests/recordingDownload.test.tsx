import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import type { CallDetail, Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * "Download recording" beside the player's speed and volume (founder, 11 Oct 2026).
 *
 * The same rules as playing: owner-only (`calls:read_raw`), minted on the press through
 * the audited route (`GET /v1/calls/{id}/recording/download`, its own `recording.download`
 * audit row on the server), and never left behind as a link in the page.
 */

const page = <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />;
const DOWNLOAD = "/v1/calls/c1/recording/download";

function me(permissions: string[]): Me {
  return {
    user_id: "u1",
    realm: "client",
    role: "owner",
    permissions,
    impersonating: false,
    withheld_acts: [],
    organization: { id: "o1", name: "Raghava Organics", slug: "acme", status: "active" },
  };
}

function detail(): CallDetail {
  return {
    id: "c1",
    agent_id: "a1",
    agent_name: "Reception",
    direction: "outbound",
    status: "completed",
    caller_e164: "+919876543210",
    started_at: "2026-10-10T12:22:00Z",
    duration_s: 64,
    outcome_tag: "answered",
    summary_state: "ready",
    test_call: false,
    caller_id_hidden: false,
    forwarding_test: false,
    translation_state: "not_needed",
    language: "en-IN",
    sentiment: "neutral",
    summary: "Asked about chilli.",
    lead_id: "l1",
    extraction: {},
    captured: [],
    extraction_valid: true,
    has_recording: true,
    disclosure_played: true,
    moments: [],
    quality: null,
    signals: [],
    transcript: [{ idx: 0, speaker: "agent", text: "Hello.", redacted: true, start_ms: 0, start_approximate: false, likely_cut_off: false }],
  };
}

function routes(permissions: string[], download: unknown) {
  return {
    "/v1/me": me(permissions),
    "/v1/calls/c1": detail(),
    "/v1/calls/c1/callback": { eligible: false, reason: "This call was answered.", rule: null },
    "/v1/calls/c1/recording": { url: "https://cdn.example.test/rec.mp3?sig=play", expires_in_s: 300, duration_s: 64 },
    [DOWNLOAD]: download,
  };
}

const OWNER = ["calls:read", "calls:read_raw", "leads:read"];
const FILE = {
  url: "https://cdn.example.test/rec.mp3?sig=save",
  filename: "raghava-organics-call-2026-10-10-1752.mp3",
  expires_in_s: 300,
};

let clicked: string[];
beforeEach(() => {
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this.href);
  });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value: vi.fn() });
});
afterEach(() => vi.restoreAllMocks());

async function openPlayer() {
  fireEvent.click(await screen.findByRole("button", { name: "Listen to this call" }));
  await screen.findByRole("button", { name: "Play recording" });
}

describe("downloading the recording", () => {
  it("is offered beside the player, minted on the press, and leaves no link behind", async () => {
    const { calls } = await renderClientPage(page, routes(OWNER, FILE));
    await openPlayer();
    expect(calls.some((c) => c.path === DOWNLOAD)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Download recording" }));
    await waitFor(() => expect(clicked).toEqual([FILE.url]));
    expect(calls.filter((c) => c.path === DOWNLOAD)).toHaveLength(1);
    expect(document.querySelector(`a[href="${FILE.url}"]`)).toBeNull();
  });

  it("is not offered to a role that cannot play the recording", async () => {
    await renderClientPage(page, routes(["calls:read", "leads:read"], FILE));
    await openPlayer();
    expect(screen.queryByRole("button", { name: "Download recording" })).toBeNull();
  });

  it("says in a sentence that a deleted recording is no longer kept", async () => {
    const detailText = "Recordings are kept for 90 days, and this one has been deleted. The transcript and summary stay.";
    await renderClientPage(
      page,
      routes(OWNER, problem(404, { kind: "not_found", type: "https://calevate.tech/problems/recording_expired", title: "This recording is no longer kept", detail: detailText })),
    );
    await openPlayer();
    fireEvent.click(screen.getByRole("button", { name: "Download recording" }));
    expect((await screen.findByRole("alert")).textContent).toBe(detailText);
    expect(clicked).toEqual([]);
  });
});
