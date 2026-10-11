import { describe, expect, it } from "vitest";

import { noteFor } from "@/app/c/[slug]/agents/[agentId]/script/ImprovementReview";
import { applyChanges, diffScripts } from "@/app/c/[slug]/agents/[agentId]/script/scriptDiff";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage, type Improvement } from "@/lib/api/script";

/**
 * "Improve my agent" (D-724). The proposal is listed against the script it was made from,
 * so an edit the owner made since is never offered back as a change, and each listed change
 * carries the reason and the test it fixes.
 */

function stage(id: string, name: string, instruction = `Do ${name}`): ConversationStage {
  return { id, name, mode: "guide", instruction, sounds_like: "", branches: [], otherwise: "", collect: [], position: null };
}

const base: CallScript = { ...EMPTY_SCRIPT, schema_version: 2, stages: [stage("s1", "Greet"), stage("s2", "Price")] };
const proposal: CallScript = {
  ...base,
  stages: [stage("s1", "Greet"), stage("s2", "Price", "Give the price from the pinned facts.")],
  objections: [{ objection: "Not interested", response: "సరే అండి, thanks." }],
};

function improvement(): Improvement {
  return {
    script: proposal,
    base_script: base,
    base: "draft",
    changes: [
      { target: "step:s2", because: "k1", why: "Use the pinned price." },
      { target: "objections", because: "k2", why: "Let them go politely." },
    ],
    facts: [],
    for_keys: ["k1", "k2"],
    disclosure: null,
    created_at: "2026-10-11T00:00:00Z",
  };
}

describe("improvement review", () => {
  it("lists only the AI's changes and ties each to its reason", () => {
    const changes = diffScripts(base, proposal);
    expect(changes.map((c) => c.id).sort()).toEqual(["change:s2", "part:objections"]);
    expect(noteFor(changes.find((c) => c.id === "change:s2")!, improvement())?.because).toBe("k1");
    expect(noteFor(changes.find((c) => c.id === "part:objections")!, improvement())?.why).toBe("Let them go politely.");
  });

  it("keeps an edit the owner made after the proposal", () => {
    const ownerEdited: CallScript = { ...base, opening_line: "నమస్కారం అండి" };
    const kept = new Set(diffScripts(base, proposal).map((c) => c.id));
    const next = applyChanges(ownerEdited, proposal, kept);
    expect(next.opening_line).toBe("నమస్కారం అండి");
    expect(next.objections).toEqual(proposal.objections);
    expect(next.stages?.find((s) => s.id === "s2")?.instruction).toBe("Give the price from the pinned facts.");
  });

  it("applies nothing that was left unticked", () => {
    const next = applyChanges(base, proposal, new Set(["part:objections"]));
    expect(next.stages?.find((s) => s.id === "s2")?.instruction).toBe("Do Price");
  });
});
