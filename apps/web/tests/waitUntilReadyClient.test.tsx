import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PipAsk } from "@/app/c/[slug]/agents/[agentId]/script/PipAsk";
import { ScriptToolbar, publishBlock } from "@/app/c/[slug]/agents/[agentId]/script/ScriptToolbar";
import type { SaveState } from "@/app/c/[slug]/agents/[agentId]/script/scriptDraft";
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

describe("Put it live waits for the draft to save", () => {
  const toolbar = (save: SaveState, onPublish = vi.fn()) => (
    <ScriptToolbar
      save={save}
      room={null}
      unpublished
      canWrite
      writeReason={null}
      publishing={false}
      live={{ text: "Changes not live yet", tone: "warn" }}
      menu={[]}
      onPublish={onPublish}
    />
  );

  it("is greyed with its reason while a save is on its way, and ignores a press", () => {
    const onPublish = vi.fn();
    render(toolbar({ kind: "saving" }, onPublish));
    expect(waitingReason(button("Put it live"))).toBe("Waiting for your draft to save");
    fireEvent.click(button("Put it live"));
    expect(onPublish).not.toHaveBeenCalled();
  });

  it("comes back by itself once the draft is saved", () => {
    const onPublish = vi.fn();
    const { rerender } = render(toolbar({ kind: "saving" }, onPublish));
    rerender(toolbar({ kind: "clean", savedAt: "2026-11-01T05:00:00Z" }, onPublish));
    expect(waitingReason(button("Put it live"))).toBeNull();
    fireEvent.click(button("Put it live"));
    expect(onPublish).toHaveBeenCalledTimes(1);
  });

  it("is released after a failed save, whose own notice offers Try again", () => {
    expect(publishBlock({ save: { kind: "failed" }, tooLong: false })).toBeNull();
    expect(publishBlock({ save: { kind: "conflict" }, tooLong: false })).toBe("Choose which draft to keep first.");
  });
});

describe("Launch waits for the launch check it relies on", () => {
  const confirm = (waiting: string | null, onLaunch = vi.fn()) => (
    <LaunchConfirm
      contacts={3}
      concurrency={1}
      callingHours={null}
      numberE164={null}
      canWrite
      writeReason={undefined}
      status="idle"
      onLaunch={onLaunch}
      waiting={waiting}
    />
  );

  it("does not open the confirmation while the check is re-running", () => {
    const { rerender } = render(confirm("Checking your campaign again"));
    expect(waitingReason(button("Launch campaign"))).toBe("Checking your campaign again");
    fireEvent.click(button("Launch campaign"));
    expect(screen.queryByText(/This starts calling/)).toBeNull();

    rerender(confirm(null));
    fireEvent.click(button("Launch campaign"));
    expect(screen.getByText(/This starts calling/)).toBeTruthy();
  });

  it("holds an armed Call button while the check re-runs, then lets it dial", () => {
    const onLaunch = vi.fn();
    const { rerender } = render(confirm(null, onLaunch));
    fireEvent.click(button("Launch campaign"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "3" } });
    rerender(confirm("Checking your campaign again", onLaunch));
    fireEvent.click(button("Call 3 people"));
    expect(onLaunch).not.toHaveBeenCalled();
    expect(waitingReason(button("Call 3 people"))).toBe("Checking your campaign again");

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

describe("asking Pip waits for the suggestion being written", () => {
  it("holds the ask, the ideas and the whole-script ask while Pip is writing, and lifts after", async () => {
    function Written() {
      const [drafting, setDrafting] = useState(true);
      return (
        <>
          <PipAsk drafting={drafting} />
          <button type="button" onClick={() => setDrafting(false)}>
            Suggestion written
          </button>
        </>
      );
    }
    await renderClientPage(<Written />, { "/v1/me": OWNER_ME });
    fireEvent.change(await screen.findByLabelText("What should change?"), { target: { value: "Shorter opening" } });
    await waitFor(() => expect(waitingReason(button(/do it$/))).toMatch(/to finish this suggestion$/));
    expect(button(/^Let Pip draft the whole script:/).disabled).toBe(true);

    fireEvent.click(button("Suggestion written"));
    await waitFor(() => expect(waitingReason(button(/do it$/))).toBeNull());
    expect(button(/do it$/).disabled).toBe(false);
  });
});
