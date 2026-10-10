import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CreditLeft, minutesLine } from "@/components/admin/credit";

/**
 * Credit in the operator console is stated MINUTES FIRST, RUPEES SECOND (founder,
 * 10 Oct 2026), and never invents a zero: an invoiced client has no wallet, a trial has a
 * balance but no minutes figure, and a row without credit fields says nothing.
 */
const TIERS = [
  { voice_tier: "clear", label: "Clear", minutes: 240 },
  { voice_tier: "studio", label: "Studio", minutes: 80 },
];

describe("credit left", () => {
  it("puts the minutes before the rupees", () => {
    const { container } = render(
      <CreditLeft credit={{ plan_tier: "prepaid", credit_inr: "3400.00", minutes_left: TIERS }} />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Clear 240 min · Studio 80 min");
    expect(text.indexOf("240 min")).toBeLessThan(text.indexOf("₹"));
  });

  it("says Invoiced for a client with no wallet, never ₹0", () => {
    const { container } = render(
      <CreditLeft credit={{ plan_tier: "managed", credit_inr: null, minutes_left: null }} />,
    );
    expect(container.textContent).toBe("Invoiced");
  });

  it("says On trial when the balance is known but no minutes may be quoted", () => {
    const { container } = render(
      <CreditLeft credit={{ plan_tier: "prepaid", credit_inr: "50.00", minutes_left: null }} />,
    );
    expect(container.textContent).toContain("On trial");
    expect(container.textContent).toContain("₹50");
  });

  it("marks an overdrawn balance in words as well as colour", () => {
    const { container } = render(
      <CreditLeft credit={{ plan_tier: "prepaid", credit_inr: "-12.00", minutes_left: TIERS }} />,
    );
    expect(container.textContent).toContain("Overdrawn:");
  });

  it("has no minutes line without tiers", () => {
    expect(minutesLine({ plan_tier: "prepaid", credit_inr: "1.00", minutes_left: [] })).toBeNull();
  });
});
