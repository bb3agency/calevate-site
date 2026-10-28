import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TrialCallCard } from "@/app/c/[slug]/TrialCallPanel";
import { TrialChipView, TrialStrip, trialView } from "@/app/c/[slug]/TrialBanner";
import { TRIAL_LOCK_COPY } from "@/app/c/[slug]/TrialLockNotice";
import {
  TEST_CALL_POLL_MS,
  testCallKey,
  testCallPollMs,
  type TestCall,
  type TrialCallResult,
  type TrialPanel,
} from "@/lib/api/trialCalls";

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
    ...over,
  };
}

const TRIAL_NUMBER = "+918045678901";

/** What `POST /v1/trial/calls` answers for a placed call (D-885: our id and the number). */
function placed(callId: string): TrialCallResult {
  return {
    status: "queued",
    call_handle: `out_${callId}`,
    blocked_reason: null,
    blocked_rule: null,
    call_id: callId,
    caller_number: TRIAL_NUMBER,
  };
}

function testCall(over: Partial<TestCall> = {}): TestCall {
  return {
    id: "call-1",
    agent_id: "agent-out",
    agent_name: "Caller",
    status: "queued",
    status_source: "call",
    placed_at: new Date(Date.now() - 30_000).toISOString(),
    started_at: null,
    duration_s: null,
    outcome_tag: null,
    business_outcome_label: null,
    headline: null,
    caller_number: null,
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
        "POST /v1/trial/calls": placed("call-t1"),
        "/v1/me": OWNER_ME,
        // The call, followed by the id the placement answered with (D-885).
        "/v1/trial/calls/call-t1": testCall({
          id: "call-t1",
          status: "completed",
          duration_s: 40,
          outcome_tag: "answered",
          headline: "Asked about opening hours.",
          caller_number: TRIAL_NUMBER,
        }),
      },
    );
    const text = page.container.textContent ?? "";
    expect(text).toContain("26 of 30");
    expect(text).toContain("2 of 10");
    expect(text).toContain("up to 3 minutes each");
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
    const followed = await screen.findByRole("region", { name: "This test call" });
    const said = followed.textContent ?? "";
    expect(said).toContain("Ended");
    expect(said).toContain("It rang from +91 80456 78901.");
    expect(said).toContain("0:40");
    expect(said).toContain("Answered");
    expect(said).toContain("Asked about opening hours.");
    expect(screen.getByRole("link", { name: "Open this call" }).getAttribute("href")).toBe("/c/acme/calls/call-t1");
    expect(page.calls.some((call) => call.path.startsWith("/v1/calls?"))).toBe(false);
  });

  it("sends the own-number tick, which lets a test call ring outside 9am to 9pm (D-866)", async () => {
    const agent = agentRow({ id: "agent-out", name: "Caller", direction: "outbound" });
    const page = await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [agent],
      "POST /v1/trial/calls": placed("call-t3"),
      "/v1/me": OWNER_ME,
      "/v1/trial/calls/call-t3": testCall({ id: "call-t3" }),
    });
    await screen.findByRole("option", { name: "Caller" });
    fireEvent.change(screen.getByPlaceholderText("9876543210 or +919876543210"), {
      target: { value: "9876543210" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /This is my own number/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Make a test call" }));
    });
    const post = page.calls.find((call) => call.method === "POST" && call.path === "/v1/trial/calls");
    expect(JSON.parse(post!.body!)).toEqual({ agent_id: "agent-out", number: "9876543210", number_is_mine: true });
  });

  it("asks for the promise first, and does not offer a call the server would refuse", async () => {
    await renderClientPage(
      <TrialCallCard
        trial={panel({ pledge_accepted: false, can_call: false, blocked_reason: "Accept the promise." })}
        {...HREFS}
      />,
      { "/v1/agents": [agentRow({ direction: "outbound" })] },
    );
    expect(screen.getByText("Accept the no-cold-calls promise")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Make a test call" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Add credit" }).getAttribute("href")).toBe(CREDITS);
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
      "POST /v1/trial/calls": placed("call-t2"),
      "/v1/trial/calls/call-t2": testCall({ id: "call-t2", agent_id: "draft" }),
    });
    await screen.findByRole("option", { name: "Still a draft (gets ready when you call)" });
    fireEvent.change(screen.getByPlaceholderText("9876543210 or +919876543210"), {
      target: { value: "9876543210" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Make a test call" }));
    });
    await screen.findByRole("region", { name: "This test call" });
    const posts = page.calls.filter((call) => call.method === "POST").map((call) => call.path);
    expect(posts.indexOf("/v1/agents/draft/prepare")).toBeGreaterThanOrEqual(0);
    expect(posts.indexOf("/v1/agents/draft/prepare")).toBeLessThan(posts.indexOf("/v1/trial/calls"));
  });
});

