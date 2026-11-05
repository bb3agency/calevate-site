import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { goLiveOffered } from "@/app/c/[slug]/NextSteps";
import { GO_LIVE_STEPS, stageOf } from "@/app/c/[slug]/go-live/GoLiveGuide";
import GoLivePage from "@/app/c/[slug]/go-live/page";
import type { GoLive } from "@/lib/api/goLive";
import { pollMs } from "@/lib/api/goLive";

import { OWNER_ME, agentRow } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/**
 * "GO LIVE" (D-859): after the first payment the owner verifies the business, gets a number
 * and switches an agent on, in plain words with no provider named. Our move of the agents is
 * one quiet line, never a step (e2e audit OB-8), and each waiting step names its real
 * reason (OB-1, OB-2, OB-10).
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

const MOVED: GoLive["move"] = { state: "done", agents: [], total: 0 };

function guide(over: Partial<GoLive> = {}): GoLive {
  return {
    due: true,
    owed_at: "2026-10-23T06:00:00Z",
    finished_at: null,
    dismissed_at: null,
    current: "verify",
    move: {
      state: "moving",
      agents: [
        { agent_id: "a1", name: "Sravani", state: "moved" },
        { agent_id: "a2", name: "Ravi", state: "moving" },
      ],
      total: 2,
    },
    verify: "todo",
    agreements: "done",
    pledge: "todo",
    number: "locked",
    business_review_note: null,
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
  it("has three owner steps and never resumes on the move", () => {
    expect(GO_LIVE_STEPS.map((step) => step.id)).toEqual(["verify", "number", "switch_on"]);
    expect(stageOf("move")).toBe("verify");
    expect(stageOf("verify")).toBe("verify");
    expect(stageOf("done")).toBe("switch_on");
  });

  it("polls only while something is under way", () => {
    expect(pollMs(guide())).toBe(3_000);
    expect(pollMs(guide({ move: MOVED, verify: "in_review" }))).toBe(20_000);
    expect(pollMs(guide({ move: MOVED, verify: "done", number: "setting_up" }))).toBe(20_000);
    expect(pollMs(guide({ move: MOVED, verify: "done" }))).toBe(false);
  });

  it("is offered on the dashboard until finished, even once put aside", () => {
    expect(goLiveOffered(guide({ due: false, dismissed_at: "2026-10-23T07:00:00Z" }))).toBe(true);
    expect(goLiveOffered(guide({ finished_at: "2026-10-23T07:00:00Z" }))).toBe(false);
    expect(goLiveOffered(guide({ owed_at: null }))).toBe(false);
  });
});

describe("the guide", () => {
  it("says our move in one line and names no provider", async () => {
    await renderClientPage(page, routes());
    expect(await screen.findByRole("heading", { name: "Verify your business" })).toBeTruthy();
    expect(screen.getByText("Getting your account ready. Your agents keep working.")).toBeTruthy();
    expect(screen.queryByText("Ravi")).toBeNull();
    expect(document.body.textContent).not.toMatch(/ThinnestAI|workspace|Move your agents/i);
  });

  it("lists the agreements and the pledge beside the business check, each with its button", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/go-live": guide({ move: MOVED, verify: "done", agreements: "todo", pledge: "todo" }) }),
    );
    expect(await screen.findByRole("heading", { name: "Accept the agreements" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Read and accept" }).getAttribute("href")).toBe("/c/acme/agreements");
    expect(screen.getByRole("link", { name: "Accept the pledge" }).getAttribute("href")).toBe(
      "/c/acme/verify-business#step-pledge",
    );
    expect(screen.getByText("Needed before your agent calls out")).toBeTruthy();
  });

  it.each([
    ["add_credit", "Opens once you add credit.", "Add credit", "/c/acme/billing?tab=credits"],
    ["send_details", "Needed once, to buy a number in your name.", "Send my details", "/c/acme/phone-number"],
  ] as const)("a verified business held by %s is told its real reason", async (number, hint, action, to) => {
    await renderClientPage(
      page,
      routes({ "/v1/go-live": guide({ current: "number", move: MOVED, verify: "done", number }) }),
    );
    expect(await screen.findByText(hint)).toBeTruthy();
    expect(screen.queryByText(/once your business is verified/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Verify business first" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: action }));
    await waitFor(() => expect(nav.pushed).toContain(to));
  });

  it("says numbers are not on sale yet without a button", async () => {
    await renderClientPage(
      page,
      routes({ "/v1/go-live": guide({ current: "number", move: MOVED, verify: "done", number: "not_on_sale" }) }),
    );
    expect(await screen.findByRole("heading", { name: "Numbers open soon" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Verify business first" })).toBeNull();
  });

  it("shows a rejected application's review note and a way to fix it", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/go-live": guide({
          current: "number",
          move: MOVED,
          verify: "done",
          number: "needs_attention",
          business_review_note: "The address does not match the GST certificate.",
        }),
      }),
    );
    expect(await screen.findByRole("heading", { name: "Your details need a fix" })).toBeTruthy();
    expect(screen.getByText("The address does not match the GST certificate.")).toBeTruthy();
    expect(screen.queryByText(/moves on by itself/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fix and send again" }));
    await waitFor(() => expect(nav.pushed).toContain("/c/acme/phone-number"));
  });

  it("moves on by itself when the check it waits on is done, as it says it will", async () => {
    let current = guide({ current: "verify", move: MOVED, verify: "in_review" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderClientPage(page, routes({ "/v1/go-live": () => current }), "acme", client);
    expect(await screen.findByRole("heading", { name: "We're checking your details" })).toBeTruthy();

    current = { ...current, current: "number", verify: "done", number: "todo" };
    await act(async () => {
      await client.invalidateQueries();
    });

    expect(await screen.findByRole("heading", { name: "Choose your number" })).toBeTruthy();
  });

  it("points an account with no agent to making one, on the switch-on step", async () => {
    await renderClientPage(
      page,
      routes({
        "/v1/go-live": guide({ current: "switch_on", move: MOVED }),
        "/v1/agents": [],
      }),
    );
    expect(await screen.findByText("No agent to switch on yet")).toBeTruthy();
    const make = screen.getByRole("link", { name: "Make an agent" });
    expect(make.getAttribute("href")).toBe("/c/acme/agents/new");
  });

  it("opens the existing business check from the first step", async () => {
    await renderClientPage(page, routes());
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
