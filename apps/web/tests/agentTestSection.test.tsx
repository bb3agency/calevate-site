import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TestSection } from "@/app/c/[slug]/agents/[agentId]/test/TestSection";
import { countsOf, languageOf, trendLine } from "@/app/c/[slug]/agents/[agentId]/test/testCopy";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { TestConversations, TestResult } from "@/lib/api/script";

import { renderClientPage } from "./harness";

/**
 * The agent's Test section (D-748), from the founder's screenshot of 11 Oct 2026: a Telugu
 * caller answered in English, a check that a test chat cannot prove, and "Improve my agent"
 * as the next step. Each test names what it guards.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "agents:write", "org:manage", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const AGENT: Pick<Agent, "id"> = { id: "agent-1" };

function result(over: Partial<TestResult>): TestResult {
  return {
    key: "k",
    title: "A test",
    category: "business",
    probe: null,
    source: "generated",
    turns: [],
    expect: "",
    verdict: "passed",
    reason: "",
    fix: null,
    step_id: null,
    formal_words: [],
    before: null,
    limit: null,
    ...over,
  };
}

const STOP = result({
  key: "probe_stop_calling",
  title: "Asks not to be called again",
  category: "compliance",
  probe: "stop_calling",
  source: "standard",
  turns: [
    {
      said: "నాకు మళ్ళీ call చేయకండి, నా number తీసేయండి.",
      reply: "The caller's number has been added to the do-not-call list.",
      actions: ["do_not_call"],
    },
  ],
  verdict: "failed",
  reason: "The caller spoke Telugu and it answered in English.",
  fix: "platform",
  limit: "A test chat has no phone number, so it cannot show a number being removed.",
});

function tests(over: Partial<TestConversations["latest"] & object> = {}, waiting: string | null = null): TestConversations {
  return {
    available: true,
    unavailable_reason: null,
    cost_note: "Not charged.",
    waiting_update: waiting,
    latest: {
      id: "run-2",
      status: "done",
      prompt_version: 3,
      is_current: true,
      round: 1,
      retest_of: null,
      auto_improve: false,
      score: { passed: 1, judged: 2, total: 3 },
      results: [
        STOP,
        result({ key: "r1", title: "Asks what you sell", verdict: "unjudged", reason: "Not checked." }),
        result({ key: "probe_ai", title: "Asks if it is a person", probe: "ai", reason: "It answered truthfully." }),
      ],
      improvement: null,
      note: null,
      improving: false,
      improve_note: null,
      created_at: "2026-10-11T10:00:00Z",
      completed_at: "2026-10-11T10:01:00Z",
      ...over,
    },
    history: [{ id: "run-1", created_at: "2026-10-10T18:21:00Z", prompt_version: 3, round: 1, score: { passed: 3, judged: 7, total: 7 } }],
  };
}

const SAVED = { cases: [], available: true, unavailable_reason: null, live_version: 3, cost_note: "" };

describe("the Test section", () => {
  it("states the run, the trend, each language and what to do, failures first", async () => {
    await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests({}, "Your agreements are waiting, so the improvements cannot reach this one yet."),
      "/v1/agents/agent-1/test-cases": SAVED,
    });
    await screen.findByText("Asks not to be called again");
    // The summary counts a needs-fix and a failure together, and says which way it moved.
    expect(screen.getByText("Need a fix").nextSibling?.textContent).toBe("1");
    expect(screen.getByText(/Better than last time \(3 of 7/)).toBeTruthy();
    // The caller's language and the agent's are shown, so the mismatch is visible.
    expect(screen.getByText("· Telugu")).toBeTruthy();
    expect(screen.getAllByText("· English").length).toBeGreaterThan(0);
    expect(screen.getByText("Used its step that removes a number")).toBeTruthy();
    // One plain line, then what to do; what a test cannot show is behind the ⓘ.
    expect(screen.getByText("The caller spoke Telugu and it answered in English.")).toBeTruthy();
    expect(screen.getByText(/What to do: Ours to fix, not yours/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /About what a test cannot show/i })).toBeTruthy();
    expect(screen.queryByText(/Fix on our side: contact us/)).toBeNull();
    expect(screen.getByText(/Your agreements are waiting/)).toBeTruthy();
    // Needs a fix is listed before Read these yourself.
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings.findIndex((h) => h?.startsWith("Needs a fix"))).toBeLessThan(
      headings.findIndex((h) => h?.startsWith("Read these yourself")),
    );
  });

  it("queues Improve my agent and shows it working, with one filled button", async () => {
    const { calls } = await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests(),
      "/v1/agents/agent-1/test-cases": SAVED,
      "POST /v1/agents/agent-1/script/tests/run-2/improve": tests({ improving: true }),
    });
    const improve = await screen.findByRole("button", { name: "Improve my agent" });
    // "Test again" steps back once a test fails, so fixing is the one filled button.
    expect(screen.getByRole("button", { name: "Test again" }).className).not.toBe(improve.className);
    fireEvent.click(improve);
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/agents/agent-1/script/tests/run-2/improve")).toBe(true),
    );
    expect(await screen.findByText(/Working out fixes for 1 test/)).toBeTruthy();
  });

  it("says why suggestions could not be made", async () => {
    await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests({
        improve_note: "Suggestions could not be worked out, because this month's AI help allowance is used up.",
      }),
      "/v1/agents/agent-1/test-cases": SAVED,
    });
    expect(await screen.findByText(/allowance is used up/)).toBeTruthy();
  });
});

describe("test copy", () => {
  it("names a line's language from its letters", () => {
    expect(languageOf("ఈ call record అవుతుందా?")).toBe("Telugu");
    expect(languageOf("क्या ये call record हो रही है?")).toBe("Hindi");
    expect(languageOf("Is this call recorded?")).toBe("English");
    expect(languageOf("…")).toBeNull();
  });

  it("compares runs as a share of what was checked", () => {
    const run = { id: "b", score: { passed: 2, judged: 4, total: 6 } };
    const prior = [{ id: "a", created_at: "2026-10-10T18:21:00Z", prompt_version: 1, round: 1, score: { passed: 3, judged: 6, total: 6 } }];
    expect(trendLine(run, prior)).toMatch(/^Same as last time/);
    expect(trendLine(run, [])).toBeNull();
    expect(countsOf([{ verdict: "needs_fix" }, { verdict: "failed" }, { verdict: "unjudged" }])).toEqual({
      passed: 0,
      failing: 2,
      unchecked: 1,
      total: 3,
    });
  });
});
