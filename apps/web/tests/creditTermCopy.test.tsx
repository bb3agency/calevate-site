/**
 * THE CREDIT TERM, AS THE BILLING EXPLAINER STATES IT (D-840, Terms 6.1 revision 19).
 *
 * The founder saw "Your credit never expires … never swept" on 27 Oct 2026, after credit
 * bought in a pack started lapsing 12 months after purchase. The claim now follows the
 * card's `credit_expiry_months`, and without a card it states no term rather than a guess.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WhatCallsCost } from "@/app/c/[slug]/billing/WhatCallsCost";
import type { CreditPacks } from "@/lib/api/billing";

const CARD: CreditPacks = {
  list_rate_inr_per_min: "4.50",
  from_inr_per_min: "4.50",
  from_clear_inr_per_min: "4.50",
  from_studio_inr_per_min: "6.00",
  clear_tier_label: "Clear",
  studio_tier_label: "Studio",
  voice_not_offered: null,
  voice_not_offered_notice: null,
  packs: [],
  credit_expiry_months: 12,
};

describe("what calls cost: the credit term", () => {
  it("says credit lasts 12 months and never that it never expires", () => {
    const { container } = render(<WhatCallsCost card={CARD} labels={undefined} />);
    expect(screen.getByText("Credit you buy lasts 12 months")).toBeTruthy();
    expect(container.textContent).not.toMatch(/never expires|never swept/i);
  });

  it("states no term when the card has not loaded", () => {
    const { container } = render(<WhatCallsCost card={undefined} labels={undefined} />);
    expect(container.textContent).not.toMatch(/never expires|lasts \d+ months/i);
  });
});
