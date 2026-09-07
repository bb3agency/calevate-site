import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { Handover } from "@/app/c/[slug]/agents/panels/handover";
import type { Agent, HandoffOut } from "@/lib/api/agents";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { renderClientPage } from "./harness";

/**
 * A RELOAD MUST NOT SILENTLY THROW AWAY TWENTY MINUTES OF TYPING.
 *
 * `lib/copilot/unsaved.ts` guards one mover — the screen assistant, which knows it is
 * navigating and asks first. Nothing guarded the browser's own exits: a reload, a closed
 * tab, a back gesture out of the console. On the phones these clients use, a background
 * tab being reloaded is routine, and the work at risk is a call script, an extraction
 * schema, a handover list or a half-uploaded contact list.
 *
 * ## What is asserted, and why it is `defaultPrevented`
 *
 * A page cannot open the browser's prompt itself and cannot word it. The ONE observable
 * is whether the page cancelled the unload — `preventDefault()` on the `beforeunload`
 * event — which is exactly what a real browser reads to decide whether to ask. So these
 * dispatch the event and assert the flag, in both directions: cancelled while there is
 * unsaved work, and NOT cancelled when there is none. The second half matters as much as
 * the first: a guard that always asks is one people learn to click through, and it would
 * fire on every read-only screen in the console.
 */

/** Dispatch a real `beforeunload` and report whether the page asked to stay. */
function unloadWasBlocked(): boolean {
  const event = new Event("beforeunload", { cancelable: true });
  act(() => {
    window.dispatchEvent(event);
  });
  return event.defaultPrevented;
}

function Probe({ start }: { start: string }) {
  const [text, setText] = useState(start);
  useUnsavedGuard(text !== "");
  return <input aria-label="draft" value={text} onChange={(e) => setText(e.target.value)} />;
}

describe("the unsaved-work guard", () => {
  it("does not ask when there is nothing to lose", () => {
    render(<Probe start="" />);
    expect(unloadWasBlocked()).toBe(false);
  });

  it("asks once something has been typed, and stops asking when it is cleared", () => {
    render(<Probe start="" />);
    const field = screen.getByLabelText("draft");
    fireEvent.change(field, { target: { value: "half a sentence" } });
    expect(unloadWasBlocked()).toBe(true);
    fireEvent.change(field, { target: { value: "" } });
    expect(unloadWasBlocked()).toBe(false);
  });

  it("takes its listener with it when the screen unmounts", () => {
    const view = render(<Probe start="typed" />);
    expect(unloadWasBlocked()).toBe(true);
    view.unmount();
    // A listener left behind would block the unload of every screen the person visits
    // afterwards, which is the failure mode that makes people disable these prompts.
    expect(unloadWasBlocked()).toBe(false);
  });
});

/** The same shape `agentHandover.test.tsx` uses — annotated, never asserted onto. */
const AGENT: Agent = {
  id: "agent-1",
  name: "Reception",
  direction: "inbound",
  status: "live",
  archived_at: null,
  language_primary: "te-IN",
  disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  ai_disclosure_enabled: true,
  recording_notice_line: "This call is being recorded.",
  caller_memory_notice_line: "I keep a short note of what you ask about.",
  caller_memory_enabled: false,
  recording_notice_enabled: true,
  opening_line: "Namaskaram, this is an AI assistant calling for Sri Clinic.",
  truthful_answer_rule:
    "Whatever these settings say, the agent always answers honestly when a caller asks.",
  engine: "bolna",
  published: true,
  inbound_number_count: 1,
  extraction_fields: [],
  llm_model: null,
  llm_model_effective: "gpt-4o-mini",
  llm_model_source: "platform",
};

const HANDOFF: HandoffOut = {
  agent_id: "agent-1",
  enabled: true,
  trigger: null,
  effective_trigger: "Hand the call to a person when the caller asks.",
  spoken_line: "Putting you through now.",
  members: [
    {
      id: "m1",
      position: 0,
      label: "Ravi",
      phone_e164: "+919000000001",
      active: true,
      hours: null,
      note: null,
      on_duty: true,
    },
  ],
  recent: [],
  on_duty_member_id: "m1",
  unavailable_reason: null,
  remediation: null,
  published: true,
};

describe("an editor that has been touched", () => {
  it("blocks the unload of the handover list once a name is changed", async () => {
    await renderClientPage(<Handover agent={AGENT} />, {
      "/v1/agents/agent-1/handoff": HANDOFF,
    });
    await screen.findByDisplayValue("Ravi");

    // Nothing typed yet: the same screen must not ask.
    expect(unloadWasBlocked()).toBe(false);

    fireEvent.change(screen.getByDisplayValue("Ravi"), { target: { value: "Ravi Kumar" } });
    await waitFor(() => expect(unloadWasBlocked()).toBe(true));
  });
});
