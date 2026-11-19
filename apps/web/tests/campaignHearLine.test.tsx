import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HearLine, type FlowAgent } from "@/app/c/[slug]/campaigns/LineCoach";
import type { WriteAccess } from "@/lib/api/hooks";
import type { ClientVoiceTuning } from "@/lib/api/voiceTuning";

import { renderClientPage } from "./harness";

/*
 * "Hear it in <agent>'s voice" beside a scenario's line spends one of the account's samples,
 * and the route that speaks it is the owner's (`org:manage`). Anyone else sees the button
 * closed with the reason on it, and pressing it sends nothing.
 */

const AGENT = "0192f0aa-8888-7000-8000-0000000000c3";
const PATH = `/v1/agents/${AGENT}/voice-tuning`;

const agent: FlowAgent = { id: AGENT, name: "Asha", voiceId: "byok:cv-1", missing: null };

const tuning: ClientVoiceTuning = {
  agent_id: AGENT,
  studio: true,
  speed: null,
  volume: null,
  emotion: null,
  options: {
    speed_min: "0.6",
    speed_max: "1.5",
    speed_step: "0.01",
    volume_min: "0.5",
    volume_max: "2.0",
    emotions: ["neutral"],
    previews_per_day: 20,
  },
  previews_left_today: 20,
};

const OWNER: WriteAccess = { allowed: true, reason: null, unknown: false };
const STAFF: WriteAccess = {
  allowed: false,
  reason: "Only an account owner can hear a line in the agent's voice.",
  unknown: false,
};

const mount = (access: WriteAccess) =>
  renderClientPage(<HearLine agent={agent} access={access} language="en-IN" line="Hello, this is Asha." />, {
    [PATH]: tuning,
  });

describe("hearing a scenario's line", () => {
  it("is closed, with the reason on it, for someone who is not the owner", async () => {
    const view = await mount(STAFF);
    const button = (await screen.findByRole("button", { name: "Hear it in Asha's voice" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toBe(STAFF.reason);
    fireEvent.click(button);
    expect(view.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("is open for the owner", async () => {
    await mount(OWNER);
    const button = (await screen.findByRole("button", { name: "Hear it in Asha's voice" })) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.title).toBe("Speaks the start of this line in the agent's voice.");
  });
});
