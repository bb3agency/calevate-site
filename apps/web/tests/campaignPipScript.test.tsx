import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CampaignWorkspace, scriptAsk } from "@/app/c/[slug]/campaigns/CampaignWorkspace";
import type { CampaignProposal } from "@/lib/api/campaignWorkspace";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

import {
  FIXTURE_AGENT_ID,
  FIXTURE_CAMPAIGN_ID,
  scriptVersionsFixture,
  settingsFixture,
  workspaceFixture,
} from "./campaignFixtures";
import { noReply, problem, renderClientPage, type ApiCall, type Routes } from "./harness";

/**
 * Pip's campaign script from Generate to a kept script (D-1004): the owner's tone and note go
 * with Generate, a campaign with no sources says so with a button to pick them, a used-up
 * allowance points to the page that changes it, each part Pip wrote has its reason behind
 * "Why?", and a part of a kept script is rewritten with the owner's own instruction.
 */

const base = `/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`;
const SOURCE_ID = "0192f0aa-5555-7000-8000-000000000001";

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Hello {{lead_name}}, this is Sunrise Homes about your plot enquiry. Can you talk now?",
};

function ready(over: Partial<CampaignProposal> = {}): CampaignProposal {
  return {
    id: "0192f0aa-6666-7000-8000-000000000001",
    status: "ready",
    requested_at: "2026-11-16T04:00:00Z",
    base_script: null,
    script: SCRIPT,
    note: null,
    disclosure: null,
    left_out: [],
    reason: null,
    fixes: null,
    why: { opening_line: "Says who calls and why, then asks to talk, as your main task asks." },
    ...over,
  };
}

const routes = (extra: Routes = {}): Routes => ({
  [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID] }),
  [`${base}/settings`]: settingsFixture(),
  [`${base}/script/versions`]: scriptVersionsFixture(),
  "/v1/kb/notes": { notes: [] },
  "/v1/kb/uploads": [],
  // The call flow's voice bar lists the account's agents.
  "/v1/agents": [],
  // Who may hear a line in the agent's voice: not what these tests are about.
  "/v1/me": noReply(),
  ...extra,
});

const render = (extra: Routes = {}) =>
  renderClientPage(<CampaignWorkspace campaignId={FIXTURE_CAMPAIGN_ID} canWrite />, routes(extra));

const posted = (calls: ApiCall[]) =>
  calls.filter((c) => c.method === "POST" && c.path === `${base}/script/proposal`).map((c) => JSON.parse(c.body ?? "null") as unknown);

