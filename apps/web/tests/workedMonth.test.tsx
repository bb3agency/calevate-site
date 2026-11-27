import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage from "@/app/pricing/page";
import { WhatCallsCost } from "@/app/c/[slug]/billing/WhatCallsCost";
import type { PublicRateCard } from "@/lib/api/rateCard";
import { workedMonthLines } from "@/lib/workedMonth";

import { RATE_CARD } from "./fixtures/rateCard";
import { stubApi } from "./harness";

/**
 * The all-in worked month (W9.1): every rupee in it is a string the server priced, shown to
 * the paisa, and a month without an attested number price never claims "nothing added".
 *
 * The figures below are deliberately not the real card's: a page that typed the real
 * month into its copy would still fail, because these strings are the only ones on screen.
 */
const LABELS = { clear: "Clear", studio: "Studio" };

const ALL_IN: PublicRateCard = {
  ...RATE_CARD,
  voice_not_offered: null,
  voice_not_offered_notice: null,
  number_inr_per_month: "321.45",
  worked_month: {
    minutes: 3000,
    numbers: 1,
    number_inr_per_month: "321.45",
    platform_fee_inr_per_month: null,
    registered_buyer_note: RATE_CARD.worked_month.registered_buyer_note,
    voices: [
      { voice: "clear", pack_id: "plus", inr_per_min: "4.00", talk_inr: "12000.00", total_inr: "12321.45", all_in_inr_per_min: "4.11" },
      { voice: "studio", pack_id: "pro", inr_per_min: "5.80", talk_inr: "17400.00", total_inr: "17721.45", all_in_inr_per_min: "5.91" },
    ],
  },
};

describe("the worked month", () => {
  it("says the server's total to the paisa, with the number in it", () => {
    const month = ALL_IN.worked_month!;
    const lines = workedMonthLines(month, month.voices[0], LABELS);
    expect(lines.headline).toBe("A month of 3,000 minutes on Clear: ₹12,321.45, nothing added");
    expect(lines.breakdown).toBe(
      "₹12,000.00 of talk time at ₹4.00 a minute, one phone number at ₹321.45. That is ₹4.11 a minute with everything in it.",
    );
  });

  it("names the platform fee when one is charged", () => {
    const month = { ...ALL_IN.worked_month!, platform_fee_inr_per_month: "999.00" };
    expect(workedMonthLines(month, month.voices[0], LABELS).breakdown).toContain("and the ₹999.00 monthly platform fee");
  });

  it("never says 'nothing added' while the number price is unknown", () => {
    const month = RATE_CARD.worked_month;
    const lines = workedMonthLines(month, month.voices[0], LABELS);
    expect(lines.headline).toBe("A month of 3,000 minutes on Studio: ₹17,400.00 of talk time");
    expect(lines.headline).not.toMatch(/nothing added/);
    expect(lines.breakdown).toBe(
      "That is ₹5.80 a minute. Your phone number's monthly fee is added to it, and shown before you buy the number.",
    );
  });

  it("is on /pricing for every offered voice, with the GST-registered sentence", async () => {
    stubApi({ "/v1/public/rate-card": ALL_IN });
    const { container } = render(await PricingPage());
    const section = container.querySelector("#worked-month");
    const text = section?.textContent ?? "";
    expect(text).toContain("A month of 3,000 minutes on Clear: ₹12,321.45, nothing added");
    expect(text).toContain("A month of 3,000 minutes on Studio: ₹17,721.45, nothing added");
    expect(text).toContain(ALL_IN.worked_month!.registered_buyer_note);
    expect(text).toMatch(/an example, not a quote/i);
    // No figure in the section the server did not send.
    const sent = ["₹12,321.45", "₹12,000.00", "₹4.00", "₹4.11", "₹321.45", "₹17,721.45", "₹17,400.00", "₹5.80", "₹5.91"];
    for (const figure of text.match(/₹[\d,]+(\.\d+)?/g) ?? []) expect(sent).toContain(figure);
  });

  it("is absent from /pricing when the card carries none", async () => {
    stubApi({ "/v1/public/rate-card": { ...ALL_IN, worked_month: null } });
    const { container } = render(await PricingPage());
    expect(container.querySelector("#worked-month")).toBeNull();
  });

  it("leads 'What calls cost' in the console, with the no-per-message line and the worked step", () => {
    render(<WhatCallsCost card={ALL_IN} labels={LABELS} />);

    expect(screen.getByText(/A month of 3,000 minutes on Studio: ₹17,721\.45, nothing added/)).toBeTruthy();
    expect(screen.getByText("No charge per AI message")).toBeTruthy();
    expect(screen.getByText(/Calls are billed in 30-second steps/)).toBeTruthy();
  });
});
