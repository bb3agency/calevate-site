/**
 * One rule for "an Indian mobile" in the browser, the same as `calevate_shared.indian_mobile`
 * on the server: ten digits opening 6, 7, 8 or 9 behind +91.
 */
import { describe, expect, it } from "vitest";

import { normaliseIndianMobile } from "@/lib/api/healer";
import { isIndianMobile, normalizePhone } from "@/lib/phoneNumber";

describe("isIndianMobile", () => {
  it.each(["+918019857559", "+916000000000", "+917999999999", "+919999999999"])("accepts %s", (number) => {
    expect(isIndianMobile(number)).toBe(true);
  });

  it.each([
    "+915999999999", // a 5 opening is not a mobile level
    "+911140000000", // a Delhi landline
    "+91801985755", // nine digits
    "+9180198575590", // eleven digits
    "8019857559", // no country code
    "+448019857559", // another country
    "+91 80198 57559", // not normalised
  ])("refuses %s", (number) => {
    expect(isIndianMobile(number)).toBe(false);
  });

  it("agrees with the normaliser on the number from the 26 Nov 2026 call", () => {
    for (const typed of ["+91 80198 57559", "80198 57559", "080198 57559", "91 8019857559"]) {
      expect(normalizePhone(typed)).toBe("+918019857559");
      expect(isIndianMobile(normaliseIndianMobile(typed))).toBe(true);
    }
  });
});
