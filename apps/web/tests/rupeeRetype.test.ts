import { describe, expect, it } from "vitest";

import { sameRupees, typedRupees } from "@/lib/api/credits";

describe("re-keying an amount", () => {
  it("asks for the amount, not its spelling", () => {
    for (const typed of ["1000", "1000.0", "1000.00", "1,000", "₹1,000", " 1000 ", "01000"]) {
      expect(sameRupees(typed, "1000.00")).toBe(true);
    }
  });

  it("still refuses a different figure or something that is not one", () => {
    expect(sameRupees("100", "1000.00")).toBe(false);
    expect(sameRupees("1000.5", "1000.00")).toBe(false);
    expect(sameRupees("ten", "10.00")).toBe(false);
    expect(sameRupees("", "0.00")).toBe(false);
  });

  it("keeps the sign of a correction", () => {
    expect(sameRupees("-250", "-250.00")).toBe(true);
    expect(sameRupees("250", "-250.00")).toBe(false);
    expect(typedRupees("1,234.5")).toBe("1234.50");
  });
});
