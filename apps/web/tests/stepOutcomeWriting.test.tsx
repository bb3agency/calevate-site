import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignWorkspace } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import { OUTCOME_PLACEHOLDER, OUTCOME_WRITING } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { outcomeOf, setOutcome, withPipOutcomes } from "@/app/c/[slug]/campaigns/scenarioModel";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import {
  FIXTURE_AGENT_ID,
  FIXTURE_CAMPAIGN_ID,
  scriptVersionsFixture,
  settingsFixture,
  workspaceFixture,
} from "./campaignFixtures";
import { noReply, renderClientPage, type Routes } from "./harness";

/**
 * D-1036: a step's outcome is Pip's to write. An empty box never asks the owner to invent it;
 * while Pip writes, the app's loader shows beside it, and the outcome appears when written.
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
  scripts: {},
  qa: [],
  coaching: [],
  ...over,
});

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello, this is the shop.",
  stages: [stage(), stage({ id: "close", name: "Close", instruction: "Thank them.", step: 2 })],
};
const WRITTEN = "The person says they remember the shop.";

const routes = (workspace: Routes[string]): Routes => ({
  [`${base}/workspace`]: workspace,
  [`${base}/settings`]: settingsFixture(),
  [`${base}/script/versions`]: scriptVersionsFixture(),
  [`${base}/script/checks`]: { findings: [], blocks_live: false },
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  "/v1/agents": [],
  "/v1/me": noReply(),
  [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
});

const outcomeBoxes = () => screen.getAllByRole("textbox", { name: /Done when…/ }) as HTMLTextAreaElement[];

describe("a step's outcome, written by Pip", () => {
  it("never asks the owner to invent an empty one", async () => {
    renderClientPage(
      <CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      routes(workspaceFixture({ script: SCRIPT })),
    );
    await screen.findAllByRole("textbox", { name: /Done when…/ });
    for (const box of outcomeBoxes()) expect(box.placeholder).toBe(OUTCOME_PLACEHOLDER);
    expect(screen.queryByText(OUTCOME_WRITING)).toBeNull();
  });

  it("shows the loader while Pip writes, then the outcome it wrote", async () => {
    let reads = 0;
    renderClientPage(
      <CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      routes(() => {
        reads += 1;
        return reads === 1
          ? workspaceFixture({ script: SCRIPT, step_outcomes_pending: true })
          : workspaceFixture({ script: setOutcome(SCRIPT, 1, WRITTEN), step_outcomes_pending: false });
      }),
    );
    const writing = await screen.findAllByText(OUTCOME_WRITING);
    expect(writing.length).toBeGreaterThan(0);
    expect(writing[0]?.getAttribute("role")).toBe("status");
    // The owner can still type in it while Pip writes.
    expect(outcomeBoxes().every((box) => !box.readOnly)).toBe(true);

    await waitFor(() => expect(outcomeBoxes().some((box) => box.value === WRITTEN)).toBe(true), {
      timeout: 9000,
    });
    expect(screen.queryByText(OUTCOME_WRITING)).toBeNull();
  }, 15000);
});

describe("withPipOutcomes", () => {
  const before = SCRIPT;
  const after = setOutcome(setOutcome(SCRIPT, 1, WRITTEN), 2, "They are thanked.");

  it("adds what Pip wrote to the owner's unsaved draft and keeps what they typed", () => {
    const draft = setOutcome({ ...SCRIPT, goal: "Owner's unsaved goal." }, 2, "Owner's words.");
    const merged = withPipOutcomes(draft, before, after);
    expect(merged.goal).toBe("Owner's unsaved goal.");
    expect(outcomeOf(merged, 1)).toBe(WRITTEN);
    expect(outcomeOf(merged, 2)).toBe("Owner's words.");
  });

  it("follows a step the owner has moved, and leaves out one whose scenarios are gone", () => {
    const moved: CallScript = {
      ...SCRIPT,
      stages: [stage({ id: "close", name: "Close", instruction: "Thank them.", step: 1 }), stage({ step: 2 })],
    };
    const merged = withPipOutcomes(moved, before, after);
    expect(outcomeOf(merged, 2)).toBe(WRITTEN);
    expect(outcomeOf(merged, 1)).toBe("They are thanked.");

    const removed: CallScript = { ...SCRIPT, stages: [stage({ id: "other", name: "Other", step: 1 })] };
    expect(withPipOutcomes(removed, before, after).step_outcomes ?? []).toEqual([]);
  });

  it("takes Pip's rewrite where the draft still holds the outcome it replaced, never the owner's edit", () => {
    const had = setOutcome(setOutcome(SCRIPT, 1, WRITTEN), 2, "They are thanked.");
    const rewritten = setOutcome(setOutcome(had, 1, "The person says they know the shop."), 2, "The person is thanked.");
    const draft = setOutcome({ ...had, goal: "Owner's unsaved goal." }, 2, "Owner's own thanks.");
    const merged = withPipOutcomes(draft, had, rewritten);
    expect(outcomeOf(merged, 1)).toBe("The person says they know the shop.");
    expect(outcomeOf(merged, 2)).toBe("Owner's own thanks.");
  });
});

describe("giving the outcomes back to Pip", () => {
  it("is one button, asked in a dialog, that sends one request", async () => {
    const { calls } = await renderClientPage(
      <CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      {
        ...routes(workspaceFixture({ script: setOutcome(SCRIPT, 1, WRITTEN), step_outcomes_by_owner: true })),
        [`POST ${base}/script/step-outcomes/rewrite`]: workspaceFixture({
          script: setOutcome(SCRIPT, 1, WRITTEN),
          step_outcomes_pending: true,
        }),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Let Pip rewrite every “Done when…”" }));
    await screen.findByRole("dialog");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Rewrite them" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.path === `${base}/script/step-outcomes/rewrite`)).toHaveLength(1),
    );
  });

  it("is not offered while every outcome is Pip's", async () => {
    await renderClientPage(
      <CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />,
      routes(workspaceFixture({ script: setOutcome(SCRIPT, 1, WRITTEN), step_outcomes_by_owner: false })),
    );
    await screen.findAllByRole("textbox", { name: /Done when…/ });
    expect(screen.queryByRole("button", { name: "Let Pip rewrite every “Done when…”" })).toBeNull();
  });
});