describe("Pip writing a campaign's script", () => {
  it("builds the request from the owner's choices, and nothing when they made none", () => {
    expect(scriptAsk({ tone: "", note: "  " })).toBeUndefined();
    expect(scriptAsk({ tone: "warm", note: " Keep it short. " })).toEqual({ tone: "warm", instruction: "Keep it short." });
  });

  it("sends the tone and the note with Generate", async () => {
    const rendered = await render({ [`POST ${base}/script/proposal`]: ready({ status: "drafting", script: null }) });
    fireEvent.change(await screen.findByLabelText("Tone"), { target: { value: "respectful" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a note for Pip" }));
    fireEvent.change(screen.getByLabelText("Note for Pip"), { target: { value: "Say the price only when asked." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() =>
      expect(posted(rendered.calls)).toEqual([{ tone: "respectful", instruction: "Say the price only when asked." }]),
    );
  });

  it("takes a long note in a box that grows, counts what is left, and sends it whole", async () => {
    const rendered = await render({ [`POST ${base}/script/proposal`]: ready({ status: "drafting", script: null }) });
    fireEvent.click(await screen.findByRole("button", { name: "Add a note for Pip" }));
    const box = screen.getByLabelText("Note for Pip");
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.getAttribute("maxLength")).toBe("2000");
    const note = "The agent is Priya from Sunrise Homes. Keep the words EMI and loan in English. ".repeat(11).trim();
    expect(note.length).toBeGreaterThan(800);
    fireEvent.change(box, { target: { value: note } });
    expect(screen.getByText(`${2000 - note.length} characters left`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(posted(rendered.calls)).toEqual([{ instruction: note }]));
  });

  it("keeps Generate open when the sources list did not load", async () => {
    const down = problem(503, { title: "This did not load", status: 503, retryable: true });
    const rendered = await render({
      "/v1/kb/notes": down,
      "/v1/kb/uploads": down,
      [`POST ${base}/script/proposal`]: ready({ status: "drafting", script: null }),
    });
    const generate = await screen.findByRole("button", { name: "Generate" });
    await waitFor(() => expect(rendered.calls.some((c) => c.path === "/v1/kb/notes")).toBe(true));
    expect(generate.hasAttribute("disabled")).toBe(false);
    fireEvent.click(generate);
    await waitFor(() => expect(posted(rendered.calls)).toHaveLength(1));
  });

  it("says when no sources are picked, with a button to pick them", async () => {
    await render({ [`${base}/workspace`]: workspaceFixture() });
    expect(await screen.findByText("No sources picked. Pip uses only the main task.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pick sources" })).toBeTruthy();
  });

  it("points a used-up allowance to the AI allowance page", async () => {
    await render({
      [`POST ${base}/script/proposal`]: problem(402, {
        type: "https://calevate.tech/problems/ai_quota_exceeded",
        title: "AI allowance used up",
        status: 402,
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Generate" }));
    expect(await screen.findByText("Your AI allowance is used up")).toBeTruthy();
    expect(screen.getByRole("link", { name: "See AI allowance" })).toBeTruthy();
  });

  it("shows Pip's reason for a part behind Why?", async () => {
    await render({ [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID], proposal: ready() }) });
    const why = await screen.findByRole("button", { name: "Why Pip wrote Opening line" });
    expect(screen.queryByText(/as your main task asks/)).toBeNull();
    fireEvent.click(why);
    expect(why.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Says who calls and why, then asks to talk, as your main task asks.")).toBeTruthy();
  });

  it("keeps Pip's draft in the one save, which settles the draft too", async () => {
    const draft = ready();
    const rendered = await render({
      [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID], proposal: draft }),
      [`PUT ${base}/script`]: workspaceFixture({ source_ids: [SOURCE_ID], script: SCRIPT }),
      [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
    });
    fireEvent.click(await screen.findByRole("button", { name: /to my draft/ }));
    await waitFor(() => expect(rendered.calls.some((c) => c.method === "PUT")).toBe(true));
    const saved = rendered.calls.filter((c) => c.method === "PUT" && c.path === `${base}/script`);
    expect(saved).toHaveLength(1);
    expect(JSON.parse(saved[0]?.body ?? "null")).toMatchObject({ proposal_id: draft.id });
    expect(rendered.calls.some((c) => c.method === "DELETE")).toBe(false);
  });

  it("reads the workspace again when a save is refused after it was stored", async () => {
    const rendered = await render({
      [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID], proposal: ready() }),
      [`PUT ${base}/script`]: problem(503, {
        type: "https://calevate.tech/problems/engine_unavailable",
        title: "Saved, but not on its calls yet",
        status: 503,
        detail: "The calling platform did not answer.",
      }),
      [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
    });
    const reads = () => rendered.calls.filter((c) => c.method === "GET" && c.path === `${base}/workspace`).length;
    fireEvent.click(await screen.findByRole("button", { name: /to my draft/ }));
    const before = reads();
    expect(await screen.findByText("Saved, but not on its calls yet")).toBeTruthy();
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
  });

  it("rewrites one part of a kept script with the owner's own instruction", async () => {
    const rendered = await render({
      [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID], script: SCRIPT }),
      [`POST ${base}/script/proposal`]: ready({ status: "drafting", script: null }),
      // The call flow's step names: not what this test is about.
      [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit script" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ask Pip to change Opening line" }));
    const box = screen.getByLabelText("What should Pip change in Opening line?");
    const rewrite = screen.getByRole("button", { name: "Rewrite" });
    expect((rewrite as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box, { target: { value: "Make it warmer." } });
    fireEvent.click(rewrite);
    await waitFor(() =>
      expect(posted(rendered.calls)).toEqual([{ part: "Opening line", language: "te-IN", instruction: "Make it warmer." }]),
    );
  });

  it("says why a part's rewrite was refused", async () => {
    const rendered = await render({
      [`${base}/workspace`]: workspaceFixture({ source_ids: [SOURCE_ID], script: SCRIPT }),
      [`POST ${base}/script/proposal`]: problem(409, {
        type: "https://calevate.tech/problems/campaign_script_busy",
        title: "Pip is already writing",
        status: 409,
        detail: "Pip is still writing this campaign's script.",
      }),
      [`/v1/agents/${FIXTURE_AGENT_ID}/script`]: noReply(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Edit script" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ask Pip to change Opening line" }));
    fireEvent.change(screen.getByLabelText("What should Pip change in Opening line?"), {
      target: { value: "Make it warmer." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Rewrite" }));
    expect(await screen.findByText("Pip is still writing this campaign's script.")).toBeTruthy();
    expect(posted(rendered.calls)).toEqual([{ part: "Opening line", language: "te-IN", instruction: "Make it warmer." }]);
  });
});
