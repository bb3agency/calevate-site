import { describe, expect, it } from "vitest";

import { compareRates, rateDifference } from "@/lib/llmRates";

/**
 * The arithmetic behind the model picker's price column — hard rule 7 at its narrowest.
 *
 * Every figure this module produces is shown to a client deciding what to pay per minute,
 * and the obvious implementation is wrong in a way no type checker sees:
 *
 *     Number("0.4830") - Number("0.2400") === 0.24300000000000002
 *
 * That is the whole subject. The tests below are the shapes an actual price list produces
 * — different scales, a zero difference, a value that is zero written three ways — plus
 * the two REFUSALS, because "we cannot compare these" is a state the picker renders and
 * therefore a state this module has to be able to return.
 */

describe("comparing two per-minute rates", () => {
  it("does not go through a float", () => {
    // The exact case above. A float implementation returns 0.24300000000000002 here.
    expect(rateDifference("0.4830", "0.2400")).toBe("0.2430");
  });

  it("answers at the finer of the two precisions", () => {
    // A four-decimal rate against a two-decimal one keeps four: rounding the answer to
    // the coarser side is the same defect as rounding the inputs.
    expect(rateDifference("0.24", "0.2385")).toBe("0.0015");
    expect(rateDifference("1", "0.25")).toBe("0.75");
  });

  it("is symmetric, because the direction is a separate question", () => {
    // `compareRates` says which way; this says by how much. Returning a negative number
    // would leave a caller rendering "₹-0.24 more a minute".
    expect(rateDifference("0.2400", "0.4830")).toBe("0.2430");
    expect(compareRates("0.2400", "0.4830")).toBe("cheaper");
    expect(compareRates("0.4830", "0.2400")).toBe("dearer");
  });

  it("reads every spelling of the same price as the same price", () => {
    expect(compareRates("0.24", "0.2400")).toBe("same");
    expect(compareRates("0.2400", "0.24")).toBe("same");
    expect(compareRates("00.240", ".24")).toBe("same");
    expect(rateDifference("0.24", "0.2400")).toBe("0.0000");
  });

  it("compares by value and not by string length", () => {
    // "9" > "10" lexicographically. Both operands are padded to a common width first.
    expect(compareRates("9.00", "10.00")).toBe("cheaper");
    expect(compareRates("0.9", "0.10")).toBe("dearer");
    expect(rateDifference("10.00", "9.00")).toBe("1.00");
  });

  it("says it cannot compare, rather than guessing, when a rate is missing", () => {
    // The catalogue does not price a withdrawn model, and an older API prices nothing.
    // "same price" over an absent figure is the §52 defect applied to money.
    expect(compareRates(null, "0.24")).toBe("unknown");
    expect(compareRates("0.24", undefined)).toBe("unknown");
    expect(compareRates("free", "0.24")).toBe("unknown");
    expect(compareRates("", "0.24")).toBe("unknown");
    expect(rateDifference(null, "0.24")).toBeNull();
    expect(rateDifference("₹0.24", "0.24")).toBeNull();
  });

  it("refuses a difference it could not compute exactly", () => {
    // 20 digits of rupees is not a price anybody quotes; what matters is that the integer
    // read stops being exact above 2^53 and this returns nothing instead of a wrong
    // figure. `compareRates` still answers, because it never parses.
    const huge = "99999999999999999999.0000";
    expect(rateDifference(huge, "0.2400")).toBeNull();
    expect(compareRates(huge, "0.2400")).toBe("dearer");
  });
});
