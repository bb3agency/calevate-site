import { describe, expect, it } from "vitest";

import { joinOpening, splitOpening } from "@/app/c/[slug]/agents/[agentId]/script/HandWritten";

describe("a hand-written script's opening line in its own box (A-22)", () => {
  it("round-trips the line and the brief, with no heading for the owner to type", () => {
    const raw = joinOpening("Hello, how can I help?", "You answer calls.\nBe brief.");
    expect(raw).toBe("You answer calls.\nBe brief.\n\n[OPENING]\nHello, how can I help?");
    expect(splitOpening(raw)).toEqual({ opening: "Hello, how can I help?", rest: "You answer calls.\nBe brief." });
  });

  it("keeps what the owner is typing: a trailing space or a new last line", () => {
    expect(splitOpening(joinOpening("Hello ", "Brief\n"))).toEqual({ opening: "Hello ", rest: "Brief\n" });
  });

  it("writes no heading for an empty line and reads none from a text without it", () => {
    expect(joinOpening("  ", "Brief")).toBe("Brief");
    expect(splitOpening("Brief")).toEqual({ opening: "", rest: "Brief" });
  });
});
