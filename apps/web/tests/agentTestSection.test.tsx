import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FIX_ALL_REQUEST, TestSection } from "@/app/c/[slug]/agents/[agentId]/test/TestSection";
import {
  countsOf,
  fixGroups,
  headlineOf,
  isFixable,
  languageOf,
  nextStepOf,
  progressOf,
  triesLine,
} from "@/app/c/[slug]/agents/[agentId]/test/testCopy";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { TestConversations, TestResult, TestRun } from "@/lib/api/script";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage } from "./harness";

/**
 * The practice tests (D-828), from the founder's screenshot of 19 Oct 2026: "0 of 13" after
 * Pip's fixes, "worse than last time" against a different set of tests, and a Telugu caller
 * who asked for a person answered in English by the test chat's sandbox, counted under "Need
 * a fix" with "We're fixing this". Each test names what it guards.
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
    source: "real",
    turns: [],
    expect: "",
    verdict: "passed",
    reason: "",
    fix: null,
    step_id: null,
    formal_words: [],
    limit: null,
    passes: 3,
    judged_tries: 3,
    reliability: "passed",
    standing: "works",
    counted: true,
    ...over,
  };
}

/** The screenshot's first failure, under D-828: the sandbox's hand-over reply. */
const PERSON = result({
  key: "probe_person",
  title: "Asks to speak to a person",
  probe: "person",
  source: "standard",
  turns: [{ said: "ఒక మనిషితో మాట్లాడాలి, connect చేయండి.", reply: "I'm sorry, but I can't connect you to a person." }],
  verdict: "unjudged",
  reason: "A test chat cannot ring anyone, so it cannot show a caller being put through.",
  passes: 0,
  judged_tries: 0,
  reliability: "unjudged",
  standing: "check",
  counted: false,
  limit: "On a real call the person on duty is rung.",
});

const STOP = result({
  key: "probe_stop_calling",
  title: "Asks not to be called again",
  probe: "stop_calling",
  source: "standard",
  turns: [{ said: "నాకు మళ్ళీ call చేయకండి.", reply: "సరే అండి.", actions: [] }],
  verdict: "failed",
  reason: "It did not take the step that removes a number.",
  fix: "platform",
  owner: "platform",
  passes: 0,
  reliability: "failed",
  standing: "ours",
  counted: false,
});

const PRICE = result({
  key: "real_1",
  title: "Asked on a real call: Delivery",
  verdict: "failed",
  reason: "It made up a delivery charge.",
  fix: "knowledge",
  owner: "knowledge",
  passes: 0,
  reliability: "failed",
  standing: "broken",
});

const HOURS = result({ key: "saved_1", title: "When do you open?", source: "saved" });

const FLAKY = result({
  key: "real_2",
  title: "Asked on a real call: Bulk order",
  verdict: "failed",
  reason: "Once it promised a discount.",
  fix: "script_step",
  owner: "script",
  passes: 2,
  reliability: "flaky",
  standing: "unreliable",
  tries: [
    { verdict: "passed", reason: "Fine.", turns: [{ said: "Bulk ga istara?", reply: "Team confirm chestundi andi." }] },
    { verdict: "failed", reason: "Once it promised a discount.", turns: [{ said: "Bulk ga istara?", reply: "Ten percent discount istam." }] },
    { verdict: "passed", reason: "Fine.", turns: [{ said: "Bulk ga istara?", reply: "Team confirm chestundi andi." }] },
  ],
});

function run(over: Partial<TestRun> = {}): TestRun {
  return {
    id: "run-2",
    status: "done",
    prompt_version: 12,
    is_current: true,
    round: 1,
    retest_of: null,
    auto_improve: false,
    score: { passed: 1, judged: 2, total: 4 },
    results: [PRICE, STOP, PERSON, HOURS],
    improvement: null,
    note: null,
    improving: false,
    improve_note: null,
    created_at: "2026-10-19T10:00:00Z",
    completed_at: "2026-10-19T10:09:00Z",
    set_version: 2,
    trials: 3,
    trials_done: 3,
    comparison: null,
    sounds: [{ kind: "formal_words", tests: 2 }],
    ...over,
  };
}

