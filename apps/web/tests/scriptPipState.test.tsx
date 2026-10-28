import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScriptBuilder } from "@/app/c/[slug]/agents/[agentId]/script/ScriptBuilder";
import type { Me } from "@/lib/api/client";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut, type ScriptProposal } from "@/lib/api/script";
import { useCopilotSurfaceHolder, type SurfaceHolder } from "@/lib/copilot/registry";
import { keepingOnWire } from "@/lib/copilot/keeping";

import { noContent, renderClientPage } from "./harness";
import { agentRow, settledPending } from "./fixtures/sharedReads";

/**
 * What Pip reads about the Script tab after the owner keeps its suggestion (D-832).
 *
 * The founder's report, 19 Oct 2026: the owner added Pip's whole-script suggestion to the
 * draft, the draft saved, and Pip, whose last word in the conversation was "I am drafting
 * it", went on as if nothing had happened. Pip learns the present only from the screen's
 * facts, so these pin that the facts change when the suggestion is kept and the draft saves.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sunrise Organics", slug: "acme", status: "active" },
};

const SCRIPT: CallScript = { ...EMPTY_SCRIPT, opening_line: "Namaskaram andi.", business_line: "An organic shop" };

const OUT: ScriptOut = {
  script: SCRIPT,
  draft: null,
  stored_schema_version: 2,
  context: null,
  version: 3,
  is_freeform: false,
  has_pending: false,
  standard_variables: [],
};

const PROPOSAL: ScriptProposal = {
  id: "p1",
  mode: "change",
  documents: [],
  status: "ready",
  request: "Make the opening line warmer",
  base_script: SCRIPT,
  script: { ...SCRIPT, opening_line: "Namaskaram andi, Sunrise Organics ki call chesinanduku thanks!" },
  unplaced: [],
  disclosure: null,
  note: null,
  requested_at: "2026-10-19T10:00:00+00:00",
};

const seen: { holder: SurfaceHolder | null } = { holder: null };
function Probe() {
  seen.holder = useCopilotSurfaceHolder();
  return null;
}

const facts = () => Object.fromEntries((seen.holder?.read().facts ?? []).map((f) => [f.key, f.value]));

describe("the Script tab tells Pip where the suggestion and the draft stand", () => {
  it("says the suggestion was added and the draft saved, once it was", async () => {
    await renderClientPage(
      <>
        <ScriptBuilder agentId="agent-1" knowledgeHref="/c/acme/knowledge" trainingHref="/c/acme/agents/agent-1" />
        <Probe />
      </>,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1": agentRow(),
        "/v1/agents/agent-1/script": OUT,
        "POST /v1/agents/agent-1/script/preview": { compiled: "x", instructions_chars: 10, instructions_limit: 8000, native_steps: 0 },
        "/v1/agents/agent-1/script/proposed-rules": [],
        "/v1/agents/agent-1/pending": settledPending(),
        "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL },
        "DELETE /v1/agents/agent-1/script/proposal/p1": noContent(),
        "PUT /v1/agents/agent-1/script/draft": { saved_at: "2026-10-19T10:05:00+00:00" },
      },
    );
    await screen.findByRole("heading", { name: "1 suggested change" });
    expect(facts().pip_suggestion).toMatch(/^Waiting on this screen for review/);

    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));

    await waitFor(() => expect(facts().pip_suggestion).toBe("None waiting. The last one was added to the draft."));
    await waitFor(
      () =>
        expect(facts().draft).toBe(
          "Saved as a draft. Changes not live yet: they go live when Put it live is pressed.",
        ),
      { timeout: 4000 },
    );
    const surface = seen.holder?.read();
    expect(surface?.fields.find((f) => f.id === "script-opening_line")?.value).toBe(PROPOSAL.script?.opening_line);
    // And the request says how this screen keeps edits, so Pip never sends the owner to a Save button.
    expect(surface && keepingOnWire(surface)).toEqual({ saves: "autosave", live_step: "Put it live" });
  });

  it("names the new file a suggestion was written from (D-923)", async () => {
    const fromFile: ScriptProposal = { ...PROPOSAL, mode: "knowledge", request: null, documents: ["prices.pdf"] };
    await renderClientPage(
      <ScriptBuilder agentId="agent-1" knowledgeHref="/c/acme/knowledge" trainingHref="/c/acme/agents/agent-1" />,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1": agentRow(),
        "/v1/agents/agent-1/script": OUT,
        "POST /v1/agents/agent-1/script/preview": { compiled: "x", instructions_chars: 10, instructions_limit: 8000, native_steps: 0 },
        "/v1/agents/agent-1/script/proposed-rules": [],
        "/v1/agents/agent-1/pending": settledPending(),
        "/v1/agents/agent-1/script/proposal": { proposal: fromFile },
      },
    );
    await screen.findByRole("heading", { name: "1 suggested change" });
    expect(screen.getByText(/From your new file: “prices.pdf”/)).toBeTruthy();
    expect(screen.queryByText(/You asked/)).toBeNull();
  });
});
