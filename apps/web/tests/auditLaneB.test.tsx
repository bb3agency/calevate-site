import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { ScriptBuilder } from "@/app/c/[slug]/agents/[agentId]/script/ScriptBuilder";
import { awaitsConfirmation, uploadState } from "@/app/c/[slug]/knowledge/uploadCopy";
import type { Me } from "@/lib/api/client";
import { uploadSettled, type KbUpload } from "@/lib/api/kb";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut, type ScriptProposal } from "@/lib/api/script";

import { businessProfileFixture } from "./businessProfileFixture";
import { agentRow, settledPending } from "./fixtures/sharedReads";
import { noContent, renderClientPage } from "./harness";

/** The 8 Nov 2026 audit, lane B: the Script tab's Undo and review rows, and Knowledge rows. */

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
  script: { ...SCRIPT, opening_line: "Namaskaram andi, thanks for calling Sunrise Organics!" },
  unplaced: [],
  left_out: [],
  disclosure: null,
  note: null,
  requested_at: "2026-10-19T10:00:00+00:00",
};

describe("Undo after a kept suggestion (B-08)", () => {
  it("is offered only while the draft is what the suggestion made", async () => {
    await renderClientPage(
      <ScriptBuilder agentId="agent-1" knowledgeHref="/c/acme/knowledge" trainingHref="/c/acme/agents/agent-1" />,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1": agentRow(),
        "/v1/agents/agent-1/script": OUT,
        "/v1/business-profile": businessProfileFixture(),
        "POST /v1/agents/agent-1/script/preview": { compiled: "x", instructions_chars: 10, instructions_limit: 8000, native_steps: 0 },
        "/v1/agents/agent-1/script/proposed-rules": [],
        "/v1/agents/agent-1/pending": settledPending(),
        "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL },
        "DELETE /v1/agents/agent-1/script/proposal/p1": noContent(),
        "PUT /v1/agents/agent-1/script/draft": { saved_at: "2026-10-19T10:05:00+00:00" },
      },
    );
    await screen.findByRole("heading", { name: "1 suggested change" });
    fireEvent.click(screen.getByRole("button", { name: "Add it to my draft" }));
    await screen.findByRole("button", { name: "Undo" });

    // A further edit: Undo would now throw it away, so it is no longer offered.
    const opening = screen.getByRole("textbox", { name: "Opening line" });
    fireEvent.change(opening, { target: { value: "Namaskaram andi, my own words now." } });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Undo" })).toBeNull());
  });
});

describe("review rows (B-09)", () => {
  const step = (id: string, name: string, extra: Partial<CallScript["stages"][number]> = {}) => ({
    id,
    name,
    mode: "guide" as const,
    instruction: `Do the ${name.toLowerCase()} part.`,
    sounds_like: "",
    branches: [],
    otherwise: "",
    collect: [],
    position: null,
    ...extra,
  });

  it("renames a step without calling the steps that lead to it changed", () => {
    const current: CallScript = {
      ...SCRIPT,
      stages: [step("a", "Ask", { branches: [{ when: "they need help", target: "b" }] }), step("b", "Help"), step("z", "Close")],
    };
    const proposal: CallScript = {
      ...current,
      stages: current.stages.map((s) => (s.id === "b" ? { ...s, name: "Sowing help" } : s)),
    };
    render(<ProposalReview current={current} proposal={proposal} onApply={() => undefined} onDiscard={() => undefined} />);
    expect(screen.getByRole("heading", { name: "1 suggested change" })).toBeTruthy();
    expect(screen.getByText("Step renamed")).toBeTruthy();
  });
});

describe("a PDF or link waiting for review (B-11)", () => {
  const pending = (over: Partial<KbUpload>): KbUpload => ({
    read_state: "ready",
    read_detail: null,
    page_count: 2,
    reaches_agents: false,
    id: "u1",
    source_id: "s1",
    facts_count: 0,
    name: "Menu",
    source_kind: "pdf",
    ingest_status: "received",
    ingest_detail: null,
    review_state: "pending_approval",
    is_live: false,
    version: 1,
    filename: "menu.pdf",
    byte_size: 1000,
    source_url: null,
    text_provenance: null,
    change_detected_at: null,
    ...over,
  });

  it("stops polling and asks for the owner's check once its words are read", () => {
    for (const row of [pending({}), pending({ source_kind: "url", filename: null, source_url: "https://x.in" })]) {
      expect(uploadSettled(row)).toBe(true);
      expect(awaitsConfirmation(row)).toBe(true);
      expect(uploadState(row).label).toBe("Check what we read");
    }
  });

  it("is still moving while its words are being read", () => {
    const row = pending({ read_state: "reading" });
    expect(uploadSettled(row)).toBe(false);
    expect(awaitsConfirmation(row)).toBe(false);
  });
});
