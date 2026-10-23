import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TrialCallCard } from "@/app/c/[slug]/TrialCallPanel";
import { TrialChipView, TrialStrip, trialView } from "@/app/c/[slug]/TrialBanner";
import { TRIAL_LOCK_COPY } from "@/app/c/[slug]/TrialLockNotice";
import type { TrialPanel } from "@/lib/api/trialCalls";

import { OWNER_ME, activeTrialBlock, agentRow, prepaidWallet } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * A free trial is test calls only, until the client adds credit (D-697): the strip on every
 * screen says so and links to the one step that ends it, and the dashboard's panel places a
 * test call from an agent to a number the client types.
 */

afterEach(cleanup);

const CREDITS = "/c/acme/billing?tab=credits";
const HREFS = {
  creditsHref: CREDITS,
  verifyHref: "/c/acme/verify-business",
  agentsHref: "/c/acme/agents",
  newAgentHref: "/c/acme/agents/first",
};
const ENDS = new Date("2026-10-10T17:28:00Z");

function panel(over: Partial<TrialPanel> = {}): TrialPanel {
  return {
    on_trial: true,
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
    ...over,
  };
}

describe("the trial in the shell on a test-calls-only trial", () => {
  it("the chip's panel says what is left and that everything else opens with credit", () => {
    const wallet = prepaidWallet({
      balance_inr: "0.00",
      trial: activeTrialBlock({ test_calls_only: true, free_minutes: 30, minutes_left: 26 }),
    });
    const view = trialView(wallet);
    if (view === null) throw new Error("expected a trial");
    render(
      <TrialChipView view={view} creditsHref={CREDITS} open now={new Date(ENDS.getTime() - 70 * 3_600_000)} />,
    );
    const panel = screen.getByRole("dialog", { name: "Your free trial" });
    const text = panel.textContent ?? "";
    expect(text).toContain("10 Oct, 10:58 pm IST");
    expect(text).toContain("26 of 30");
    expect(text).toContain("Answering calls, campaigns, your own number and business verification open once you add credit.");
    expect(text).not.toContain("Calls are on us until then");
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe(CREDITS);
  });

  it("says the trial has ended once it has, and still offers the way on", () => {
    window.localStorage.clear();
    const wallet = prepaidWallet({
      trial: activeTrialBlock({
        active: false,
        status: "expired",
        days_remaining: null,
        test_calls_only: true,
      }),
    });
    const { container } = render(<TrialStrip wallet={wallet} slug="acme" creditsHref={CREDITS} />);
    expect(container.textContent).toContain("Your free trial has ended.");
    expect(screen.getByRole("link", { name: "Add credit" })).toBeTruthy();
  });

  it("names no internals in the locked-screen copy", () => {
    for (const copy of Object.values(TRIAL_LOCK_COPY)) {
      expect(copy.body).not.toMatch(/tenant|workspace|thinnest|D-\d/i);
    }
  });
});

