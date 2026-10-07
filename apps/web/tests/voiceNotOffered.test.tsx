import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage from "@/app/pricing/page";
import { WhatCallsCost } from "@/app/c/[slug]/billing/WhatCallsCost";
import type { TierLabels } from "@/app/c/[slug]/billing/lots";
import { RateCard } from "@/components/marketing/rateCard";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import { headlineVoice, type PublicRateCard } from "@/lib/api/rateCard";

import { RATE_CARD } from "./fixtures/rateCard";
import { stubApi } from "./harness";

/**
 * WHICH VOICE CANNOT BE BOUGHT IS THE SERVER'S ANSWER, AND IT FOLLOWS THE ENGINE.
 *
 * On our own voices the cheaper rung (Clear) is unpriced (D-629). On ThinnestAI the
 * engine's Premium band is sold AS Clear and Studio is held back (D-681). The card carries
 * `voice_not_offered` and its sentence, and every surface that used to hard-code "Clear is
 * not available" must now say whichever the server says — or a ThinnestAI deployment tells
 * a buyer the one voice it sells cannot be chosen.
 */
const HELD_BACK_NOTICE =
  "Not available to choose yet: this voice is not open on the platform your calls run on " +
  "today, so we will not put an agent on it. Its rate is still fixed on credit you buy " +
  "today, and it costs you nothing to move an agent onto it once it opens.";

const STUDIO_HELD_BACK: PublicRateCard = {
  ...RATE_CARD,
  voice_not_offered: "studio",
  voice_not_offered_notice: HELD_BACK_NOTICE,
};

const LABELS: TierLabels = { clear: "Clear", studio: "Studio" };

describe("a deployment where Studio is held back and Clear is sold", () => {
  it("headlines the voice that can be bought", () => {
    expect(headlineVoice(STUDIO_HELD_BACK)).toBe("clear");
    expect(headlineVoice(RATE_CARD)).toBe("studio");
  });

  it("tells a signed-in client which voice is held back, by its name", () => {
    const { container } = render(<WhatCallsCost card={STUDIO_HELD_BACK} labels={LABELS} />);
    const text = container.textContent ?? "";
    expect(text).toContain(`Studio — ${HELD_BACK_NOTICE}`);
    expect(text).not.toContain("the vendor that speaks this voice changed");
  });

  it("puts the notice on the Studio panel of the public rate card and not on Clear", () => {
    render(<RateCard card={STUDIO_HELD_BACK} />);
    const notices = screen.getAllByRole("status");
    expect(notices.map((n) => n.textContent)).toEqual([HELD_BACK_NOTICE]);
  });

  it("captions Studio, not Clear, as unavailable in the ROI calculator", () => {
    const { container } = render(<RoiCalculator rateCard={STUDIO_HELD_BACK} />);
    const text = container.textContent ?? "";
    expect(text).toContain(HELD_BACK_NOTICE);
  });

  it("leads /pricing with the Clear rate", async () => {
    stubApi({ "/v1/public/rate-card": STUDIO_HELD_BACK });
    const { container } = render(await PricingPage());
    const heading = container.querySelector("h1")?.textContent ?? "";
    expect(heading).toMatch(/^Talk time on the Clear voice/);
  });
});
