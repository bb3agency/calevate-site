import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignWorkspace } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import { ToastProvider } from "@/components/arc/toast";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import {
  FIXTURE_AGENT_ID,
  FIXTURE_CAMPAIGN_ID,
  scriptVersionsFixture,
  settingsFixture,
  workspaceFixture,
} from "./campaignFixtures";
import { noReply, problem, renderClientPage, type Routes } from "./harness";

/**
 * Save flow says whether it worked (founder, 25 Nov 2026). The server tidies what it stores
 * (a way out written in words becomes a branch), so the saved script differs from the draft
 * sent; the Save bar must still clear, and a refusal must show beside the button.
 */

const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;

const stage = (over: Partial<ConversationStage> = {}): ConversationStage => ({
  id: "login",
  name: "Login",
  mode: "guide",
  instruction: "Ask them to log in. If they cannot, offer to call back.",
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

const routes = (put: unknown): Routes => ({
  [`${base}/workspace`]: workspaceFixture({ script: SCRIPT }),
  [`${base}/settings`]: settingsFixture(),
  [`${base}/script/versions`]: scriptVersionsFixture(),
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  "/v1/agents": [],
  "/v1/me": noReply(),
  [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
  [`PUT ${base}/script`]: put,
});

const editOutcome = async () => {
  const box = (await screen.findByLabelText("Outcome of this step, step 1")) as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: "The person is logged in." } });
};

describe("Save flow", () => {
  it("clears the unsaved changes and says Saved when the server stores a tidied script", async () => {
    const tidied: CallScript = {
      ...SCRIPT,
      step_outcomes: [{ step: 1, outcome: "The person is logged in." }],
      stages: [
        stage({ branches: [{ when: "They cannot", target: "callback" }] }),
        ...SCRIPT.stages.slice(1),
      ],
    };
    const view = await renderClientPage(
      <ToastProvider>{<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />}</ToastProvider>,
      routes(workspaceFixture({ script: tidied })),
    );
    await editOutcome();
    fireEvent.click(screen.getByRole("button", { name: "Save flow" }));
    await waitFor(() => expect(view.calls.some((c) => c.method === "PUT")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Save flow" })).toBeNull());
    expect(await screen.findByText("Saved")).toBeTruthy();
  });

  it("keeps the changes and shows why beside the button when the save is refused", async () => {
    await renderClientPage(
      <ToastProvider>{<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />}</ToastProvider>,
      routes(problem(409, { title: "The script changed meanwhile", detail: "Reload to see it." })),
    );
    await editOutcome();
    fireEvent.click(screen.getByRole("button", { name: "Save flow" }));
    expect(await screen.findAllByText("The script changed meanwhile")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Save flow" })).toBeTruthy();
  });
});
