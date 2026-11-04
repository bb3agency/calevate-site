import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectionEditor, inSentence } from "@/components/businessProfile/SectionEditor";
import {
  DAYS,
  blankService,
  blankStaff,
  stepsFor,
  type ProfileDraft,
  type ProfileWording,
  type StepId,
} from "@/lib/api/businessProfile";

import { NEUTRAL_WORDING } from "./businessProfileFixture";

/**
 * The business profile's labels and examples are the business's own (`wording`): before
 * they are written, generic labels and no example at all; after, its words, and no price
 * column where it quotes no price.
 */

const FARM_APP: ProfileWording = {
  offer_label: "Plan",
  price_label: null,
  offers_hint: "The plans farmers can sign up for.",
  booking_title: "How do farmers sign up?",
  booking_hint: "What a farmer needs before signing up.",
  examples: {
    ...NEUTRAL_WORDING.examples,
    offer_name: "Crop records plan",
    offer_note: "First month free",
    staff_role: "Support lead",
    booking_rules: "Sign up with a mobile number.",
  },
  drafted: true,
};

function draft(services = [blankService()]): ProfileDraft {
  return {
    business_hours: DAYS.map((day) => ({ day, opens: "", closes: "", closed: false })),
    branches: [],
    services,
    faqs: [],
    staff: [blankStaff()],
    booking_rules: "",
    escalation_contacts: [],
    languages: [],
  };
}

function show(step: StepId, wording: ProfileWording, services?: ProfileDraft["services"]) {
  const { container } = render(
    <SectionEditor
      step={step}
      draft={draft(services)}
      onChange={() => undefined}
      disabled={false}
      errorAt={() => undefined}
      wording={wording}
    />,
  );
  return Array.from(container.querySelectorAll("input, textarea"))
    .map((el) => el.getAttribute("placeholder") ?? "")
    .filter(Boolean);
}

describe("a business with no wording yet", () => {
  it("reads generic labels and no example from any trade", () => {
    for (const step of ["branches", "services", "faqs", "staff", "booking"] as StepId[]) {
      expect(show(step, NEUTRAL_WORDING), step).toEqual([]);
    }
    show("services", NEUTRAL_WORDING);
    expect(screen.getAllByLabelText("Service").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText("Price (₹)").length).toBeGreaterThan(0);
  });
});

describe("a business with its own wording", () => {
  it("reads its own labels and examples", () => {
    expect(show("services", FARM_APP)).toEqual(["Crop records plan", "First month free"]);
    expect(screen.getAllByLabelText("Plan").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Add plan" })).toBeTruthy();
    expect(show("booking", FARM_APP)).toEqual(["Sign up with a mobile number."]);
    const booking = stepsFor(FARM_APP).find((step) => step.id === "booking");
    expect(booking?.title).toBe("How do farmers sign up?");
  });

  it("shows no price column where no price applies", () => {
    show("services", FARM_APP);
    expect(screen.queryByText(/\(₹\)/)).toBeNull();
  });

  it("keeps a price already on file visible", () => {
    show("services", FARM_APP, [{ name: "Crop records plan", price_inr: "99", notes: "" }]);
    expect(screen.getAllByLabelText("Price (₹)").length).toBe(1);
  });
});

describe("a label mid-sentence", () => {
  it("lowercases a word and keeps an acronym", () => {
    expect(inSentence("Plan")).toBe("plan");
    expect(inSentence("SIM plan")).toBe("SIM plan");
  });
});
