import { describe, expect, it } from "vitest";

import { keptEdits, skippedNote } from "@/app/c/[slug]/agents/[agentId]/script/ImprovementReview";
import type { Improvement } from "@/lib/api/script";

/**
 * "Improve my agent" (D-724, small edits since D-823). Each suggestion is one edit with its own
 * tick box; the kept ones go to the server in the order they were suggested, and an edit that
 * no longer fits the owner's copy is named rather than silently lost.
 */

function improvement(): Improvement {
  return {
    base: "draft",
    edits: [
      { id: "e1", op: "set_step", label: "Step “Price”", before: "Do Price", after: "Give the pinned price.", because: "k1", why: "Use the pinned price." },
      { id: "e2", op: "set_objection", label: "When a caller says “Not interested”", before: "", after: "సరే అండి, thanks.", because: "k2", why: "Let them go politely." },
      { id: "e3", op: "set_part", label: "How it ends the call", before: "", after: "Thank them.", because: null, why: "x" },
    ],
    facts: [],
    for_keys: ["k1", "k2"],
    disclosure: null,
    created_at: "2026-10-18T00:00:00Z",
  };
}

describe("improvement review", () => {
  it("sends only the ticked edits, in the order suggested", () => {
    expect(keptEdits(improvement(), new Set(["e3", "e1"]))).toEqual(["e1", "e3"]);
    expect(keptEdits(improvement(), new Set())).toEqual([]);
  });

  it("names an edit that no longer fits instead of dropping it silently", () => {
    expect(skippedNote([], improvement())).toBeNull();
    expect(skippedNote(["e1"], improvement())).toBe(
      "One change no longer fits your script, so it was left out: Step “Price”. The part it changed was removed or edited since.",
    );
    expect(skippedNote(["e1", "e2"], improvement())).toMatch(
      /^2 changes no longer fit your script, so they were left out: .* The parts they changed were removed/,
    );
  });
});
