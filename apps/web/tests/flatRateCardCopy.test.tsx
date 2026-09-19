import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage from "@/app/pricing/page";
import { WhatCallsCost } from "@/app/c/[slug]/billing/WhatCallsCost";
import type { TierLabels } from "@/app/c/[slug]/billing/lots";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import type { PublicRateCard } from "@/lib/api/rateCard";

import { RATE_CARD } from "./fixtures/rateCard";
import { stubApi } from "./harness";

/**
 * A CARD WHOSE CHEAPER VOICE DOES NOT FALL WITH VOLUME, RENDERED EVERYWHERE THAT NARRATES
 * THE LADDER.
 *
 * ⚠ This is not a hypothetical shape. The founder's 14 Sep 2026 decision
 * (`docs/PIPECAT-MIGRATION.md` §12) is **Clear ₹4.00 flat at every rung**, Studio ₹7.00
 * down to ₹5.50; `PACK_CATALOGUE` still carries the old falling card, and §6 step 16
 * applies it. So the day that one catalogue edit lands, every surface below renders
 * against a flat Clear column — and three of them narrate the ladder in prose that only
 * reads correctly when it falls.
 *
 * `/pricing` already solved this once. `bandSentence` there collapses to a single figure
 * when the ends are equal, and says why in its own docstring: "a ladder with one rung is
 * not a band, and 'down to ₹5.00' would be a discount described where there is none."
 * That guard is the standard; this suite holds the other copies of the same sentence to
 * it, so the card edit is a card edit and not a copy hunt.
 *
 * The bans are on the SHAPE, not the wording. What may not appear is a rate quoted as
 * falling to itself — a discount advertised where the card grants none.
 */
const FLAT_CLEAR: PublicRateCard = {
  ...RATE_CARD,
  list_rate_inr_per_min: "4.0000",
  from_inr_per_min: "4.0000",
  from_clear_inr_per_min: "4.0000",
  from_studio_inr_per_min: "5.5000",
  packs: RATE_CARD.packs.map((pack, index) => ({
    ...pack,
    clear_inr_per_min: "4.0000",
    // ₹7.00 down in even ₹0.30 steps, the interpolation the decision records.
    studio_inr_per_min: (7 - index * 0.3).toFixed(4),
  })),
};

const LABELS: TierLabels = { clear: "Clear", studio: "Studio" };

/** Every "₹4.00 … down to … ₹4.00" shape, however the sentence is punctuated between. */
const FALLS_TO_ITSELF = /₹4\.00[^₹]{0,80}?(down to|coming down)[^₹]{0,40}₹4\.00/i;

describe("a rate card whose cheaper voice is flat", () => {
  it("does not tell a signed-in client their flat rate comes down on the largest pack", () => {
    const { container } = render(<WhatCallsCost card={FLAT_CLEAR} labels={LABELS} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(FALLS_TO_ITSELF);
    // The voice that DOES still fall keeps its band — the guard must not flatten both.
    expect(text).toContain("₹5.50");
  });

  it("does not advertise a pack discount the ROI calculator's own card does not grant", () => {
    const { container } = render(<RoiCalculator rateCard={FLAT_CLEAR} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(FALLS_TO_ITSELF);
  });

  it("does not headline /pricing with a rate that comes down when one of the two does not", async () => {
    stubApi({ "/v1/public/rate-card": FLAT_CLEAR });
    const { container } = render(await PricingPage());
    const text = container.textContent ?? "";
    expect(text).not.toMatch(FALLS_TO_ITSELF);
    expect(text).not.toMatch(/the rate comes down as the pack gets bigger/i);
  });
});
