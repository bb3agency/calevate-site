import { describe, expect, it } from "vitest";

import { examplesFor, type VerticalExamples } from "@/lib/verticalExamples";

/**
 * Client setup must describe the client's trade, not a dental clinic.
 *
 * Every placeholder on the onboarding intake form named one: "Consultation", "₹500",
 * "Dr Lakshmi Prasad", "Dentist", "Do you take walk-ins?", "Slots every 20 minutes …
 * never promise a specific doctor without checking". Five verticals ship and four of them
 * are not clinics, so an operator onboarding a property office or a coaching centre was
 * being taught the wrong vocabulary by the fastest-read text on the form.
 *
 * They were `placeholder`s, never values — nothing was pre-filled and nothing could be
 * submitted unchanged. That is worth saying because it is the sharper bug and it was NOT
 * the one here; what was here is a form that instructs forty times in the wrong trade.
 */

const VERTICALS = ["clinic", "real_estate", "insurance", "education", "custom"] as const;

/** Words that belong to a clinic and to nothing else we sell to. */
const CLINICAL = /doctor|patient|dentist|dental|consultation|walk-in|clinic|prescription/i;

describe("every vertical gets its own examples", () => {
  it.each(VERTICALS)("%s fills every field", (vertical) => {
    const eg = examplesFor(vertical);
    for (const [field, value] of Object.entries(eg) as [keyof VerticalExamples, string][]) {
      expect(value.trim().length, `${vertical}.${field} is empty`).toBeGreaterThan(0);
    }
  });

  it.each(VERTICALS.filter((v) => v !== "clinic"))(
    "%s says nothing clinical",
    (vertical) => {
      const offenders = Object.entries(examplesFor(vertical))
        .filter(([, value]) => CLINICAL.test(String(value)))
        .map(([field]) => field);
      expect(
        offenders,
        `${vertical} borrowed a clinic's vocabulary — that is the bug this table exists ` +
          `to remove, and copying one row to fill another is how it comes back`,
      ).toEqual([]);
    },
  );

  it("gives each trade DIFFERENT examples rather than one set with a label", () => {
    // The cheap wrong fix is a table whose rows are all the clinic's. Compare the field
    // an operator reads first — what the business sells.
    const services = VERTICALS.map((v) => examplesFor(v).serviceName);
    expect(new Set(services).size).toBe(VERTICALS.length);
  });
});

describe("an unknown vertical", () => {
  it("falls back to the trade-neutral set, NOT to the clinic", () => {
    // The fallback is the whole point: an absent or unrecognised vertical must not
    // quietly describe a dental practice. `custom`'s examples read as instructions, so a
    // fallback looks like a fallback instead of looking like a business.
    for (const value of [null, undefined, "", "chiropractor", "toString"]) {
      expect(examplesFor(value)).toEqual(examplesFor("custom"));
      expect(CLINICAL.test(examplesFor(value).serviceName)).toBe(false);
    }
  });

  it("is not fooled by a prototype key", () => {
    // `key in table` walks the prototype chain, so `constructor` would report as present
    // and the read would yield the `Object` function. The vertical comes off the wire.
    const eg = examplesFor("constructor");
    expect(typeof eg.serviceName).toBe("string");
    expect(eg).toEqual(examplesFor("custom"));
  });
});
