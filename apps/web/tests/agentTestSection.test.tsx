import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FIX_ALL_REQUEST, TestSection } from "@/app/c/[slug]/agents/[agentId]/test/TestSection";
import {
  countsOf,
  fixGroups,
  headlineOf,
  isFixable,
  languageOf,
  lastRunLine,
  nextStepOf,
  progressOf,
  triesLine,
} from "@/app/c/[slug]/agents/[agentId]/test/testCopy";
import type { Agent } from "@/lib/api/agents";
import type { Me } from "@/lib/api/client";
import type { TestConversations, TestResult, TestRun } from "@/lib/api/script";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { expectNoA11yViolations } from "./a11y";
import { noReply, problem, renderClientPage } from "./harness";

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


/** The card a test title sits in. */
const card = (title: string) => screen.getByText(title).closest("li") as HTMLElement;

describe("the practice tests in Training", () => {
  it("scores only what the owner's script decides and keeps our side apart (the screenshot)", async () => {
    const { container } = await page(tests(run(), { waiting_update: "Your agreements are waiting." }));
    // One verdict: a number, not a sentence.
    expect(await screen.findByRole("heading", { name: "1 of 2 OK" })).toBeTruthy();
    // The bar is tiny and wordless; the number above says it.
    expect(container.querySelector("[data-score-bar]")?.getAttribute("aria-hidden")).toBe("true");
    expect(screen.queryByRole("list", { name: "Your score" })).toBeNull();
    // The rule we failed is ours: never a card for the owner to act on.
    const look = screen.getByRole("list", { name: "Tests to look at" });
    expect(look.textContent).toContain("Asked on a real call: Delivery");
    expect(look.textContent).not.toContain("Asks not to be called again");
    // Our side is one muted line with nothing to open; the details are Pip's to explain.
    expect(screen.getByText("1 test is ours to fix, not yours.")).toBeTruthy();
    expect(screen.queryByText(/textbook words/i)).toBeNull();
    expect(screen.queryByText(/Show details/)).toBeNull();
    expect(screen.queryByText(/contact us/i)).toBeNull();
    // The sandbox's hand-over reply is for the owner to check, its chat one tap away.
    const person = card("Asks to speak to a person");
    expect(person.textContent).toContain("Check it yourself");
    fireEvent.click(within(person).getByRole("button", { name: "See the chat" }));
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
    const primary = await screen.findByRole("button", { name: "Fix 1 with Pip" });
    expect(primary.className).toContain("bg-brand-strong");
    fireEvent.click(primary);
    // A test OK on 2 of 3 tries is Sometimes OK, and not Pip's to chase.
    const fixOne = screen.getAllByRole("button", { name: "Fix it" });
    expect(fixOne).toHaveLength(1);
    fireEvent.click(fixOne[0]);
    expect(asked.map((a) => a.prompt)).toEqual([
      FIX_ALL_REQUEST,
      "Suggest a fix for this agent's failed test “Asked on a real call: Delivery”.",
    ]);
    const flaky = card("Asked on a real call: Bulk order");
    expect(flaky.textContent).toContain("Sometimes OK");
    // How often, and why Pip leaves it, wait behind "Why?".
    expect(screen.queryByText(/OK 2 of 3 times/)).toBeNull();
    fireEvent.click(within(flaky).getByRole("button", { name: "Why?" }));
    expect(within(flaky).getByText(/OK 2 of 3 times/)).toBeTruthy();
    expect(within(flaky).getByText("Mostly OK, so Pip leaves it alone.")).toBeTruthy();
    fireEvent.click(within(flaky).getByRole("button", { name: "See the chat" }));
    expect(within(flaky).getAllByRole("button", { name: /Chat \d/ })).toHaveLength(3);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows another try's conversation on demand", async () => {
    await page(tests(run({ results: [FLAKY] })));
    fireEvent.click(await screen.findByRole("button", { name: "See the chat" }));
    // The failing try is shown first.
    expect(await screen.findByText("Ten percent discount istam.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Chat 1/ }));
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
    expect(await screen.findByRole("heading", { name: "1 fixed, 1 broke" })).toBeTruthy();
    expect(screen.getByText("Now 1 of 2 OK")).toBeTruthy();
    expect(screen.getByText("Your last change broke 1 test.")).toBeTruthy();
    // The broken test says so in its one status.
    expect(card("When do you open?").textContent).toContain("Broke");
    // Undo leads while a change broke a test; the fixes stay offered beside it.
    expect(screen.getByRole("button", { name: "Undo last change" }).className).toContain("bg-brand-strong");
    expect(screen.getByRole("button", { name: "Fix 1 with Pip" }).className).not.toContain("bg-brand-strong");
    fireEvent.click(screen.getByRole("button", { name: "Undo last change" }));
    expect(await screen.findByText("Earlier script is in your draft")).toBeTruthy();
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

  it("shows which round is running", async () => {
    await page(tests(run({ status: "running", trials_done: 1 })));
    expect(await screen.findByText("Round 2 of 3")).toBeTruthy();
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

  it("says a run that could not be asked as a call needs calling set up, naming no provider", async () => {
    await page(tests(run({ status: "failed", error_code: "engine_test_call_not_set_up", results: [] })));
    expect(await screen.findByText("The test did not finish")).toBeTruthy();
    expect(screen.getByText(/This agent cannot take calls yet/)).toBeTruthy();
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
    // A moving bar named for what it is doing, not a sentence; no actions while it runs.
    expect(await screen.findByRole("progressbar", { name: "Pip is fixing 1 test" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Test again" })).toBeNull();
  });

  it("shows one state when an older fix waits and the newest round came back empty", async () => {
    const improvement = {
      base: "live" as const,
      edits: [{ id: "e1", op: "set_step" as const, label: "Step 2", before: "Ask.", after: "Ask again.", because: null, why: "" }],
      facts: [],
      for_keys: [],
      disclosure: null,
      created_at: "2026-10-19T10:00:00Z",
      tested: false,
    };
    await page(
      tests(
        run({
          improvement,
          improve_stop: "failed",
          improve_note: "Suggestions could not be worked out, because the AI's answer came back incomplete.",
        }),
      ),
      { "/v1/agents/agent-1/script": noReply() },
    );
    expect(await screen.findByText("These fixes are from before.")).toBeTruthy();
    // The failed round is said once, quietly: never as a warning beside the waiting fixes.
    expect(screen.queryByText(/came back incomplete/)).toBeNull();
  });

  it("points at fixes that are ready and folded away", async () => {
    const improvement = {
      base: "live" as const,
      edits: [{ id: "e1", op: "set_step" as const, label: "Step 2", before: "Ask.", after: "Ask again.", because: null, why: "" }],
      facts: [],
      for_keys: [],
      disclosure: null,
      created_at: "2026-10-19T10:00:00Z",
      tested: false,
    };
    await page(tests(run({ improvement })), { "/v1/agents/agent-1/script": noReply() });
    expect(await screen.findByText("Pip's fixes are below.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "See the fixes" })).toBeNull();
  });

  it("says why suggestions could not be made", async () => {
    await page(tests(run({ improve_note: "Suggestions could not be worked out, because this month's AI help allowance is used up." })));
    expect(await screen.findByText(/allowance is used up/)).toBeTruthy();
  });

  it("routes a setting and a missing answer to where they are fixed, and lets the owner say not a problem (D-823)", async () => {
    const OFF = { ...PERSON, owner: "setting" as const, fix: "settings", standing: "setting" as const, setting: { area: "handover" as const, reason: "Hand-over to a person is switched off for this agent." } };
    const { calls } = await page(tests(run({ results: [PRICE, OFF, HOURS] })), {
      "POST /v1/agents/agent-1/script/tests/run-2/results/real_1/wrong": tests(
        run({ results: [{ ...PRICE, owner: "test", marked_wrong: true, standing: "wrong", counted: false }, OFF, HOURS] }),
      ),
    });
    await screen.findByText("Asked on a real call: Delivery");
    // The setting is the primary next step and its card's own button.
    expect(screen.getAllByRole("link", { name: "Open call handling" })[0].getAttribute("href")).toContain("section=settings#call-handling");
    const price = card("Asked on a real call: Delivery");
    expect(within(price).getByRole("link", { name: "Add answer" }).getAttribute("href")).toContain("/c/acme/knowledge");
    fireEvent.click(within(price).getByRole("button", { name: "Why?" }));
    fireEvent.click(within(price).getByRole("button", { name: "Not a problem" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/results/real_1/wrong"))).toBe(true));
    // It moves to the folded "Not a problem" list.
    await waitFor(() => expect(screen.getByText("Asked on a real call: Delivery").closest("details")).toBeTruthy());
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
    expect(screen.getByRole("button", { name: "Fix 1 with Pip" })).toBeTruthy();
  });

  it("keeps the judge's reason behind Why?, with what a good answer does", async () => {
    await page(tests(run({ results: [{ ...PRICE, expect: "Says delivery is free above ₹500." }, HOURS] })));
    const price = (await screen.findByText("Asked on a real call: Delivery")).closest("li") as HTMLElement;
    // One status per card, and no reason until asked for.
    expect(price.textContent).toContain("Not OK");
    expect(price.textContent).not.toContain("It made up a delivery charge.");
    fireEvent.click(within(price).getByRole("button", { name: "Why?" }));
    expect(price.textContent).toContain("What happenedIt made up a delivery charge.");
    expect(price.textContent).toContain("A good answerSays delivery is free above ₹500.");
    expect(price.textContent).toContain("From a real call");
  });

  it("tests a changed script first, and keeps the same tests over time inside How this works", async () => {
    const entry = (id: string, passed: number) => ({
      id,
      created_at: "2026-10-19T10:00:00Z",
      prompt_version: 12,
      round: 1,
      score: { passed, judged: 2, total: 4 },
      set_version: 2,
    });
    await page(tests(run({ is_current: false }), { history: [entry("run-2", 1), entry("run-1", 0)] }));
    expect(await screen.findByText("The script changed since this test.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Test again" }).className).toContain("bg-brand-strong");
    expect(screen.queryByRole("button", { name: /with Pip/ })).toBeNull();
    // Hidden by default; one tap on "How this works" shows it.
    expect(screen.queryByRole("list", { name: "These tests over time" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "How this works" }));
    const overTime = await screen.findByRole("list", { name: "These tests over time" });
    expect(overTime.textContent).toContain("0 of 2 OK");
    expect(overTime.textContent).toContain("This test1 of 2 OK");
    expect(screen.getByText(/Last test:/)).toBeTruthy();
  });

  it("keeps an all-OK Test again to a check, a number and Test again (founder, 28 Oct)", async () => {
    const SHOP = result({ key: "saved_2", title: "Where is the shop?", source: "saved", change: "same" });
    const entry = (id: string, passed: number, judged: number) => ({
      id,
      created_at: "2026-10-27T06:09:00Z",
      prompt_version: 8,
      round: 1,
      score: { passed, judged, total: judged },
      set_version: 2,
    });
    const { container } = await page(
      tests(
        run({
          retest_of: "run-1",
          results: [{ ...HOURS, change: "same" }, SHOP],
          comparison: { with_run: "run-1", with_version: 7, fixed: 0, broken: 0, still: 0, same: 2, new: 0, same_script: false },
        }),
        { history: [entry("run-2", 2, 2), entry("run-1", 3, 3)] },
      ),
    );
    expect(await screen.findByRole("heading", { name: "All 2 OK" })).toBeTruthy();
    expect(screen.getByText("Same as last time")).toBeTruthy();
    // A bar of one colour said nothing the number does not.
    expect(container.querySelector("[data-score-bar]")).toBeNull();
    expect(screen.queryByRole("list", { name: "Tests to look at" })).toBeNull();
    expect(screen.getByRole("button", { name: "Test again" })).toBeTruthy();
    // The tests that were OK wait folded, one tap away.
    expect(screen.getByText("Where is the shop?").closest("details")?.open).toBe(false);
  });

  it("has no accessibility violations with every card open", async () => {
    const OFF = { ...PERSON, key: "off", owner: "setting" as const, fix: "settings", standing: "setting" as const, setting: { area: "handover" as const, reason: "Hand-over is off." } };
    const { container } = await page(tests(run({ results: [PRICE, FLAKY, OFF, STOP, PERSON, HOURS] })));
    await screen.findByText("Asked on a real call: Delivery");
    container.querySelectorAll("details").forEach((d) => (d.open = true));
    for (const name of ["Why?", "See the chat"]) {
      screen.getAllByRole("button", { name }).forEach((button) => fireEvent.click(button));
    }
    await expectNoA11yViolations(container, "practice tests");
  });
});

/**
 * THE WORDINESS GUARD (founder, 28 Oct 2026: "more buttons and short sentences"). Every line
 * this tab shows before anything is opened stays short, so explanation sentences cannot creep
 * back. Not counted: a test's title (`data-user-text`, the server's words), the server's own
 * notices (`data-server-text`), anything screen-reader-only or inside a closed fold.
 */
const LINE_MAX = 60;
const BLOCKS = "p,h4,h5,li,button,a,summary,dt,dd,label,[role=progressbar]";

function shownLines(root: HTMLElement): string[] {
  const lines: string[] = [];
  root.querySelectorAll<HTMLElement>(BLOCKS).forEach((el) => {
    if (el.closest("[data-user-text],[data-server-text],.sr-only,[hidden],[aria-hidden='true']")) return;
    // Inside a closed fold, only that fold's own summary is on screen.
    for (let fold = el.closest("details"); fold; fold = fold.parentElement?.closest("details") ?? null) {
      if (!fold.open && el.closest("summary")?.parentElement !== fold) return;
    }
    const own = el.cloneNode(true) as HTMLElement;
    own.querySelectorAll(`${BLOCKS},[data-user-text],.sr-only,[aria-hidden='true']`).forEach((child) => child.remove());
    const text = (own.textContent ?? "").replace(/\s+/g, " ").trim();
    if (text) lines.push(text);
  });
  return lines;
}

describe("the Training tab's default view stays short", () => {
  const OFF = { ...PERSON, key: "off", owner: "setting" as const, fix: "settings", standing: "setting" as const, setting: { area: "handover" as const, reason: "Hand-over to a person is switched off for this agent." } };
  const LONG = { ...PRICE, reason: "The agent incorrectly accepted a partial phone number as a complete number and moved on without asking.".repeat(2) };
  const improvement = {
    base: "live" as const,
    edits: [{ id: "e1", op: "set_step" as const, label: "Step 2", before: "Ask.", after: "Ask again.", because: null, why: "" }],
    facts: [],
    for_keys: [],
    disclosure: null,
    created_at: "2026-10-19T10:00:00Z",
    tested: false,
  };
  const STATES: [string, TestConversations][] = [
    ["failing", tests(run({ results: [LONG, FLAKY, OFF, STOP, PERSON, HOURS], note: "These tests come from your real calls, so no practice callers were written this time." }), { waiting_tests: 2, practice_offered: true })],
    ["all OK", tests(run({ results: [HOURS] }))],
    ["working", tests(run({ improving: true }))],
    ["ours only", tests(run({ results: [STOP, HOURS] }))],
    ["broke", tests(run({ results: [{ ...PRICE, change: "broken" }], comparison: { with_run: "run-1", with_version: 11, fixed: 0, broken: 1, still: 0, same: 0, new: 0, same_script: true } }))],
    ["changed script", tests(run({ is_current: false }))],
    ["running", tests(run({ status: "running", trials_done: 1 }))],
    ["stopped", tests(run({ status: "failed", error_code: "engine_test_call_not_set_up", results: [] }))],
    ["first run", tests(null, { missing_facts: ["prices"] })],
  ];

  it.each(STATES)("keeps every line on the %s view short", async (_name, data) => {
    const { container } = await page(data);
    await waitFor(() => expect(container.querySelector("h4, [data-notice]")).toBeTruthy());
    const long = shownLines(container).filter((line) => line.length > LINE_MAX);
    expect(long).toEqual([]);
  });

  it("sees a long line when one is on screen, and not one folded away", () => {
    const long = "x".repeat(LINE_MAX + 1);
    const { container } = render(
      <div>
        <p>{long}</p>
        <details>
          <summary>Open</summary>
          <p>{`${long}y`}</p>
        </details>
      </div>,
    );
    expect(shownLines(container)).toEqual([long, "Open"]);
  });

  it("keeps the folded Practice callers line short", () => {
    const counts = countsOf([PRICE, FLAKY, OFF, STOP, PERSON, HOURS]);
    expect(lastRunLine(counts, true)).toBe("1 of 4 OK, 1 to check, fixes ready");
    expect(lastRunLine(counts, true).length).toBeLessThanOrEqual(LINE_MAX);
  });

  it("shows fixes ready under the limit too, apart from the review the owner opened", async () => {
    const { container } = await page(tests(run({ improvement })), { "/v1/agents/agent-1/script": noReply() });
    await screen.findByText("Pip's fixes are below.");
    const verdict = container.querySelector("section[aria-labelledby='tests-summary-heading']") as HTMLElement;
    expect(shownLines(verdict).filter((line) => line.length > LINE_MAX)).toEqual([]);
  });
});

describe("test copy", () => {
  it("names a line's language from its letters", () => {
    expect(languageOf("ఈ call record అవుతుందా?")).toBe("Telugu");
    expect(languageOf("क्या ये call record हो रही है?")).toBe("Hindi");
    expect(languageOf("Is this call recorded?")).toBe("English");
    expect(languageOf("…")).toBeNull();
  });

  it("scores a run of only rules and our side by what was OK, never 0 of 0", () => {
    const HOURS_RULE = result({ key: "probe_ai", title: "Says it is an AI", probe: "ai", source: "standard", counted: false });
    const onlyRules = run({ results: [HOURS_RULE, STOP] });
    expect(headlineOf(onlyRules).title).toBe("1 of 1 OK");
    expect(headlineOf(onlyRules).tone).toBe("ok");
    expect(lastRunLine(countsOf(onlyRules.results), true)).toBe("1 of 1 OK, fixes ready");
    expect(lastRunLine(countsOf([STOP]), false)).toBe("Nothing to score");
  });

  it("counts the owner's score without the rules or our side", () => {
    expect(countsOf([PRICE, STOP, PERSON, HOURS, FLAKY])).toEqual({
      passed: 1,
      works: 1,
      failing: 2,
      unreliable: 1,
      unchecked: 1,
      ours: 1,
      total: 5,
    });
    // A result stored before D-828 (no standing) reads from its verdict and owner.
    expect(countsOf([{ verdict: "failed", fix: "platform", probe: null }, { verdict: "failed", fix: "style", probe: null }]).ours).toBe(2);
  });

  it("says how often a test was OK, and which are worth a fix", () => {
    expect(triesLine(FLAKY)).toBe("OK 2 of 3 times");
    // Wrong (or right) every time is the status's to say, not a second line's.
    expect(triesLine(PRICE)).toBeNull();
    expect(triesLine({ passes: 1, judged_tries: 1 })).toBeNull();
    expect(isFixable(PRICE)).toBe(true);
    expect(isFixable(FLAKY)).toBe(false);
    expect(isFixable({ ...FLAKY, passes: 1 })).toBe(true);
    expect(isFixable(STOP)).toBe(false);
  });

  it("leads with the change on the same tests, or the score on a new set", () => {
    expect(headlineOf(run()).title).toBe("1 of 2 OK");
    expect(headlineOf(run({ results: [HOURS] })).title).toBe("1 of 1 OK");
    // A passing rule check is not scored but is in the folded "OK" list, so the all-OK
    // number counts it too and the two match.
    const check = { ...HOURS, key: "rule-check", probe: "partial_number", counted: false };
    expect(headlineOf(run({ results: [HOURS, check] })).title).toBe("All 2 OK");
    // The folded row says the same number as the card it opens to.
    expect(lastRunLine(countsOf([HOURS, check]), false)).toBe("All 2 OK");
    const same = run({ comparison: { with_run: "a", with_version: 12, fixed: 0, broken: 0, still: 1, same: 1, new: 0, same_script: true } });
    // Nothing moved: the score leads and "Same as last time" is said once, underneath.
    expect(headlineOf(same).title).toBe("1 of 2 OK");
    expect(headlineOf(same).detail).toBe("Same as last time");
  });

  it("orders failures by what fixes them, in the order the owner acts on them", () => {
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
