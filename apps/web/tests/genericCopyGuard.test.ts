import { describe, expect, it } from "vitest";

import { copyUnder } from "./copyScan";

/**
 * Calevate serves every kind of small business, so text written for ANY client never
 * assumes a clinic. Examples that belong to one trade live in `lib/verticalExamples.ts`,
 * keyed by the client's business type, and `verticalExamples.test.ts` keeps the other
 * trades' rows free of clinic words.
 *
 * Marketing pages are not read: there a clinic is one named industry among several.
 */

const SURFACES = [
  "src/app/c",
  "src/app/admin",
  "src/components",
  "src/lib",
  // The client's own way in (REDESIGN-2): every business signs up and signs in here.
  "src/app/(auth)/auth/sign-in",
  "src/app/(auth)/auth/accept-invitation",
  "src/app/(auth)/auth/account",
  "src/app/(auth)/auth/forgot-password",
  "src/app/(auth)/auth/reset-password",
  "src/app/(auth)/auth/google",
  "src/app/signup",
  "src/app/invite",
];

const EXEMPT = [
  "src/components/marketing",
  "src/lib/marketing",
  "src/lib/legal",
  "src/lib/api/schema.d.ts",
  // Per-trade examples; the clinic row is the clinic's own.
  "src/lib/verticalExamples.ts",
];

const CLINIC_ONLY = /\b(?:clinics?|hospitals?|patients?|doctors?|dentists?|dental|appointments?)\b/i;

/** Places where the word names the clinic business type itself, with the reason. */
const ALLOWED: ReadonlyArray<{ file: string; text: RegExp; reason: string }> = [
  {
    file: "src/app/admin/new/shared.ts",
    text: /^Clinic$/,
    reason: "the clinic business type's own label in the operator's new-client picker",
  },
  {
    file: "src/app/admin/new/shared.ts",
    text: /^Appointments, department, patient name$/,
    reason: "the lead fields the clinic business type seeds, shown only beside that type",
  },
  {
    file: "src/lib/api/signup.ts",
    text: /^Clinic or hospital$/,
    reason: "the clinic business type's own label in the signup picker",
  },
];

/**
 * Files owned by other work that still carry the wording; reported for routing. Each
 * count may shrink and never grow.
 */
const ROUTED: Readonly<Record<string, number>> = {
  "src/app/c/[slug]/integrations/ConnectedAccounts.tsx": 1,
  "src/components/authn/authShowcase.tsx": 1,
};

describe("copy for any business does not assume a clinic", () => {
  it("reads the surfaces it claims to read", () => {
    expect(copyUnder(SURFACES, EXEMPT, { wide: true }).length).toBeGreaterThan(2000);
  });

  it("finds no clinic-only words outside the clinic's own examples", () => {
    const counted = new Map<string, string[]>();
    for (const entry of copyUnder(SURFACES, EXEMPT, { wide: true })) {
      const match = CLINIC_ONLY.exec(entry.text);
      if (!match) continue;
      if (ALLOWED.some((a) => entry.file === a.file && a.text.test(entry.text.trim()))) continue;
      const line = `${entry.file}:${entry.line} (“${match[0]}”) in: ${entry.text.trim().slice(0, 140)}`;
      counted.set(entry.file, [...(counted.get(entry.file) ?? []), line]);
    }
    const found: string[] = [];
    for (const [file, lines] of counted) {
      if (lines.length > (ROUTED[file] ?? 0)) found.push(...lines);
    }
    expect(found).toEqual([]);
  });
});
