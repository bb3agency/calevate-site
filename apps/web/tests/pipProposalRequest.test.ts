import { describe, expect, it } from "vitest";

import { requestLines } from "@/app/c/[slug]/agents/[agentId]/script/PipProposal";

describe("the request above a suggestion", () => {
  it("puts each numbered point on its own line", () => {
    expect(requestLines("Rewrite the script: 1. Opening Line: keep it short. 2. Step 1: ask first. 3. Style: short.")).toBe(
      "Rewrite the script:\n1. Opening Line: keep it short.\n2. Step 1: ask first.\n3. Style: short.",
    );
  });

  it("leaves a plain request and a decimal alone", () => {
    expect(requestLines("Make the opening warmer, about 1.5 seconds shorter.")).toBe(
      "Make the opening warmer, about 1.5 seconds shorter.",
    );
  });
});
