import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectionEditor } from "@/components/businessProfile/SectionEditor";
import {
  DAYS,
  blankService,
  blankStaff,
  type ProfileDraft,
  type StepId,
} from "@/lib/api/businessProfile";

/**
 * The setup wizard and the business profile both draw their placeholders from
 * `verticalExamples`, so a business that is not a clinic never reads clinic examples.
 */

const CLINICAL = /doctor|patient|dentist|dental|consultation|clinic|hospital|appointment/i;

function draft(): ProfileDraft {
  return {
    business_hours: DAYS.map((day) => ({ day, opens: "", closes: "", closed: false })),
    branches: [],
    services: [blankService()],
    faqs: [],
    staff: [blankStaff()],
    booking_rules: "",
    escalation_contacts: [],
    languages: [],
  };
}

function placeholders(step: StepId, vertical: string | null): string[] {
  const { container } = render(
    <SectionEditor
      step={step}
      draft={draft()}
      onChange={() => undefined}
      disabled={false}
      errorAt={() => undefined}
      vertical={vertical}
    />,
  );
  return Array.from(container.querySelectorAll("input, textarea"))
    .map((el) => el.getAttribute("placeholder") ?? "")
    .filter(Boolean);
}

describe("setup placeholders follow the business type", () => {
  it.each([null, "custom", "real_estate", "insurance", "education"])(
    "%s reads no clinic words on any step",
    (vertical) => {
      for (const step of ["services", "staff", "booking"] as StepId[]) {
        const offenders = placeholders(step, vertical).filter((text) => CLINICAL.test(text));
        expect(offenders, `${String(vertical)} / ${step}`).toEqual([]);
      }
    },
  );

  it("speaks of bookings or orders when the business type is unknown", () => {
    expect(placeholders("booking", null)[0]).toMatch(/bookings or orders/);
  });

  it("shows a property office its own trade", () => {
    expect(placeholders("booking", "real_estate")[0]).toMatch(/Site visits/);
    expect(placeholders("services", "real_estate")).toContain("2 BHK, Gachibowli");
  });

  it("keeps the clinic's own examples for a clinic", () => {
    expect(placeholders("staff", "clinic")).toContain("Dr Lakshmi Prasad");
  });
});
