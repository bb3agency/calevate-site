import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { awaitsConfirmation, uploadState } from "@/app/c/[slug]/knowledge/uploadCopy";
import { uploadSettled, type KbUpload } from "@/lib/api/kb";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

/** The 8 Nov 2026 audit, lane B: review rows, and Knowledge rows. */

const SCRIPT: CallScript = { ...EMPTY_SCRIPT, opening_line: "Namaskaram andi.", business_line: "An organic shop" };

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
