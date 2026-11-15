import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImprovementReview } from "@/app/c/[slug]/agents/[agentId]/script/ImprovementReview";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type Improvement, type ScriptOut, type TestRun } from "@/lib/api/script";

import { problem, renderClientPage, type ApiCall, type Routes } from "./harness";

/**
 * The agent and script screens (audit 15 Nov 2026): each case is a user action whose result
 * was wrong before its fix.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "agents:write", "org:manage", "kb:write", "org:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const SCRIPT: ScriptOut = {
  script: { ...EMPTY_SCRIPT, goal: "Book visits" },
  stored_schema_version: 2,
  context: null,
  draft: null,
  version: 3,
  is_freeform: false,
  has_pending: false,
  standard_variables: [],
};

function improvementWith(facts: Improvement["facts"]): Improvement {
  return {
    base: "live",
    edits: [],
    facts,
    for_keys: [],
    disclosure: null,
    created_at: "2026-11-15T00:00:00Z",
    tested: true,
  };
}

const RUN = { id: "run-1", results: [] } as unknown as TestRun;

describe("suggested fixes: the facts to pin", () => {
  it("names each fact's tick box, whatever the question says", async () => {
    await renderClientPage(
      <ImprovementReview
        agentId="agent-1"
        run={RUN}
        improvement={improvementWith([
          { action: "add", fact_id: null, question: "What are your opening hours?", answer: "9 to 6", because: null, why: "" },
          { action: "add", fact_id: null, question: "What are your opening hours on Sunday?", answer: "Closed", because: null, why: "" },
        ])}
        onClose={() => undefined}
        onTestAgain={() => undefined}
      />,
      { "/v1/me": OWNER, "/v1/agents/agent-1/script": SCRIPT },
    );
    expect(await screen.findByRole("checkbox", { name: "Pin a fact: What are your opening hours?" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Pin a fact: What are your opening hours on Sunday?" })).toBeTruthy();
  });

  it("does not pin a fact twice when Keep is pressed again after a later step failed", async () => {
    let settles = 0;
    const routes: Routes = {
      "/v1/me": OWNER,
      "/v1/agents/agent-1/script": SCRIPT,
      "POST /v1/kb/facts": { id: "fact-1", text: "9 to 6", question: "Hours?", pinned: true },
      "POST /v1/agents/agent-1/script/tests/run-1/improvement/settle": () =>
        ++settles === 1 ? problem(503, { title: "Try again in a moment.", retryable: true }) : { available: true, latest: null, history: [] },
    };
    const { calls } = await renderClientPage(
      <ImprovementReview
        agentId="agent-1"
        run={RUN}
        improvement={improvementWith([
          { action: "add", fact_id: null, question: "Hours?", answer: "9 to 6", because: null, why: "" },
        ])}
        onClose={() => undefined}
        onTestAgain={() => undefined}
      />,
      routes,
    );
    const adds = () => calls.filter((c: ApiCall) => c.method === "POST" && c.path === "/v1/kb/facts").length;
    fireEvent.click(await screen.findByRole("button", { name: "Keep 1" }));
    expect((await screen.findAllByRole("alert"))[0]!.textContent).toContain("Try again in a moment.");
    expect(adds()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Keep 1" }));
    expect(await screen.findByText("Kept")).toBeTruthy();
    expect(settles).toBe(2);
    expect(adds()).toBe(1);
  });

  it("does not put the same fixes live twice when Keep and put live is pressed again", async () => {
    let settles = 0;
    const edit = { id: "e1", op: "set_part", label: "How it ends the call", before: "", after: "Thank them.", because: null, why: "x" };
    const { calls } = await renderClientPage(
      <ImprovementReview
        agentId="agent-1"
        run={RUN}
        improvement={{ ...improvementWith([]), edits: [edit] } as Improvement}
        onClose={() => undefined}
        onTestAgain={() => undefined}
      />,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1/script": SCRIPT,
        "POST /v1/agents/agent-1/script/tests/run-1/improvement/apply": { script: SCRIPT.script, skipped: [] },
        "POST /v1/agents/agent-1/script/publish": { version: 4, live: true },
        "POST /v1/agents/agent-1/script/tests/run-1/improvement/settle": () =>
          ++settles === 1 ? problem(503, { title: "Try again in a moment.", retryable: true }) : { available: true, latest: null, history: [] },
      },
    );
    const publishes = () => calls.filter((c: ApiCall) => c.path === "/v1/agents/agent-1/script/publish").length;
    fireEvent.click(await screen.findByRole("button", { name: "Keep and put live" }));
    await waitFor(() => expect(settles).toBe(1));
    expect(await screen.findByText("Try again in a moment.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep and put live" }));
    expect(await screen.findByText("Callers hear them from the next call.")).toBeTruthy();
    expect(publishes()).toBe(1);
  });
});
