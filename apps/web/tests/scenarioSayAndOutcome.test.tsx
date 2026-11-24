import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignWorkspace } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { addScenario, deleteScenario, outcomeOf, setOutcome } from "@/app/c/[slug]/campaigns/scenarioModel";
import { DEFAULT_LIMITS, SAY_EXACT_STEP, asSection, sectionDetail } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { WriteAccess } from "@/lib/api/hooks";
import { EMPTY_SCRIPT, STEP_OUTCOME_MAX, type CallScript, type ConversationStage } from "@/lib/api/script";

import {
  FIXTURE_AGENT_ID,
  FIXTURE_CAMPAIGN_ID,
  scriptVersionsFixture,
  settingsFixture,
  workspaceFixture,
} from "./campaignFixtures";
import { noReply, renderClientPage, type ApiCall, type Routes } from "./harness";

/**
 * The call flow's "Say this line exactly" switch on a scenario (D-1035) and each step's
 * "Outcome of this step" (founder, 23 Nov 2026), both saved with the flow's one Save.
 */

const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;

const stage = (over: Partial<ConversationStage> = {}): ConversationStage => ({
  id: "remind",
  name: "Does not remember us",
  mode: "guide",
  instruction: "Remind them who we are.",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  procedure: [],
  position: null,
  step: 1,
  scripts: { "te-IN": "Line one." },
  qa: [],
  coaching: [],
  ...over,
});

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello, this is the shop.",
  stages: [stage(), stage({ id: "close", name: "Close", instruction: "Thank them.", step: 2, scripts: {} })],
};

const routes = (script: CallScript): Routes => ({
  [`${base}/workspace`]: workspaceFixture({ script }),
  [`${base}/settings`]: settingsFixture(),
  [`${base}/script/versions`]: scriptVersionsFixture(),
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  "/v1/agents": [],
  "/v1/me": noReply(),
  [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
  [`PUT ${base}/script`]: workspaceFixture({ script }),
});

const render = (script: CallScript = SCRIPT) =>
  renderClientPage(<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, routes(script));

const savedScript = (calls: ApiCall[]): CallScript => {
  const put = calls.filter((c) => c.method === "PUT" && c.path === `${base}/script`);
  expect(put).toHaveLength(1);
  return (JSON.parse(put[0]?.body ?? "null") as { script: CallScript }).script;
};

const openScenario = async () => {
  fireEvent.click(await screen.findByRole("button", { name: /Does not remember us/ }));
  return screen.getByRole("switch", { name: /Say this line exactly/ }) as HTMLInputElement;
};

describe("Say this line exactly", () => {
  it("is off by default, says what it means, and is a native control a keyboard reaches", async () => {
    await render();
    const toggle = await openScenario();
    expect(toggle.checked).toBe(false);
    expect(toggle.tagName).toBe("INPUT");
    expect(toggle.type).toBe("checkbox");
    expect(toggle.disabled).toBe(false);
    expect(toggle.tabIndex).not.toBe(-1);
    toggle.focus();
    expect(document.activeElement).toBe(toggle);
    expect(screen.getByText("On: the agent says the script line word for word. Off: it says it in its own words.")).toBeTruthy();
  });

  it("turns on, marks the scenario, and saves mode say with the flow", async () => {
    const view = await render();
    const toggle = await openScenario();
    fireEvent.click(toggle);
    expect(toggle.checked).toBe(true);
    const card = screen.getByRole("button", { name: /Does not remember us/ });
    expect(within(card).getByText("Exact words")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save flow" }));
    await waitFor(() => expect(view.calls.some((c) => c.method === "PUT")).toBe(true));
    const saved = savedScript(view.calls);
    expect(saved.stages.map((s) => s.mode)).toEqual(["say", "guide"]);
    // A script with no outcomes does not gain the field from an unrelated edit.
    expect("step_outcomes" in saved).toBe(false);
  });

  it("turns back off to guide", async () => {
    const view = await render({ ...SCRIPT, stages: [stage({ mode: "say" }), ...SCRIPT.stages.slice(1)] });
    const toggle = await openScenario();
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Save flow" }));
    await waitFor(() => expect(view.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(savedScript(view.calls).stages[0]?.mode).toBe("guide");
  });

  it("says the agent uses its own words while there is no line to say", async () => {
    await render({ ...SCRIPT, stages: [stage({ scripts: {} }), ...SCRIPT.stages.slice(1)] });
    fireEvent.click(await openScenario());
    expect(screen.getByText(/Until then the agent uses its own words/)).toBeTruthy();
  });

  it("counts against the step's 600 the way the server compiles it", () => {
    const say = sectionDetail(asSection(stage({ mode: "say" })));
    expect(say).toContain(`Remind them who we are. ${SAY_EXACT_STEP}`);
    expect(say).not.toContain("Say: ");
    // A section from before scenarios still says its own instruction.
    expect(sectionDetail(asSection(stage({ mode: "say", step: null, scripts: {} })))).toBe('Say: "Remind them who we are."');
  });
});

describe("Outcome of this step", () => {
  it("shows above each step's scenarios, counts to 300 and saves with the flow", async () => {
    const view = await render();
    const box = (await screen.findByLabelText("Outcome of this step, step 1")) as HTMLTextAreaElement;
    expect(screen.getByLabelText("Outcome of this step, step 2")).toBeTruthy();
    expect(box.maxLength).toBe(STEP_OUTCOME_MAX);
    expect(screen.getAllByText(/What must be true before the call moves on/).length).toBeGreaterThan(0);
    fireEvent.change(box, { target: { value: "They know who is calling." } });
    expect(screen.getByText(`25/${STEP_OUTCOME_MAX}`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save flow" }));
    await waitFor(() => expect(view.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(savedScript(view.calls).step_outcomes).toEqual([{ step: 1, outcome: "They know who is calling." }]);
  });

  it("shows on the canvas columns too", async () => {
    const hear: WriteAccess = { allowed: true, reason: null, unknown: false };
    const scripted = setOutcome(SCRIPT, 2, "The call is closed politely.");
    await renderClientPage(
      <ScenarioFlow
        agent={null}
        hear={hear}
        script={{ ...scripted, stages: [stage({ mode: "say" }), ...SCRIPT.stages.slice(1)] }}
        limits={DEFAULT_LIMITS}
        issues={[]}
        languages={["te-IN"]}
        selected={null}
        readOnly={false}
        wide
        onSelect={() => {}}
        onChange={() => {}}
      />,
      {},
    );
    const region = await screen.findByRole("region", { name: "The call flow, step by step" });
    expect((within(region).getByLabelText("Outcome of this step, step 2") as HTMLTextAreaElement).value).toBe(
      "The call is closed politely.",
    );
    expect(within(region).getByText(/Exact words/)).toBeTruthy();
  });

  it("follows its step when steps are inserted or closed up, and a blank one is removed", () => {
    let script = setOutcome(SCRIPT, 1, "Knows us.");
    script = setOutcome(script, 2, "Closed.");
    const inserted = addScenario(script, 1, { newStep: true }).script;
    expect(outcomeOf(inserted, 1)).toBe("");
    expect(outcomeOf(inserted, 2)).toBe("Knows us.");
    expect(outcomeOf(inserted, 3)).toBe("Closed.");
    const closed = deleteScenario(script, "remind");
    expect(closed.step_outcomes).toEqual([{ step: 1, outcome: "Closed." }]);
    expect(setOutcome(script, 1, "  ").step_outcomes).toEqual([{ step: 2, outcome: "Closed." }]);
    expect("step_outcomes" in setOutcome(SCRIPT, 1, "")).toBe(false);
  });
});
