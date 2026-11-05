import { describe, expect, it } from "vitest";

import { sentLine } from "@/app/c/[slug]/knowledge/CallInstructions";

describe("Use in call scripts says what was sent (A-11)", () => {
  it("never says a suggestion is coming when nothing was sent", () => {
    expect(sentLine({ agents: 0, skipped: 2 })).toBe("Not sent to any agent. See their Script pages.");
    expect(sentLine({ agents: 0, skipped: 1 }, "Varsha")).toBe("Not sent to Varsha. See its Script page.");
  });

  it("counts the agents sent to and the ones skipped", () => {
    expect(sentLine({ agents: 2, skipped: 0 })).toBe("Sent to 2 agents. Suggestion soon.");
    expect(sentLine({ agents: 2, skipped: 1 })).toBe("Sent to 2 agents. Suggestion soon. 1 not sent.");
    expect(sentLine({ agents: 1, skipped: 0 }, "Varsha")).toBe("Suggestion on Varsha's Script page soon");
  });
});
