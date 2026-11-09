import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage from "@/app/pricing/page";
import RoiPage from "@/app/roi/page";
import { WhatCallsCost } from "@/app/c/[slug]/billing/WhatCallsCost";
import type { TierLabels } from "@/app/c/[slug]/billing/lots";
import { RateCard } from "@/components/marketing/rateCard";
import { RoiCalculator } from "@/components/marketing/roiCalculator";
import { headlineVoice, type PublicRateCard } from "@/lib/api/rateCard";
import { formatINR } from "@/lib/numberDisplay";

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
  "Not open on your account yet. Credit you buy today keeps its rate, and moving an agent " +
  "onto it later costs nothing.";

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

  it("opens the public rate card on the voice the headline quotes, both ways round", () => {
    const CLEAR_HELD_BACK: PublicRateCard = {
      ...RATE_CARD,
      voice_not_offered: "clear",
      voice_not_offered_notice: HELD_BACK_NOTICE,
    };
    const cases: [PublicRateCard, string][] = [
      [STUDIO_HELD_BACK, "Clear voice"],
      [CLEAR_HELD_BACK, "Studio voice"],
    ];
    for (const [card, opens] of cases) {
      const { unmount } = render(<RateCard card={card} />);
      expect((screen.getByLabelText(opens) as HTMLInputElement).checked).toBe(true);
      unmount();
    }
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

/**
 * The ROI calculator's "from" figure and its working follow the card too. They named Studio
 * as the voice the comparison opens on and Clear as the one that cannot be chosen, whatever
 * the card said, so a deployment holding Studio back quoted Studio's figure and told a buyer
 * the voice it sells was unavailable.
 */
describe("the ROI calculator's own words about which voice it prices", () => {
  const BOTH_OPEN: PublicRateCard = {
    ...RATE_CARD,
    voice_not_offered: null,
    voice_not_offered_notice: null,
  };

  function voiceLegend(container: HTMLElement): string {
    const legend = Array.from(container.querySelectorAll("legend")).find((l) =>
      (l.textContent ?? "").startsWith("Which voice"),
    );
    return legend?.textContent ?? "";
  }

  it("leads with the from figure of a voice that can be bought", () => {
    const { container } = render(<RoiCalculator rateCard={STUDIO_HELD_BACK} />);
    expect(voiceLegend(container)).toBe(
      `Which voice your agents use — priced from ${formatINR(STUDIO_HELD_BACK.from_clear_inr_per_min)}/min`,
    );
  });

  it("leads with the cheaper voice's from figure when both can be bought", () => {
    const { container } = render(<RoiCalculator rateCard={BOTH_OPEN} />);
    expect(voiceLegend(container)).toBe(
      `Which voice your agents use — priced from ${formatINR(BOTH_OPEN.from_clear_inr_per_min)}/min`,
    );
  });

  it("says the held-back voice cannot be chosen, and only that one", () => {
    const { container } = render(<RoiCalculator rateCard={STUDIO_HELD_BACK} />);
    const text = container.textContent ?? "";
    expect(text).toContain("our published list rate on the Clear voice");
    expect(text).toContain("The Studio voice is");
    expect(text).toContain("which is why the comparison opens on the Clear voice");
    expect(text).not.toContain("opens on the Studio voice");
  });

  it("does not call a voice unavailable when the card holds none back", () => {
    const { container } = render(<RoiCalculator rateCard={BOTH_OPEN} />);
    expect(container.textContent ?? "").not.toContain("cannot be chosen at the moment");
  });

  it("names the voice that can be bought in the /roi console illustration", async () => {
    stubApi({ "/v1/public/rate-card": STUDIO_HELD_BACK });
    const { container } = render(await RoiPage());
    const text = container.textContent ?? "";
    expect(text).toContain("Clear voice (1,284.50 min)");
    expect(text).not.toContain("Studio voice (1,284.50 min)");
  });
});
