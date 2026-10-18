import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SECOND_READING_REQUEST } from "@/app/c/[slug]/calls/[callId]/AssistCard";
import CallDetailPage from "@/app/c/[slug]/calls/[callId]/page";
import type { Me } from "@/lib/api/client";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage } from "./harness";

/**
 * "A second reading of this call" on the call detail screen (D-127), asked of Pip since
 * D-821. The page only prefills Pip; the reading, its G-6 disclosure, its "nothing was
 * charged" note and the ceiling's wallet dialog are Pip's (`call_summarise_again`,
 * `tests/call_assist_test.py`, `copilotProposalCeiling.test.tsx`). What is pinned here is
 * that the page sends nothing itself and previews the gate.
 */

const CALL = {
  id: "c1",
  agent_id: "a1",
  agent_name: "Reception",
  direction: "inbound",
  status: "completed",
  caller_e164: "+919876500023",
  started_at: "2026-08-14T09:00:00Z",
  duration_s: 62,
  outcome_tag: "resolved",
  sentiment: "neutral",
  summary: "Caller asked about a Tuesday slot.",
  lead_id: null,
  transcript: [
    {
      idx: 0,
      speaker: "agent",
      text: "Namaskaram.",
      lang: "te",
      start_ms: 0,
      redacted: true,
    },
  ],
  extraction: {},
  extraction_valid: true,
  has_recording: false,
  disclosure_played: true,
  moments: [],
  captured: [],
};

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["calls:read", "billing:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

const STAFF: Me = { ...ME, permissions: ["calls:read"] };

function page() {
  return (
    <CallDetailPage params={Promise.resolve({ slug: "acme", callId: "c1" })} />
  );
}

/** The base route table every test needs: identity, the call, and the follow-up read. */
function baseRoutes(me: Me = ME): Record<string, unknown> {
  return {
    "/v1/me": me,
    "/v1/calls/c1": CALL,
    "/v1/calls/c1/callback": {
      eligible: false,
      reason: "already followed up twice",
    },
  };
}

function listenToPip(): AssistantRequest[] {
  const asked: AssistantRequest[] = [];
  function Listener() {
    useAssistantRequests((request) => asked.push(request));
    return null;
  }
  render(<Listener />);
  return asked;
}

describe("a second reading is asked of Pip (D-821)", () => {
  it("prefills Pip with the request and calls nothing itself", async () => {
    const asked = listenToPip();
    const { calls } = await renderClientPage(page(), baseRoutes());
    fireEvent.click(await screen.findByText("A second reading of this call"));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: /^Let Pip write a second reading: / }));
    });
    expect(asked.map((a) => a.prompt)).toEqual([SECOND_READING_REQUEST]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("is previewed as a disabled control with a reason for a session without the permission", async () => {
    await renderClientPage(page(), baseRoutes(STAFF));
    fireEvent.click(await screen.findByText("A second reading of this call"));
    const button = await screen.findByRole("button", { name: /^Let Pip write a second reading: / });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/Only an account owner can use AI help on this call/i)).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = await renderClientPage(page(), baseRoutes());
    fireEvent.click(await screen.findByText("A second reading of this call"));
    await screen.findByRole("button", { name: /^Let Pip write a second reading: / });
    await expectNoA11yViolations(container, "call detail, second reading");
  });
});
