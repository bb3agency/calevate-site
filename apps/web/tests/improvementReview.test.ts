import { describe, expect, it } from "vitest";

import { holderPath, scriptFixLine } from "@/app/c/[slug]/agents/[agentId]/script/ImprovementReview";
import type { Improvement } from "@/lib/api/script";

/**
 * "Improve my agent" since D-1017: script fixes are a Pip draft on the agent's Inbound line or
 * campaign, and the Training tab says where (or why there is none) in one line.
 */

function improvement(patch: Partial<Improvement> = {}): Improvement {
  return {
    script_fixes: "drafted",
    holder: { kind: "campaign", id: "camp-1", name: "Reminders" },
    edits: [
      { id: "e1", op: "set_step", label: "Step “Price”", before: "Do Price", after: "Give the pinned price.", because: "k1", why: "Use the pinned price." },
      { id: "e2", op: "set_objection", label: "When a caller says “Not interested”", before: "", after: "Thank them.", because: "k2", why: "Let them go politely." },
    ],
    facts: [],
    for_keys: ["k1", "k2"],
    disclosure: null,
    created_at: "2026-11-17T00:00:00Z",
    ...patch,
  };
}

describe("where a practice test's script fixes went", () => {
  it("names the line or campaign holding the draft, and links to its page", () => {
    expect(scriptFixLine(improvement())).toBe("2 fixes drafted on “Reminders”.");
    expect(holderPath("acme", { kind: "campaign", id: "camp-1" })).toBe("/c/acme/campaigns/camp-1");
    expect(holderPath("acme", { kind: "inbound_line", id: "line-1" })).toBe("/c/acme/inbound/line-1");
  });

  it("says why there is no draft", () => {
    expect(scriptFixLine(improvement({ script_fixes: "draft_open", edits: [] }))).toBe(
      "A Pip draft already waits on “Reminders”.",
    );
    expect(scriptFixLine(improvement({ script_fixes: "no_holder", holder: null, edits: [] }))).toMatch(/no line or campaign/);
    expect(scriptFixLine(improvement({ script_fixes: "choose", holder: null, edits: [] }))).toMatch(/^Choose where/);
    expect(scriptFixLine(improvement({ script_fixes: "none", edits: [] }))).toBeNull();
  });
});
