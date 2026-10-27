import { describe, expect, it } from "vitest";

import {
  formatDecimal,
  formatINR,
  formatINRExact,
  formatPayableINR,
  formatPercent,
  formatRupeeRateExact,
  roundDecimalString,
} from "@/lib/numberDisplay";
import { formatPaiseINR } from "@/lib/roi";

describe("the client display rule: at most one decimal, none when whole", () => {
  it.each([
    ["6.0000", "₹6"],
    ["4.5000", "₹4.5"],
    ["4.6296", "₹4.6"],
    ["4.95", "₹5"],
    ["4.05", "₹4.1"],
    ["1234.56", "₹1,234.6"],
    ["10159.00", "₹10,159"],
    ["1234567.89", "₹12,34,567.9"],
    ["999.96", "₹1,000"],
    ["0.04", "₹0"],
    ["0", "₹0"],
    ["-1234.56", "-₹1,234.6"],
    ["-0.04", "₹0"],
  ])("formatINR(%s) is %s", (value, expected) => {
    expect(formatINR(value)).toBe(expected);
  });

  it("renders an absent figure as a dash", () => {
    expect(formatINR(null)).toBe("—");
    expect(formatINR(undefined)).toBe("—");
    expect(formatINR("")).toBe("—");
    expect(formatDecimal(null)).toBe("—");
    expect(formatPercent(null)).toBe("—");
  });

  it("rounds half-up on the digits, not on a float", () => {
    // (1.005).toFixed(2) is "1.00" in every JS engine; the digits say 1.01.
    expect(roundDecimalString("1.005", 2)).toBe("1.01");
    expect(roundDecimalString("0.15", 1)).toBe("0.2");
    expect(roundDecimalString("9.95", 1)).toBe("10");
    expect(roundDecimalString("-2.25", 1)).toBe("-2.3");
  });

  it("refuses a string that is not a decimal rather than printing NaN", () => {
    expect(() => formatINR("₹4.50")).toThrow(/not a decimal string/);
  });

  it("formats non-money figures and percentages by the same rule", () => {
    expect(formatDecimal("3.25")).toBe("3.3");
    expect(formatDecimal("40.00")).toBe("40");
    expect(formatDecimal(2.5)).toBe("2.5");
    expect(formatPercent("12.0")).toBe("12%");
    expect(formatPercent("4.25")).toBe("4.3%");
  });

  it("formats integer paise for the marketing calculator by the same rule", () => {
    expect(formatPaiseINR(520000)).toBe("₹5,200");
    expect(formatPaiseINR(462)).toBe("₹4.6");
    expect(formatPaiseINR(-12345)).toBe("-₹123.5");
  });
});

describe("the tax-document and admin exception keeps the paisa", () => {
  it("formatINRExact prints exactly two decimals", () => {
    expect(formatINRExact("6.0000")).toBe("₹6.00");
    expect(formatINRExact("1234.5")).toBe("₹1,234.50");
    expect(formatINRExact("10159")).toBe("₹10,159.00");
    expect(formatINRExact("-1234.56")).toBe("-₹1,234.56");
    expect(formatINRExact(null)).toBe("—");
  });

  it("formatRupeeRateExact keeps the server's full rate precision", () => {
    expect(formatRupeeRateExact("7.1250")).toBe("₹7.1250");
  });
});

describe("an amount someone is about to pay", () => {
  it("is plain when whole and exact when it carries paise, never rounded", () => {
    expect(formatPayableINR("50000.00")).toBe("₹50,000");
    expect(formatPayableINR("2500.10")).toBe("₹2,500.10");
    expect(formatPayableINR("2500.15")).toBe("₹2,500.15");
    expect(formatPayableINR(null)).toBe("—");
  });
});