describe("the test-call panel", () => {
  it("shows days, minutes and today's calls, and places a test call with a held key", async () => {
    const agent = agentRow({ id: "agent-out", name: "Caller", direction: "outbound" });
    const page = await renderClientPage(
      <TrialCallCard trial={panel()} {...HREFS} />,
      {
        "/v1/agents": [agent],
        "/v1/trial/calls": { status: "queued", call_handle: "out_1", blocked_reason: null, blocked_rule: null },
        // The test call, read back once it lands (REDESIGN-2): this agent's newest call.
        "/v1/me": OWNER_ME,
        "/v1/calls?agent_id=agent-out&limit=1": [
          { id: "call-t1", agent_id: "agent-out", direction: "outbound", status: "completed", started_at: new Date().toISOString() },
        ],
        "/v1/calls/call-t1": {
          id: "call-t1",
          agent_id: "agent-out",
          agent_name: "Caller",
          direction: "outbound",
          status: "completed",
          caller_e164: "+919876543210",
          started_at: new Date().toISOString(),
          duration_s: 40,
          outcome_tag: "resolved",
          sentiment: "neutral",
          summary: "A test call.",
          lead_id: null,
          transcript: [{ idx: 0, speaker: "agent", text: "Hello, this is your test call.", lang: "en", start_ms: 0, redacted: true }],
          extraction: {},
          extraction_valid: true,
          has_recording: false,
          disclosure_played: true,
          moments: [],
        },
      },
    );
    const text = page.container.textContent ?? "";
    expect(text).toContain("26 of 30");
    expect(text).toContain("2 of 10");
    expect(text).toContain("ends after 3 minutes");
    await screen.findByRole("option", { name: "Caller" });
    fireEvent.change(screen.getByPlaceholderText("9876543210 or +919876543210"), {
      target: { value: "9876543210" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Make a test call" }));
    });
    const post = page.calls.find((call) => call.method === "POST" && call.path === "/v1/trial/calls");
    expect(JSON.parse(post!.body!)).toEqual({ agent_id: "agent-out", number: "9876543210" });
    expect(post?.headers["Idempotency-Key"]).toBeTruthy();
    expect(await screen.findByText("Calling now. The call appears under Calls once it ends.")).toBeTruthy();
    // Then what was said, in place, redacted by default with its notice above.
    expect(await screen.findByText("Hello, this is your test call.")).toBeTruthy();
    expect(screen.getByText(/are hidden in/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open this call" }).getAttribute("href")).toBe("/c/acme/calls/call-t1");
  });

  it("asks for the promise first, and does not offer a call the server would refuse", async () => {
    await renderClientPage(
      <TrialCallCard
        trial={panel({ pledge_accepted: false, can_call: false, blocked_reason: "Accept the promise." })}
        {...HREFS}
      />,
      { "/v1/agents": [agentRow({ direction: "outbound" })] },
    );
    expect(screen.getByText("One step before your first test call")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Make a test call" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Add credit to go live" }).getAttribute("href")).toBe(CREDITS);
  });
});

describe("the test-call panel's agents (D-853)", () => {
  it("offers every agent, a draft marked as one that gets ready when called", async () => {
    await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [
        agentRow({ id: "front", name: "Front desk", direction: "inbound", status: "paused", published: true }),
        agentRow({ id: "off", name: "Switched off", direction: "outbound", status: "paused", published: true }),
        agentRow({ id: "draft", name: "Still a draft", direction: "outbound", status: "draft", published: false }),
      ],
    });
    const select = (await screen.findByRole("combobox")) as HTMLSelectElement;
    const names = Array.from(select.options).map((option) => option.textContent);
    expect(names).toEqual(["Front desk", "Switched off", "Still a draft (gets ready when you call)"]);
  });

  it("links an account with no agents to its first one", async () => {
    await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, { "/v1/agents": [] });
    const link = await screen.findByRole("link", { name: "Build your first agent" });
    expect(link.getAttribute("href")).toBe("/c/acme/agents/first");
  });

  it("gets a draft ready, then calls from it", async () => {
    const page = await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [agentRow({ id: "draft", name: "Still a draft", status: "draft", published: false })],
      "/v1/agents/draft/prepare": { status: "paused" },
      "/v1/trial/calls": { status: "queued", call_handle: "out_2", blocked_reason: null, blocked_rule: null },
      "/v1/calls?agent_id=draft&limit=1": [],
    });
    await screen.findByRole("option", { name: "Still a draft (gets ready when you call)" });
    fireEvent.change(screen.getByPlaceholderText("9876543210 or +919876543210"), {
      target: { value: "9876543210" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Make a test call" }));
    });
    await screen.findByText("Calling now. The call appears under Calls once it ends.");
    const posts = page.calls.filter((call) => call.method === "POST").map((call) => call.path);
    expect(posts.indexOf("/v1/agents/draft/prepare")).toBeGreaterThanOrEqual(0);
    expect(posts.indexOf("/v1/agents/draft/prepare")).toBeLessThan(posts.indexOf("/v1/trial/calls"));
  });
});
