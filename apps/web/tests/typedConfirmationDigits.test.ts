import { describe, expect, it } from "vitest";

import { confirmationMatches } from "@/components/typedConfirmation";

/** `n` written in Telugu digits, generated from code points rather than typed. */
const telugu = (n: number) =>
  [...String(n)].map((d) => String.fromCodePoint(0x0c66 + Number(d))).join("");

describe("a typed count confirmation", () => {
  it("accepts the count typed on a Telugu keyboard", () => {
    expect(confirmationMatches(telugu(125), "125")).toBe(true);
  });

  it("still refuses a different count, and exact matching is unchanged", () => {
    expect(confirmationMatches(telugu(124), "125")).toBe(false);
    expect(confirmationMatches(telugu(125), "125", "exact")).toBe(false);
  });
});
