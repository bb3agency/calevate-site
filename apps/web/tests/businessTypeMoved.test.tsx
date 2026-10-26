import { describe, expect, it } from "vitest";

import { replacedSentence } from "@/app/admin/tenants/[tenantId]/profile/BusinessTypeMoved";

/**
 * The operator's answer after "Use the <type> details". It is built from the server's
 * counts, so an account with no agents, or one whose agents already had the set, is not
 * told that "0 agents now write" anything.
 */
describe("replacedSentence", () => {
  it("counts the agents that moved", () => {
    expect(replacedSentence({ agents_changed: 1, agents_unchanged: 0 }, "retail")).toBe(
      "1 agent now writes down the retail details. Answers already captured keep their old names.",
    );
    expect(replacedSentence({ agents_changed: 3, agents_unchanged: 1 }, "retail")).toMatch(
      /^3 agents now write down the retail details\./,
    );
  });

  it("says nothing changed when every agent already had the set", () => {
    expect(replacedSentence({ agents_changed: 0, agents_unchanged: 2 }, "retail")).toBe(
      "Every agent already writes down the retail details. Nothing changed.",
    );
  });

  it("says there are no agents rather than a zero count", () => {
    const sentence = replacedSentence({ agents_changed: 0, agents_unchanged: 0 }, "retail");
    expect(sentence).not.toMatch(/^0 /);
    expect(sentence).toBe(
      "This account has no agents yet. A new agent starts with the retail details.",
    );
  });
});
