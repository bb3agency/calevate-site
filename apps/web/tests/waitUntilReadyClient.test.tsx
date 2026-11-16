import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LaunchConfirm } from "@/app/c/[slug]/campaigns/LaunchConfirm";
import { TrialCallCard, callWait } from "@/app/c/[slug]/TrialCallPanel";
import type { TestCall, TrialPanel } from "@/lib/api/trialCalls";

import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * "Wait until it is ready" on the client screens (founder, 1 Nov 2026): a control whose
 * dependency is still happening is greyed with its reason beside it, ignores presses, and
 * comes back by itself when the dependency lands or fails.
 *
 * Asserted on `aria-disabled` plus the reason the button is described by, the convention in
 * `components/arc/feedback.tsx` (`waitingFor`).
 */

afterEach(cleanup);

function button(name: string | RegExp): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

function waitingReason(el: HTMLElement): string | null {
  if (el.getAttribute("aria-disabled") !== "true") return null;
  const ids = (el.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
  const text = ids.map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim();
  return text || null;
}

describe("Launch waits for the launch check it relies on", () => {
  const confirm = (waiting: string | null, onLaunch = vi.fn()) => (
    <LaunchConfirm
      contacts={3}
      canWrite
      writeReason={undefined}
      status="idle"
      onLaunch={onLaunch}
      waiting={waiting}
    />
  );

  it("holds the Call button while the check re-runs, then lets it dial", () => {
    const onLaunch = vi.fn();
    const { rerender } = render(confirm("Checking your campaign again", onLaunch));
    expect(waitingReason(button("Call 3 people"))).toBe("Checking your campaign again");
    fireEvent.click(button("Call 3 people"));
    expect(onLaunch).not.toHaveBeenCalled();

    rerender(confirm(null, onLaunch));
    fireEvent.click(button("Call 3 people"));
    expect(onLaunch).toHaveBeenCalledTimes(1);
  });
});

describe("a test call waits for the one still ringing", () => {
  const HREFS = {
    creditsHref: "/c/acme/billing?tab=credits",
    verifyHref: "/c/acme/verify-business",
    agentsHref: "/c/acme/agents",
    newAgentHref: "/c/acme/agents/first",
  };
  const trial: TrialPanel = {
    on_trial: true,
    paid_test_calls: false,
    status: "active",
    ends_at: "2026-10-10T17:28:00Z",
    days_remaining: 3,
    free_minutes: 30,
    minutes_used: 4,
    minutes_left: 26,
    calls_today: 2,
    daily_cap: 10,
    max_call_seconds: 180,
    pledge_accepted: true,
    shared_line: false,
    needs_number: false,
    can_call: true,
    blocked_reason: null,
  };
  const call = (over: Partial<TestCall>): TestCall => ({
    id: "call-1",
    agent_id: "agent-out",
    agent_name: "Caller",
    status: "ringing",
    status_source: "call",
    placed_at: new Date(Date.now() - 30_000).toISOString(),
    started_at: null,
    duration_s: null,
    outcome_tag: null,
    business_outcome_label: null,
    headline: null,
    caller_number: null,
    ...over,
  });

  async function renderWith(followed: TestCall) {
    const page = await renderClientPage(<TrialCallCard trial={trial} {...HREFS} />, {
      "/v1/me": OWNER_ME,
      "/v1/agents": [agentRow({ id: "agent-out", name: "Caller", direction: "outbound" })],
      "/v1/trial/calls": [followed],
      [`/v1/trial/calls/${followed.id}`]: followed,
    });
    await screen.findByRole("option", { name: "Caller" });
    fireEvent.change(screen.getByPlaceholderText("9876543210 or +919876543210"), {
      target: { value: "9876543210" },
    });
    return page;
  }

  it("is greyed while the last test call is ringing, and places nothing on a press", async () => {
    const page = await renderWith(call({ status: "ringing" }));
    await waitFor(() => expect(waitingReason(button("Make a test call"))).toBe("Wait for this call to end"));
    await act(async () => {
      fireEvent.click(button("Make a test call"));
    });
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("is ready once that call has ended", async () => {
    await renderWith(call({ status: "completed", duration_s: 40 }));
    await screen.findByText("Ended");
    expect(waitingReason(button("Make a test call"))).toBeNull();
  });

  it("never stays grey for a call the engine left open past the follow window", async () => {
    await renderWith(call({ status: "ringing", placed_at: new Date(Date.now() - 3 * 3_600_000).toISOString() }));
    await screen.findByText("Ringing");
    expect(waitingReason(button("Make a test call"))).toBeNull();
  });

  it("says what is missing before a number is typed", () => {
    expect(callWait({ onCall: false, agentsLoading: false, number: " ", canCall: true })).toBe("Type a number to call");
    expect(callWait({ onCall: false, agentsLoading: true, number: "", canCall: true })).toBe(
      "Waiting for your agents to load",
    );
    expect(callWait({ onCall: false, agentsLoading: false, number: "98765", canCall: true })).toBeNull();
  });
});
