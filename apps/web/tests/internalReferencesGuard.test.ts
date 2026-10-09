import { readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { copyUnder, WEB_ROOT, type CopyString } from "./copyScan";

/**
 * Copy is written from the reader's side of the screen, not from ours.
 *
 * The founder's complaint was that client-facing text "points the clients to irrelevant
 * sources": hints that cited a hard rule, a decision id or a section of DATA-MODEL, and
 * explained a field by how the API stores it. A client needs what this is, what to do and
 * what happens; the reasoning belongs in a code comment.
 *
 * Two guards over `copyScan`'s WIDE walk (JSX text, every string JSX prop that is not
 * styling or wiring, copy-table properties, and any sentence-shaped literal). Comments are
 * never read: the walk is an AST parse.
 *
 *  - CLIENT surfaces: the client console, sign-in, signup, invite, the public pages, every
 *    shared component and the shared libraries that word client screens. Bans internal
 *    references, implementation words and vendor names.
 *  - ADMIN realm: operators may read technical terms, so only code-review artefacts are
 *    banned there — hard rule numbers, decision ids, doc names and section marks.
 *
 * `src/lib/legal` is not read: the legal documents are versioned and hashed, and
 * `legalVendorNames.test.ts` holds them to their own rule.
 *
 * Each ALLOWED entry is a file and the one word it may use, with the reason. An entry is a
 * place where the word is the reader's own subject (a client configuring a webhook), never
 * a place nobody has swept.
 */

const CLIENT_SURFACES = [
  "src/app/c",
  "src/app/(auth)",
  "src/app/page.tsx",
  "src/app/not-found.tsx",
  "src/app/error.tsx",
  "src/app/global-error.tsx",
  "src/app/pricing",
  "src/app/roi",
  "src/app/resources",
  "src/app/security",
  "src/app/solutions",
  "src/app/industries",
  "src/app/why-calevate",
  "src/app/signup",
  "src/app/invite",
  "src/app/legal",
  "src/app/status",
  "src/components",
  "src/lib",
];

/**
 * Inside the roots above, what is not client copy: the hashed legal documents, and the
 * admin-only API helpers whose words are rendered in the operator console only.
 */
const ADMIN_ONLY_LIBS = [
  "src/lib/api/admin",
  "src/lib/api/ops",
  "src/lib/api/clientHealth.ts",
  "src/lib/api/closure.ts",
  "src/lib/api/commercials.ts",
  "src/lib/api/creditLots.ts",
  "src/lib/api/engineCatalogue.ts",
  "src/lib/api/engineLatency.ts",
  "src/lib/api/engineMinutePricing.ts",
  "src/lib/api/engineWorkspaces.ts",
  "src/lib/api/erasure.ts",
  "src/lib/api/featureFlags.ts",
  "src/lib/api/holds.ts",
  "src/lib/api/kycReview.ts",
  "src/lib/api/llmDefaults.ts",
  "src/lib/api/numberPricing.ts",
  "src/lib/api/preferenceScrub.ts",
  "src/lib/api/qaSamples.ts",
  "src/lib/api/refunds.ts",
  "src/lib/api/tenantMembers.ts",
  "src/lib/api/tenantProfile.ts",
  "src/lib/api/trials.ts",
];

const CLIENT_EXEMPT = ["src/lib/legal", "src/lib/api/schema.d.ts", ...ADMIN_ONLY_LIBS];

/** The operator console, and the helpers that word only its screens. */
const ADMIN_SURFACES = [
  "src/app/admin",
  ...readdirSync(join(WEB_ROOT, "src/lib/api"))
    .map((name) => `src/lib/api/${name}`)
    .filter((path) => ADMIN_ONLY_LIBS.some((prefix) => path.startsWith(prefix))),
];

/** Code-review artefacts: banned everywhere a person reads, staff included. */
const ARTEFACT_RULES: ReadonlyArray<readonly [string, RegExp]> = [
  ["a hard rule", /\bhard rules?\b/i],
  ["a decision id", /\bD-\d{2,4}\b/],
  ["a section mark", /§/],
  ["a design doc", /\b(?:DATA-MODEL|TRD|BRD|FLOWS|OPERATIONS|SECURITY-COMPLIANCE|ROADMAP)\b/],
];

/** Implementation words a client has no use for, plus the vendors (D-679). */
const CLIENT_RULES: ReadonlyArray<readonly [string, RegExp]> = [
  ...ARTEFACT_RULES,
  ["our data model", /\b(?:tenants?|RLS|enums?|schemas?|migrations?)\b/i],
  ["our stack", /\bthe API\b|\bendpoints?\b|\bpayloads?\b|\bwebhooks?\b/i],
  [
    "a vendor",
    /\b(?:sarvam|cartesia|bulbul|saaras|sonic|gnani|timbre|vobiz|plivo|pipecat|thinnest(?:ai)?|bolna|exotel)\b/i,
  ],
];

/**
 * Files where one banned word is the reader's own subject. Keyed `file → word`; the word
 * is matched case-insensitively against the finding, so the entry allows nothing else.
 */
const CLIENT_ALLOWED: ReadonlyArray<{ file: string; word: RegExp; reason: string }> = [
  {
    file: "src/app/c/[slug]/integrations/",
    word: /^(?:webhooks?|endpoints?|payloads?)$/i,
    reason: "the client configures their own webhooks and endpoints on this screen",
  },
  {
    file: "src/app/c/[slug]/lead-sources/",
    word: /^(?:webhooks?|endpoints?|payloads?)$/i,
    reason: "a lead source is a webhook the client points their own form at",
  },
  {
    file: "src/app/solutions/page.tsx",
    word: /^(?:webhooks?|endpoints?)$/i,
    reason: "the CRM-delivery section sells the signed webhook to the buyer who wires it",
  },
  {
    file: "src/components/marketing/solutions/solutionMockups.tsx",
    word: /^(?:webhooks?|endpoints?)$/i,
    reason: "the illustration of that same Integrations screen, labelled as the client sees it",
  },
  {
    file: "src/components/marketing/faq.tsx",
    word: /^webhooks?$/i,
    reason: "the FAQ answer on getting leads into your own CRM names the delivery method",
  },
];

function scan(
  roots: readonly string[],
  exempt: readonly string[],
  rules: ReadonlyArray<readonly [string, RegExp]>,
  allowed: typeof CLIENT_ALLOWED = [],
): string[] {
  const out: string[] = [];
  for (const entry of copyUnder(roots, exempt, { wide: true })) {
    for (const [name, rule] of rules) {
      const match = rule.exec(entry.text);
      if (!match) continue;
      if (allowed.some((a) => entry.file.startsWith(a.file) && a.word.test(match[0]))) continue;
      out.push(report(entry, name, match[0]));
    }
  }
  return out;
}

function report(entry: CopyString, name: string, word: string): string {
  return `${entry.file}:${entry.line} — ${name} (“${word}”) in: ${entry.text.trim().slice(0, 140)}`;
}

/**
 * Files owned by lanes this sweep did not edit. Their findings are reported for routing
 * and listed here so the guard is green meanwhile; each entry may shrink and never grow.
 */
const ROUTED: Readonly<Record<string, number>> = {
};

function unrouted(found: readonly string[]): string[] {
  const counted = new Map<string, string[]>();
  for (const line of found) {
    const file = line.slice(0, line.indexOf(":"));
    counted.set(file, [...(counted.get(file) ?? []), line]);
  }
  const out: string[] = [];
  for (const [file, lines] of counted) {
    if (lines.length > (ROUTED[file] ?? 0)) out.push(...lines);
  }
  return out;
}

describe("copy speaks to the reader, not about our internals", () => {
  it("reads the surfaces it claims to read", () => {
    const client = copyUnder(CLIENT_SURFACES, CLIENT_EXEMPT, { wide: true });
    expect(client.length).toBeGreaterThan(3000);
    const admin = copyUnder(ADMIN_SURFACES, [], { wide: true });
    expect(admin.length).toBeGreaterThan(1000);
  });

  it("catches what it exists to catch, and not a comment", () => {
    const sample = [
      "the API stores the OTHERS (DATA-MODEL §3)",
      "so it is never turned into a number here (hard rule 7)",
      "Superseded by D-679.",
      "Your tenant record",
    ];
    for (const text of sample) {
      expect(CLIENT_RULES.some(([, rule]) => rule.test(text)), text).toBe(true);
    }
    expect(CLIENT_RULES.some(([, rule]) => rule.test("Your calls keep going."))).toBe(false);
  });

  it("client copy carries no internal reference, implementation word or vendor", () => {
    expect(
      unrouted(scan(CLIENT_SURFACES, CLIENT_EXEMPT, CLIENT_RULES, CLIENT_ALLOWED)),
      "say what this is, what to do and what happens, in the client's words. Hard rules, " +
        "decision ids, doc sections and how the system stores things belong in a comment.",
    ).toEqual([]);
  });

  it("admin copy carries no code-review artefact", () => {
    expect(
      unrouted(scan(ADMIN_SURFACES, [], ARTEFACT_RULES)),
      "operators read technical terms, but not hard rule numbers, decision ids or doc " +
        "sections — those belong in a comment.",
    ).toEqual([]);
  });
});