describe("following a test call on the card (D-885)", () => {
  it("walks one call from calling to ringing to connected to ended, read by its id", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const started = new Date(Date.now() - 65_000).toISOString();
    const steps: TestCall[] = [
      testCall({ id: "call-s", status: "queued" }),
      testCall({ id: "call-s", status: "ringing", status_source: "engine" }),
      testCall({ id: "call-s", status: "in_progress", status_source: "engine", started_at: started }),
      testCall({ id: "call-s", status: "completed", started_at: started, duration_s: 72, outcome_tag: "answered" }),
    ];
    let step = 0;
    await renderClientPage(
      <TrialCallCard trial={panel()} {...HREFS} />,
      {
        "/v1/agents": [agentRow({ id: "agent-out", name: "Caller", direction: "outbound" })],
        "/v1/me": OWNER_ME,
        "GET /v1/trial/calls": [testCall({ id: "call-s" })],
        "/v1/trial/calls/call-s": () => steps[Math.min(step, steps.length - 1)],
      },
      "acme",
      client,
    );
    const region = await screen.findByRole("region", { name: "Your last test call" });
    const says = async (words: string) => {
      await screen.findByText(words, { exact: false });
      return region.textContent ?? "";
    };
    const next = async () => {
      step += 1;
      await act(async () => {
        await client.refetchQueries({ queryKey: testCallKey("acme", "call-s") });
      });
    };
    expect(await says("Placing the call.")).toContain("Calling");

    await next();
    expect(await says("Your phone is ringing.")).toContain("Ringing");

    await next();
    expect(await says("You're talking to your agent.")).toContain("Connected");
    expect(screen.getByRole("timer").textContent).toMatch(/^1:0\d$/);
    expect(screen.queryByRole("link", { name: "Open this call" })).toBeNull();

    await next();
    const ended = await says("The call has ended.");
    expect(ended).toContain("1:12");
    expect(ended).toContain("Answered");
    expect(screen.getByRole("link", { name: "Open this call" }).getAttribute("href")).toBe("/c/acme/calls/call-s");
  });

  it("polls a running call often and stops once it has ended", () => {
    const now = Date.now();
    expect(testCallPollMs(testCall({ status: "queued" }), now)).toBe(TEST_CALL_POLL_MS);
    expect(testCallPollMs(testCall({ status: "in_progress" }), now)).toBe(TEST_CALL_POLL_MS);
    for (const status of ["no_answer", "busy", "voicemail", "failed"] as const) {
      expect(testCallPollMs(testCall({ status }), now)).toBe(false);
    }
    expect(testCallPollMs(testCall({ status: "completed", headline: "Done." }), now)).toBe(false);
    // An ended call still waiting for its summary is read on the live stream's slow poll.
    expect(testCallPollMs(testCall({ status: "completed" }), now)).toBe(20_000);
    // A call that still reads as live long after it was placed is not asked about forever.
    const stale = testCall({ status: "queued", placed_at: new Date(now - 60 * 60_000).toISOString() });
    expect(testCallPollMs(stale, now)).toBe(false);
  });

  it.each([
    ["no_answer", "Not answered", "Nobody picked up."],
    ["busy", "Line busy", "Try again in a minute."],
    ["voicemail", "Went to voicemail", "Call again and pick up."],
    ["failed", "Did not go through", "Check the number and try again."],
  ] as const)("says a call that ended %s in plain words with what to do", async (status, label, step) => {
    const ended = testCall({ id: "call-x", status, duration_s: 0, caller_number: TRIAL_NUMBER });
    await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [agentRow({ id: "agent-out", name: "Caller", direction: "outbound" })],
      "GET /v1/trial/calls": [ended],
      "/v1/trial/calls/call-x": ended,
    });
    const region = await screen.findByRole("region", { name: "Your last test call" });
    await screen.findByText(label);
    expect(region.textContent).toContain(step);
    expect(region.textContent).toContain("It rang from +91 80456 78901.");
  });

  it("shows today's test calls again after a reload, the newest followed and the rest listed", async () => {
    const newest = testCall({ id: "call-3", status: "completed", duration_s: 95, headline: "Booked a visit." });
    await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [agentRow({ id: "agent-out", name: "Caller", direction: "outbound" })],
      "GET /v1/trial/calls": [
        newest,
        testCall({ id: "call-2", status: "no_answer", duration_s: 0 }),
        testCall({ id: "call-1", status: "completed", duration_s: 30, outcome_tag: "answered" }),
      ],
      "/v1/trial/calls/call-3": newest,
    });
    const last = await screen.findByRole("region", { name: "Your last test call" });
    expect(await screen.findByText("Booked a visit.")).toBeTruthy();
    expect(last.textContent).toContain("1:35");
    const earlier = screen.getByRole("region", { name: "Earlier test calls today" });
    const rows = earlier.querySelectorAll("li");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("No answer");
    expect(rows[1].textContent).toContain("Answered");
    const links = Array.from(earlier.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/c/acme/calls/call-2", "/c/acme/calls/call-1"]);
  });

  it("says nothing about earlier calls on a day with none", async () => {
    await renderClientPage(<TrialCallCard trial={panel()} {...HREFS} />, {
      "/v1/agents": [agentRow({ id: "agent-out", name: "Caller", direction: "outbound" })],
    });
    await screen.findByRole("option", { name: "Caller" });
    expect(screen.queryByRole("region", { name: "Your last test call" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Earlier test calls today" })).toBeNull();
  });
});