function tests(latest: TestRun | null, over: Partial<TestConversations> = {}): TestConversations {
  return {
    available: true,
    unavailable_reason: null,
    cost_note: "Not charged.",
    waiting_update: null,
    latest,
    history: [],
    waiting_tests: 0,
    practice_offered: false,
    trials: 3,
    max_replies: 60,
    ...over,
  };
}

const SAVED = { cases: [], available: true, unavailable_reason: null, live_version: 12, cost_note: "" };

function page(data: TestConversations, extra: Record<string, unknown> = {}) {
  return renderClientPage(<TestSection agent={AGENT} slug="acme" />, {
    "/v1/me": ME,
    "/v1/agents/agent-1/script/tests": data,
    "/v1/agents/agent-1/test-cases": SAVED,
    ...extra,
  });
}

describe("the practice tests in Training", () => {
  it("scores only what the owner's script decides and keeps our side apart (the screenshot)", async () => {
    await page(tests(run(), { waiting_update: "Your agreements are waiting." }));
    // One headline: right every time on 1 of the 2 tests the script decides.
    expect(await screen.findByRole("heading", { name: "Right every time on 1 of your 2 tests." })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Your score" }).textContent).toBe("1 right every time1 needs a fix");
    // The rule we failed is ours: in "On our side", never under what the owner fixes.
    const attention = screen.getByRole("heading", { name: /Your agent is missing an answer/ }).closest("section");
    expect(attention?.textContent).toContain("Asked on a real call: Delivery");
    expect(attention?.textContent).not.toContain("Asks not to be called again");
    expect(screen.getByText(/1 test failed on a rule we keep for every agent/)).toBeTruthy();
    expect(screen.getByText(/some answers used textbook words \(2 tests\)/)).toBeTruthy();
    expect(screen.getByText(/do not count against your agent/)).toBeTruthy();
    expect(screen.queryByText(/contact us/i)).toBeNull();
    // The sandbox's hand-over reply is for the owner to read, with the languages shown.
    const read = screen.getByRole("heading", { name: /Read these yourself/ }).closest("section");
    expect(read?.textContent).toContain("Asks to speak to a person");
    expect(screen.getAllByText(", Telugu").length).toBeGreaterThan(0);
    expect(screen.getByText(/Your agreements are waiting/)).toBeTruthy();
    // No trend against a different set of tests.
    expect(screen.queryByText(/than last time/)).toBeNull();
  });

  it("offers one primary action: Pip's fixes for tests that fail every time, prefilled and not sent", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await page(tests(run({ results: [PRICE, FLAKY, HOURS] })));
    fireEvent.click(await screen.findByRole("button", { name: "Let Pip suggest fixes" }));
    // A test right on 2 of 3 tries is not reliable yet, and not Pip's to chase.
    const fixOne = screen.getAllByRole("button", { name: "Let Pip suggest a fix" });
    expect(fixOne).toHaveLength(1);
    fireEvent.click(fixOne[0]);
    expect(asked.map((a) => a.prompt)).toEqual([
      FIX_ALL_REQUEST,
      "Suggest a fix for this agent's failed test “Asked on a real call: Delivery”.",
    ]);
    expect(screen.getByText("Not reliable yet")).toBeTruthy();
    expect(screen.getByText("Right 2 of 3 times")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Try \d/ })).toHaveLength(3);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows another try's conversation on demand", async () => {
    await page(tests(run({ results: [FLAKY] })));
    // The failing try is shown first.
    expect(await screen.findByText("Ten percent discount istam.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Try 1/ }));
    expect(screen.getByText("Team confirm chestundi andi.")).toBeTruthy();
  });

  it("leads a test again with what changed on the same tests, and offers Undo for a regression", async () => {
    const compared = run({
      retest_of: "run-1",
      results: [
        { ...PRICE, verdict: "passed", owner: null, standing: "works", reliability: "passed", passes: 3, change: "fixed" },
        { ...HOURS, verdict: "failed", owner: "script", fix: "script_step", standing: "broken", reliability: "failed", passes: 0, change: "broken" },
      ],
      comparison: { with_run: "run-1", with_version: 11, fixed: 1, broken: 1, still: 0, same: 0, new: 0, same_script: false },
    });
    const { calls } = await page(tests(compared), {
      "POST /v1/agents/agent-1/script/versions/11/restore": { script: { schema_version: 2, stages: [] }, saved_at: "2026-10-19T10:10:00Z" },
    });
    expect(await screen.findByRole("heading", { name: "1 fixed, 1 newly broken since the last test." })).toBeTruthy();
    expect(screen.getByText("Fixed")).toBeTruthy();
    expect(screen.getByText("Newly broken")).toBeTruthy();
    // Undo is the one primary action while a change broke a test.
    expect(screen.queryByRole("button", { name: "Let Pip suggest fixes" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo the last change" }));
    expect(await screen.findByText("The earlier script is in your draft")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/versions/11/restore"))).toBe(true);
  });

  it("asks the same tests again, and adds new tests only as a new set", async () => {
    const { calls } = await page(tests(run(), { waiting_tests: 2, practice_offered: true }), {
      "POST /v1/agents/agent-1/script/tests": tests(run({ id: "run-3", status: "queued", trials_done: 0 })),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Test again" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/script/tests"))).toBe(true));
    const posted = calls.filter((c) => c.method === "POST" && c.path.endsWith("/script/tests"));
    expect(JSON.parse(posted[0]?.body ?? "null")).toEqual({ retest_of: "run-2", auto_improve: false });
  });

  it("offers waiting tests and practice callers as a new set", async () => {
    const { calls } = await page(tests(run(), { waiting_tests: 2, practice_offered: true }), {
      "POST /v1/agents/agent-1/script/tests": tests(run({ id: "run-3", status: "queued", trials_done: 0 })),
    });
    expect(await screen.findByRole("button", { name: "Add practice callers" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add 2 new tests" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/script/tests"))).toBe(true));
    const posted = calls.filter((c) => c.method === "POST" && c.path.endsWith("/script/tests"));
    expect(JSON.parse(posted[0]?.body ?? "null")).toEqual({ practice_callers: false });
  });

  it("shows which try is running", async () => {
    await page(tests(run({ status: "running", trials_done: 1 })));
    expect(await screen.findByText("Try 2 of 3")).toBeTruthy();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("says a run that stopped judged nothing, and retries the same comparison", async () => {
    const { calls } = await page(tests(run({ status: "failed", retest_of: "run-1", error_code: "stalled", results: [] })), {
      "POST /v1/agents/agent-1/script/tests": tests(run({ id: "run-3", status: "queued", trials_done: 0 })),
    });
    expect(await screen.findByText("The test did not finish")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/script/tests"))).toBe(true));
    const posted = calls.filter((c) => c.method === "POST" && c.path.endsWith("/script/tests"));
    expect(JSON.parse(posted[0]?.body ?? "null")).toEqual({ retest_of: "run-1" });
  });

  it("invites the first run", async () => {
    await page(tests(null));
    expect(await screen.findByRole("heading", { name: "Check your agent before your callers do" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run the tests" })).toBeTruthy();
  });
  it("asks for prices before the first run when nothing the agent knows has one (D-849)", async () => {
    await page(tests(null, { missing_facts: ["prices"] }));
    expect(await screen.findByText("Add your prices first")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add prices" }).getAttribute("href")).toContain("/knowledge");
    expect(screen.getByRole("button", { name: "Run the tests" })).toBeTruthy();
  });

  it("shows the fixes being worked out, and why they could not be", async () => {
    await page(tests(run({ improving: true })));
    expect(await screen.findByText(/Working out fixes for 1 test/)).toBeTruthy();
  });

  it("says why suggestions could not be made", async () => {
    await page(tests(run({ improve_note: "Suggestions could not be worked out, because this month's AI help allowance is used up." })));
    expect(await screen.findByText(/allowance is used up/)).toBeTruthy();
  });

  it("routes a setting to its setting and lets the owner mark a test wrong (D-823)", async () => {
    const OFF = { ...PERSON, owner: "setting" as const, fix: "settings", standing: "setting" as const, setting: { area: "handover" as const, reason: "Hand-over to a person is switched off for this agent." } };
    const { calls } = await page(tests(run({ results: [PRICE, OFF, HOURS] })), {
      "POST /v1/agents/agent-1/script/tests/run-2/results/real_1/wrong": tests(
        run({ results: [{ ...PRICE, owner: "test", marked_wrong: true, standing: "wrong", counted: false }, OFF, HOURS] }),
      ),
    });
    await screen.findByText("Asked on a real call: Delivery");
    expect(screen.getByRole("link", { name: "Open call handling" }).getAttribute("href")).toContain("section=settings#call-handling");
    fireEvent.click(screen.getAllByRole("button", { name: "This test is wrong" })[0]);
    expect((await screen.findAllByText("Marked wrong")).length).toBeGreaterThan(0);
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/results/real_1/wrong"))).toBe(true);
  });

  it("answers a Test again with nothing changed as guidance in the server's words, not an error", async () => {
    await page(tests(run({ results: [PRICE, HOURS] })), {
      "POST /v1/agents/agent-1/script/tests": problem(422, {
        type: "https://calevate.tech/problems/agent_tests_nothing_changed",
        title: "We cannot do that",
        kind: "business_rule",
        detail: "Nothing has changed since that test: the same tests would fail again.",
        remediation: "Keep a suggested fix and put it live. Then test again.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Test again" }));
    const said = await screen.findByText("Nothing has changed since that test: the same tests would fail again.");
    const notice = said.closest("[data-notice]");
    expect(notice?.getAttribute("data-notice")).toBe("neutral");
    expect(notice?.getAttribute("role")).toBe("status");
    expect(notice?.textContent).toContain("Keep a suggested fix and put it live.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("We cannot do that")).toBeNull();
    // The way forward is still the one primary action.
    expect(screen.getByRole("button", { name: "Let Pip suggest fixes" })).toBeTruthy();
  });

  it("shows the judge's reason on the closed row, and what a good answer does when opened", async () => {
    await page(tests(run({ results: [{ ...PRICE, expect: "Says delivery is free above ₹500." }, HOURS] })));
    const row = (await screen.findByText("Asked on a real call: Delivery")).closest("details");
    expect(row?.open).toBe(false);
    expect(row?.querySelector("summary")?.textContent).toContain("It made up a delivery charge.");
    expect(row?.querySelector("summary")?.textContent).toContain("Wrong all 3 times");
    expect(row?.textContent).toContain("A good answer: Says delivery is free above ₹500.");
  });

  it("tests a changed script first, and shows the same tests over time", async () => {
    const entry = (id: string, passed: number) => ({
      id,
      created_at: "2026-10-19T10:00:00Z",
      prompt_version: 12,
      round: 1,
      score: { passed, judged: 2, total: 4 },
      set_version: 2,
    });
    await page(tests(run({ is_current: false }), { history: [entry("run-2", 1), entry("run-1", 0)] }));
    expect(await screen.findByText(/The script has changed since this test/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Test again" }).className).toContain("bg-brand-strong");
    expect(screen.queryByRole("button", { name: "Let Pip suggest fixes" })).toBeNull();
    const overTime = screen.getByRole("list", { name: "These tests over time" });
    expect(overTime.textContent).toContain("0 of 2");
    expect(overTime.textContent).toContain("This test1 of 2");
  });

  it("has no accessibility violations with every group open", async () => {
    const OFF = { ...PERSON, key: "off", owner: "setting" as const, fix: "settings", standing: "setting" as const, setting: { area: "handover" as const, reason: "Hand-over is off." } };
    const { container } = await page(tests(run({ results: [PRICE, FLAKY, OFF, STOP, PERSON, HOURS] })));
    await screen.findByText("Asked on a real call: Delivery");
    container.querySelectorAll("details").forEach((d) => (d.open = true));
    await expectNoA11yViolations(container, "practice tests");
  });
});

describe("test copy", () => {
  it("names a line's language from its letters", () => {
    expect(languageOf("ఈ call record అవుతుందా?")).toBe("Telugu");
    expect(languageOf("क्या ये call record हो रही है?")).toBe("Hindi");
    expect(languageOf("Is this call recorded?")).toBe("English");
    expect(languageOf("…")).toBeNull();
  });

  it("counts the owner's score without the rules or our side", () => {
    expect(countsOf([PRICE, STOP, PERSON, HOURS, FLAKY])).toEqual({
      passed: 1,
      failing: 2,
      unreliable: 1,
      unchecked: 1,
      ours: 1,
      total: 5,
    });
    // A result stored before D-828 (no standing) reads from its verdict and owner.
    expect(countsOf([{ verdict: "failed", fix: "platform", probe: null }, { verdict: "failed", fix: "style", probe: null }]).ours).toBe(2);
  });

  it("says how often a test was right, and which are worth a fix", () => {
    expect(triesLine(FLAKY)).toBe("Right 2 of 3 times");
    expect(triesLine(PRICE)).toBe("Wrong all 3 times");
    expect(triesLine({ passes: 1, judged_tries: 1 })).toBeNull();
    expect(isFixable(PRICE)).toBe(true);
    expect(isFixable(FLAKY)).toBe(false);
    expect(isFixable({ ...FLAKY, passes: 1 })).toBe(true);
    expect(isFixable(STOP)).toBe(false);
  });

  it("leads with the change on the same tests, or the score on a new set", () => {
    expect(headlineOf(run()).title).toBe("Right every time on 1 of your 2 tests.");
    expect(headlineOf(run({ results: [HOURS] })).title).toBe("Right every time on your one test.");
    const same = run({ comparison: { with_run: "a", with_version: 12, fixed: 0, broken: 0, still: 1, same: 1, new: 0, same_script: true } });
    expect(headlineOf(same).title).toBe("No change since the last test.");
  });

  it("groups failures by what fixes them, in the order the owner acts on them", () => {
    const OFF = { ...PRICE, key: "off", owner: "setting" as const, standing: "setting" as const };
    const groups = fixGroups([OFF, HOURS, PRICE, FLAKY, STOP, PERSON]);
    expect(groups.map((g) => [g.group, g.rows.map((r) => r.key)])).toEqual([
      ["script", ["real_2"]],
      ["knowledge", ["real_1"]],
      ["setting", ["off"]],
    ]);
  });

  it("keeps progress to runs of the same tests, oldest first", () => {
    const entry = (id: string, set: number, passed: number) => ({
      id,
      created_at: "2026-10-19T10:00:00Z",
      prompt_version: 1,
      round: 1,
      score: { passed, judged: 4, total: 5 },
      set_version: set,
    });
    const history = [entry("run-2", 2, 3), entry("run-1b", 2, 1), entry("run-0", 1, 4)];
    expect(progressOf(history, { id: "run-2", set_version: 2 })?.map((p) => [p.id, p.passed, p.latest])).toEqual([
      ["run-1b", 1, false],
      ["run-2", 3, true],
    ]);
    expect(progressOf(history, { id: "run-0", set_version: 1 })).toBeNull();
    expect(progressOf(history, { id: "run-2", set_version: null })).toBeNull();
  });

  it("picks one next step, most urgent first", () => {
    const base = {
      canWrite: true,
      broke: false,
      restored: false,
      hasProposal: false,
      isCurrent: true,
      fixable: 0,
      settings: 0,
      failing: 0,
    };
    expect(nextStepOf({ ...base, broke: true, fixable: 2 })).toBe("undo");
    expect(nextStepOf({ ...base, broke: true, canWrite: false, hasProposal: true })).toBe("review");
    expect(nextStepOf({ ...base, isCurrent: false, fixable: 2 })).toBe("retest");
    expect(nextStepOf({ ...base, fixable: 2, settings: 1, failing: 3 })).toBe("fix");
    expect(nextStepOf({ ...base, settings: 1, failing: 1 })).toBe("setting");
    expect(nextStepOf({ ...base, failing: 1 })).toBe("hold");
    expect(nextStepOf(base)).toBe("done");
  });
});
