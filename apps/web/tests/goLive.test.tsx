import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { goLiveOffered } from "@/app/c/[slug]/GoLiveInvite";
import { TrialCallCard } from "@/app/c/[slug]/TrialCallPanel";
import { moveChecklist, stageOf } from "@/app/c/[slug]/go-live/GoLiveGuide";
import GoLivePage from "@/app/c/[slug]/go-live/page";
import type { GoLive } from "@/lib/api/goLive";
import { pollMs } from "@/lib/api/goLive";
import type { TrialPanel } from "@/lib/api/trialCalls";

import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/**
 * "GO LIVE" (D-859): after the first payment the owner sees the agents' real move, then the
 * business check, the number and the switch, in plain words with no provider named; the
 * dashboard's test-call card has no trial copy once the account has paid.
 */

const nav = vi.hoisted(() => ({ pushed: [] as string[] }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/c/acme/go-live",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({
    push: (path: string) => nav.pushed.push(path),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  nav.pushed = [];
});

const page = <GoLivePage params={Promise.resolve({ slug: "acme" })} />;

function guide(over: Partial<GoLive> = {}): GoLive {
  return {
    due: true,
    owed_at: "2026-10-23T06:00:00Z",
    finished_at: null,
    dismissed_at: null,
    current: "move",
    move: {
      state: "moving",
      agents: [
        { agent_id: "a1", name: "Sravani", state: "moved" },
        { agent_id: "a2", name: "Ravi", state: "moving" },
      ],
      total: 2,
    },
    verify: "todo",
    number: "locked",
    numbers: 0,
    switch_on: "todo",
    live_agents: 0,
    ...over,
  };
}

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": OWNER_ME, "/v1/go-live": guide(), "/v1/agents": [], ...over };
}

describe("what the guide derives", () => {
  it("ticks moved agents first and holds on one we are finishing", () => {
    const list = moveChecklist([
      { agent_id: "a", name: "Held", state: "finishing" },
      { agent_id: "b", name: "Moved", state: "moved" },
    ]);
    expect(list.steps.map((step) => step.label)).toEqual(["Moved", "Held"]);
    expect(list.current).toBe(1);
    expect(list.held).toBe(true);
    expect(list.steps[1].meta).toBe("We're finishing this for you");
  });

  it("resumes where the server says and polls only while something is under way", () => {
    expect(stageOf("verify")).toBe("verify");
    expect(stageOf("done")).toBe("switch_on");
    expect(pollMs(guide())).toBe(3_000);
    expect(pollMs(guide({ move: { state: "done", agents: [], total: 0 }, verify: "in_review" }))).toBe(20_000);
    expect(pollMs(guide({ move: { state: "done", agents: [], total: 0 }, verify: "done" }))).toBe(false);
  });

  it("is offered on the dashboard until finished, even once put aside", () => {
    expect(goLiveOffered(guide({ due: false, dismissed_at: "2026-10-23T07:00:00Z" }))).toBe(true);
    expect(goLiveOffered(guide({ finished_at: "2026-10-23T07:00:00Z" }))).toBe(false);
    expect(goLiveOffered(guide({ owed_at: null }))).toBe(false);
  });
});

describe("the guide", () => {
  it("shows the real move, agent by agent, and names no provider", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "Moving your agents to your own account…" })).toBeTruthy();
    expect(screen.getByText("Sravani")).toBeTruthy();
    expect(screen.getByText("Ravi")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/ThinnestAI|workspace/i);
  });

  it("says we are finishing it when an agent is held", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/go-live": guide({
          move: { state: "finishing", agents: [{ agent_id: "a1", name: "Sravani", state: "finishing" }], total: 1 },
        }),
      }),
    );
    expect(await screen.findByRole("heading", { name: "We're finishing this for you" })).toBeTruthy();
  });

  it("goes on to the business check, which opens the existing flow", async () => {
    await renderClientPage(page, routes());
    fireEvent.click(await screen.findByRole("button", { name: /Verify your business/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Verify my business" }));
    await waitFor(() => expect(nav.pushed).toContain("/c/acme/verify-business"));
  });

  it("switches an agent on with its own switch and shows the server's refusal", async () => {
    const { calls } = await renderClientPage(
      page,
      routes({
        "/v1/go-live": guide({
          current: "switch_on",
          move: { state: "done", agents: [], total: 0 },
          verify: "done",
          number: "done",
          numbers: 1,
        }),
        "/v1/agents": [agentRow({ id: "a1", name: "Sravani", status: "paused", published: true })],
        "POST /v1/agents/a1/activate": problem(409, {
          type: "about:blank",
          title: "Not yet",
          status: 409,
          code: "agent_needs_number",
          detail: "Attach your number to this agent first.",
        }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Switch on" }));
    expect(await screen.findByText(/Attach your number to this agent first/)).toBeTruthy();
    expect(calls.some((call) => call.method === "POST" && call.path === "/v1/agents/a1/activate")).toBe(true);
  });
});

describe("the dashboard's test-call card after payment", () => {
  const paid: TrialPanel = {
    on_trial: false,
    paid_test_calls: true,
    status: null,
    ends_at: null,
    days_remaining: null,
    free_minutes: null,
    minutes_used: 0,
    minutes_left: null,
    calls_today: 1,
    daily_cap: 10,
    max_call_seconds: 180,
    pledge_accepted: true,
    can_call: false,
    blocked_reason: "Test calls now ring from your own number. Get your number and switch this agent on, then call it here.",
  };

  it("has no trial words and no add-credit prompt", async () => {
    await renderClientPage(
      <TrialCallCard
        trial={paid}
        creditsHref="/c/acme/billing"
        verifyHref="/c/acme/verify-business"
        agentsHref="/c/acme/agents"
        newAgentHref="/c/acme/agents/first"
      />,
      routes(),
    );
    expect(await screen.findByText("Test calls")).toBeTruthy();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/free trial|Days left|Free minutes|Add credit/i);
    expect(text).toMatch(/billed like any call/);
  });
});
