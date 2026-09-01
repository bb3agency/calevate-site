import { afterEach, describe, expect, it } from "vitest";

import { istDateToInstant, istInputToInstant } from "@/components/ui";
import { consentCollectedAt } from "@/lib/api/campaigns";

/**
 * A DATE TYPED ON THIS CONSOLE MEANS THE SAME INSTANT WHOEVER TYPES IT.
 *
 * `components/ui.tsx::formatISTInput` states the doctrine at length: a `datetime-local`
 * or `date` field carries no zone, both halves of the naive round trip read the BROWSER's
 * clock, and that is correct on a machine set to India and silently wrong everywhere
 * else. D-22's "view as client" plus a colleague on a laptop still set to a US zone make
 * "everywhere else" a real session rather than a hypothetical.
 *
 * Three call sites were still spelling it the naive way, and each one wrote a fact that
 * is read back with `formatIST` — so the value disagreed with its own read-back:
 *
 * - commercial terms' `effective_from` / `effective_to` — the instant a rate card, an
 *   included-minutes allowance and a hard spend cap take effect;
 * - a tenant's DLT `registered_at` — the date on an Indian registrar's letter;
 * - a campaign's `consent_provenance.collected_at` — the date a client asserts they
 *   collected permission to call, under a regime where that date is the defence.
 *
 * ## Why the zone is forced rather than assumed
 *
 * Asserting `"2026-08-09T18:30:00.000Z"` already pins the answer independently of the
 * runner's clock, and would fail on the old code in every zone but +05:30. The `TZ`
 * sweep is what makes the property EXPLICIT: the whole class of defect is "the answer
 * moved with the viewer", so the test states that it does not, in four zones on either
 * side of India — including one (Pacific/Auckland) where the browser's own midnight
 * lands on the PREVIOUS IST day, which is the case that turns a wrong hour into a wrong
 * DATE on a compliance record.
 *
 * Node re-reads `process.env.TZ` on the next `Date` construction, so setting it here is
 * enough; it is restored afterwards because these helpers are the only thing in the
 * suite that would notice, and the next file must not inherit a clock.
 */

const ORIGINAL_TZ = process.env.TZ;

afterEach(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

/** Zones on both sides of IST, including one far enough east to move the DAY. */
const ZONES = ["UTC", "America/Los_Angeles", "Europe/London", "Pacific/Auckland"];

describe("a date-only field means midnight in India", () => {
  it("is the same instant in every zone the console can be opened in", () => {
    for (const zone of ZONES) {
      process.env.TZ = zone;
      // 2026-08-10T00:00+05:30 === 2026-08-09T18:30Z. The browser's own midnight would
      // be 2026-08-10T00:00Z in UTC and 2026-08-09T12:00Z in Auckland — the latter is a
      // different DAY once it is read back in IST.
      expect(istDateToInstant("2026-08-10")).toBe("2026-08-09T18:30:00.000Z");
    }
  });

  it("refuses an empty or unparseable field rather than guessing a day", () => {
    expect(istDateToInstant("")).toBeNull();
    expect(istDateToInstant("   ")).toBeNull();
    expect(istDateToInstant("not-a-date")).toBeNull();
  });
});

describe("a datetime-local field means that wall clock in India", () => {
  it("is the same instant in every zone the console can be opened in", () => {
    for (const zone of ZONES) {
      process.env.TZ = zone;
      // 09:00 IST === 03:30Z. Read as the browser's clock this would have been 09:00Z in
      // UTC and 20:30Z the previous day in Auckland — for commercial terms, a billing
      // boundary up to eleven and a half hours from the one the operator agreed.
      expect(istInputToInstant("2026-08-10T09:00")).toBe("2026-08-10T03:30:00.000Z");
    }
  });
});

describe("the consent collection date a client asserts", () => {
  it("records the day they picked, not the day their browser was on", () => {
    for (const zone of ZONES) {
      process.env.TZ = zone;
      expect(consentCollectedAt("2026-08-10")).toBe("2026-08-09T18:30:00.000Z");
    }
  });

  /**
   * The property the old spelling was reaching for and got by luck: the server refuses a
   * collection date in the future, and midnight IST is the earliest instant of the picked
   * day in the zone the server compares against — so it is never ahead of an IST clock
   * that has already reached that date.
   */
  it("is the earliest instant of that day in India, so it cannot read as future", () => {
    process.env.TZ = "UTC";
    const picked = "2026-08-10";
    const iso = consentCollectedAt(picked);
    expect(iso).not.toBeNull();
    // Any IST wall-clock moment on the picked day is at or after what we send.
    const nineAmIst = new Date(`${picked}T09:00:00+05:30`).toISOString();
    expect(new Date(iso as string).getTime()).toBeLessThan(new Date(nineAmIst).getTime());
  });

  it("refuses an empty field rather than sending an instant nobody chose", () => {
    expect(consentCollectedAt("")).toBeNull();
  });
});
