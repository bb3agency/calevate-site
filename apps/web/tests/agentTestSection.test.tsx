import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FIX_ALL_REQUEST, TestSection } from "@/app/c/[slug]/agents/[agentId]/test/TestSection";
import { countsOf, languageOf, trendLine } from "@/app/c/[slug]/agents/[agentId]/test/testCopy";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { TestConversations, TestResult } from "@/lib/api/script";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { renderClientPage } from "./harness";

/**
 * The agent's Test section (D-748), from the founder's screenshot of 11 Oct 2026: a Telugu
 * caller answered in English, a check that a test chat cannot prove, and the fixes (asked of
 * Pip since D-820) as the next step. Each test names what it guards.
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

describe("the practice callers in Training", () => {
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
    expect(screen.getByText(/What to do: We're fixing this/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /About what a test cannot show/i })).toBeTruthy();
    expect(screen.queryByText(/Fix on our side: contact us/)).toBeNull();
    expect(screen.getByText(/Your agreements are waiting/)).toBeTruthy();
    // Needs a fix is listed before Read these yourself.
    const headings = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(headings.findIndex((h) => h?.startsWith("Needs a fix"))).toBeLessThan(
      headings.findIndex((h) => h?.startsWith("Read these yourself")),
    );
  });

  it("asks Pip for the fixes, prefilled and not sent (D-820)", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests({
        results: [STOP, result({ key: "g1", title: "Asks for a discount", verdict: "needs_fix", reason: "It promised a discount.", fix: "script_step" })],
      }),
      "/v1/agents/agent-1/test-cases": SAVED,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Let Pip suggest fixes" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Let Pip suggest a fix" })[0]);
    expect(asked.map((a) => a.prompt)).toEqual([
      FIX_ALL_REQUEST,
      "Suggest a fix for this agent's failed test “Asks for a discount”.",
    ]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the fixes being worked out", async () => {
    await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests({
        improving: true,
        results: [STOP, result({ key: "g1", title: "Asks the price", verdict: "failed", fix: "knowledge" })],
      }),
      "/v1/agents/agent-1/test-cases": SAVED,
    });
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

  it("routes each failure to who can fix it, and lets the owner mark a test wrong (D-823)", async () => {
    const PERSON = result({
      key: "probe_person",
      title: "Asks to speak to a person",
      probe: "person",
      verdict: "unjudged",
      reason: "Hand-over to a person is switched off for this agent.",
      fix: "settings",
      owner: "setting",
      setting: { area: "handover", reason: "Hand-over to a person is switched off for this agent." },
    });
    const PRICE = result({ key: "g1", title: "Asks the price", verdict: "failed", reason: "It made up a price.", fix: "knowledge", owner: "knowledge" });
    const { calls } = await renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
      "/v1/me": ME,
      "/v1/agents/agent-1/script/tests": tests({ results: [STOP, PRICE, PERSON] }),
      "POST /v1/agents/agent-1/script/tests/run-2/results/g1/wrong": tests({
        results: [STOP, { ...PRICE, owner: "test", marked_wrong: true }, PERSON],
      }),
      "/v1/agents/agent-1/test-cases": SAVED,
    });
    await screen.findByText("Asks the price");
    // Only the knowledge failure is Pip's to fix; ours says so, without "contact us".
    expect(screen.getByText(/1 test can be fixed in the script or your facts/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Let Pip suggest a fix" })).toHaveLength(1);
    expect(screen.queryByText(/contact us/i)).toBeNull();
    // A setting's result links to the setting.
    expect(screen.getByRole("link", { name: "Open call handling" }).getAttribute("href")).toContain("section=settings#call-handling");
    fireEvent.click(screen.getAllByRole("button", { name: "This test is wrong" })[1]);
    await screen.findByText("Marked wrong (1)");
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/results/g1/wrong"))).toBe(true);
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
