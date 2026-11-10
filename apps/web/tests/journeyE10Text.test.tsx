/**
 * Journey audit E10 (10 Nov 2026): Indian-script text on the way into the console.
 *
 * Telugu and Devanagari digits are built from their code points (U+0C66, U+0966), and the
 * Telugu name is taken from the founder-owned demo-call fixture: no Indian-language text
 * is hand-written here.
 */
import { describe, expect, it } from "vitest";

import { decodeTextFile, normalizePhone, parseCsv, rowsToEntries } from "@/app/c/[slug]/campaigns/contactList";
import demoCall from "@/components/marketing/home/mockups/demoCall.json";
import { normaliseMobileNumber } from "@/lib/authn/mobileNumber";
import { asciiDigits } from "@/lib/phoneNumber";

const inScript = (zero: number, ascii: string) =>
  [...ascii].map((d) => String.fromCodePoint(zero + Number(d))).join("");
const TELUGU_ZERO = 0x0c66;
const DEVANAGARI_ZERO = 0x0966;
const teluguName = demoCall.turns[0].te.split(",")[0];

describe("a number typed in Telugu or Devanagari digits", () => {
  it("is the same number the server reads (ingest.normalize_phone folds any script's digits)", () => {
    expect(normalizePhone(inScript(TELUGU_ZERO, "9876543210"))).toBe("+919876543210");
    expect(normalizePhone(`+91 ${inScript(DEVANAGARI_ZERO, "9876543210")}`)).toBe("+919876543210");
    expect(normaliseMobileNumber(inScript(TELUGU_ZERO, "09876543210"))).toBe("+919876543210");
  });

  it("reads every digit value, including the run's first and last", () => {
    expect(asciiDigits(inScript(TELUGU_ZERO, "0123456789"))).toBe("0123456789");
    expect(asciiDigits(inScript(DEVANAGARI_ZERO, "0123456789"))).toBe("0123456789");
  });

  it("ignores letters, so a name is still not a number", () => {
    expect(asciiDigits(teluguName)).toBe("");
    expect(normalizePhone(teluguName)).toBeNull();
  });
});

describe("+91 (0) on a business card", () => {
  it("drops the trunk zero as the server does, rather than marking the row unreadable", () => {
    expect(normalizePhone("91 0 98765 43210")).toBe("+919876543210");
    expect(normalizePhone("+91 (0) 98765 43210")).toBe("+919876543210");
  });
});

describe("a contact file saved from Excel", () => {
  const rows = ["phone\tname", `9876543210\t${teluguName}`].join("\r\n");

  it("reads Excel's Unicode Text (UTF-16LE behind FF FE) with the Telugu name intact", () => {
    const body = new Uint8Array(rows.length * 2);
    for (let i = 0; i < rows.length; i += 1) {
      const unit = rows.charCodeAt(i);
      body[i * 2] = unit & 0xff;
      body[i * 2 + 1] = unit >> 8;
    }
    const bytes = new Uint8Array([0xff, 0xfe, ...body]);
    const { entries } = rowsToEntries(parseCsv(decodeTextFile(bytes)));
    expect(entries).toHaveLength(1);
    expect(entries[0].phone).toBe("9876543210");
    expect(entries[0].name).toBe(teluguName);
  });

  it("still reads CSV UTF-8, with or without its mark", () => {
    const utf8 = new TextEncoder().encode(rows);
    const marked = new Uint8Array([0xef, 0xbb, 0xbf, ...utf8]);
    for (const bytes of [utf8, marked]) {
      const { entries } = rowsToEntries(parseCsv(decodeTextFile(bytes)));
      expect(entries[0].name).toBe(teluguName);
    }
  });
});
