import { describe, expect, it } from "vitest";

import { LEGAL_DOCUMENTS, textOf } from "@/lib/legal";
import { CHROME_TOKENS, PLACEHOLDER_PATTERN } from "@/lib/legal/placeholders";

/**
 * The eight published legal documents are written for people, not for the people who
 * built the product. This is what stops the second kind of sentence coming back.
 *
 * ## The defect, photographed
 *
 * `/legal/acceptable-use` printed the compliance gate's own blocker identifiers, in
 * backticks, in operative prose a client is asked to agree to: `tm_registration_missing`,
 * `dlt_template_not_approved`, `national_dnd_scrub_expired`, `all_contacts_dnc` and
 * eleven more. It was written deliberately — the theory was that a client, a support
 * agent and the test suite would then share one vocabulary — and it was wrong twice.
 *
 * They never shared it. `app/c/[slug]/campaigns/page.tsx` keys a table of English
 * sentences off those identifiers and says so in terms ("the names themselves stay out of
 * the DOM"), so the LOGGED-IN client has never been shown one; the legal page was the
 * only client-facing surface in the product printing them. And a code identifier in a
 * legal document reads as an unfinished draft to the two audiences that matter most for
 * these pages — a regulator and a payment gateway's onboarding reviewer.
 *
 * ## The standard, and where it comes from
 *
 * The same one `tests/plain_language_guard_test.py` cites for the API's problem+json
 * messages, applied to the other half of the product's prose. EVIDENCE CLASS for both
 * sources: read as web-search results quoting them on 2 Sep 2026 — nngroup.com and
 * design-system.service.gov.uk are egress-blocked from this container, so neither page
 * was opened here.
 *
 * - Nielsen Norman Group, "Error-Message Guidelines": human-readable language, with error
 *   codes hidden or minimised and shown for diagnosis only.
 * - GOV.UK Design System, "Error message": word it as the person would.
 *
 * ## What this reads, and the two places it deliberately differs from the Python guard
 *
 * It reads `textOf(doc)` for all eight documents — every heading, paragraph, list item,
 * definition, table cell and callout, which is the same exhaustive walk the placeholder
 * audit in `legal.test.tsx` depends on. Not the TypeScript around it: a module docstring
 * explaining WHY a document says what it says is for the next editor and legitimately
 * names files, blockers and decisions. Nothing renders it.
 *
 * 1. **Backticks are not an exemption here, they are the tell.** The Python guard exempts
 *    a backticked name, because an API message that says press `Idempotency-Key` is
 *    quoting a literal the reader types. These documents have no inline markup at all
 *    (`LegalBlock` is five kinds of plain text, and `types.ts` says why), so a backtick
 *    renders as a backtick — there is no reading of one that helps a client.
 * 2. **Bare "HTTP" is allowed; a status code is not.** The cookie notice explains that
 *    the session cookie is `Secure`, "so it is never sent over plain HTTP", and the
 *    sub-processor register describes what the edge sees on "every HTTP request". Both
 *    are the accurate word for the thing being described, and a vaguer one would be less
 *    true — the same carve-out the Python guard makes for `endpoint`, `header` and
 *    `webhook`. A three-digit status code is never the right word for anybody.
 */

/**
 * The literals a document legitimately QUOTES, because the machine spelling is the word
 * the reader needs.
 *
 * The same carve-out `tests/plain_language_guard_test.py` makes for a message that names
 * an HTTP header the reader types. A cookie notice that will not name the cookie is a
 * cookie notice a reader cannot check against their own browser — the name in the table
 * is the identifier they will see in the developer tools, and any paraphrase of it would
 * be wrong. Each entry is one exact string and is added only for a reader who has to
 * match it against something outside the page.
 */
const QUOTED_LITERALS: readonly string[] = [
  "__Host-calevate_client_session",
  "__Host-calevate_admin_session",
];

/**
 * Prose ready to scan: the `{{TOKENS}}` and the quoted literals removed.
 *
 * The tokens are SCREAMING_CASE and are the one form of machine spelling that belongs on
 * these pages — a blank the founder must fill, marked so a reader cannot read it as final
 * text.
 */
function proseOf(text: string): string {
  let prose = text.replace(new RegExp(PLACEHOLDER_PATTERN.source, "g"), " ");
  for (const literal of QUOTED_LITERALS) prose = prose.split(literal).join(" ");
  return prose;
}

const RULES: readonly (readonly [string, RegExp])[] = [
  // A blocker rule, a column, a config key, a database table — the class of leak that
  // produced this file. Backticked or bare; the marks around it change nothing.
  ["a name in its machine spelling", /(?<![\w{])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w}])/],
  // `PLATFORM_KEK`, `RECORDING_FLOOR_DAYS` — a constant, once the placeholder tokens are
  // stripped out above.
  ["a constant in its machine spelling", /(?<![\w{])[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+(?![\w}])/],
  ["a source file", /\b[\w./-]*\/?[\w-]+\.(?:py|ts|tsx|jsx|json|ya?ml|sql|toml|env)\b/],
  // Our decision log's own numbering. It is the most authoritative-looking citation in
  // the repository and it resolves to a file no reader outside it can open.
  ["an internal decision id", /\bD-\d{1,4}\b/],
  ["an HTTP status code", /\bHTTP[\s-]*\d{3}\b|\b(?:status code|response code)\b/i],
  ["an exception class", /\b[A-Z][A-Za-z]*(?:Error|Exception)\b/],
  // Anything the author reached for backticks to set apart is, on a page with no inline
  // markup, a backtick the reader sees.
  ["a backtick, which renders as a backtick", /`/],
];

/**
 * The claim these documents may never make, in either of its disguises.
 *
 * Calevate is not incorporated. The documents identify the supplier by name, registration
 * number and principal place of business — the items rule 4 of the Consumer Protection
 * (E-Commerce) Rules 2020 requires displayed — and state no legal form at all, which is
 * what most commercial contracts do. Saying nothing is an omission; saying the opposite
 * would be a false statement in a contract, which is a different order of defect, so the
 * words that would assert it are banned by shape. `legal.test.tsx` bans the identifiers
 * that would come with one (a CIN, a GSTIN, a PAN); this bans the prose.
 */
const FABRICATED_INCORPORATION: readonly (readonly [string, RegExp])[] = [
  ["a private limited company", /\bprivate limited\b|\bpvt\.?\s*ltd\b/i],
  // NOT the bare word "CIN". The privacy notice lists the public-registry documents a
  // CLIENT may produce for identity verification — "CIN, LLPIN, GSTIN, Udyam, shop-and-
  // establishment or trade licence" — which is a true sentence about the reader, not a
  // claim about the supplier. A CIN-shaped literal is banned by `legal.test.tsx`, which
  // is the half that would actually be a fabrication.
  ["a certificate of incorporation", /\bcertificate of incorporation\b/i],
  // The documents publish a principal place of business. "Registered office" is the
  // corporate term for a different thing and only gets in by being copied from a
  // template, where it would imply a registration nobody has made.
  ["a registered office", /\bregistered office\b/i],
];

describe("the published legal documents are written in a client's register", () => {
  it("prints no machine name, file, decision id or status code", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const prose = proseOf(textOf(doc));
      for (const [what, pattern] of RULES) {
        const found = pattern.exec(prose);
        expect(
          found?.[0] ?? null,
          `/legal/${doc.slug} shows a reader ${what}. These pages are read by clients, ` +
            `regulators and payment gateways; a code identifier in one reads as an ` +
            `unfinished document. Say what the thing DOES in the words the reader would ` +
            `use — the meaning is load-bearing, the spelling is not.`,
        ).toBeNull();
      }
    }
  });

  it("claims no incorporation that has not happened", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const prose = proseOf(textOf(doc));
      for (const [what, pattern] of FABRICATED_INCORPORATION) {
        expect(
          pattern.exec(prose)?.[0] ?? null,
          `/legal/${doc.slug} appears to describe the supplier as ${what}. It is not ` +
            `incorporated. The documents identify it by name, registration number and ` +
            `principal place of business and state no legal form.`,
        ).toBeNull();
      }
    }
  });

  /**
   * The negative controls. Without these, a regex that had quietly stopped matching
   * anything would pass this file forever and the guard would be decoration.
   */
  it("catches each shape it exists to catch, and clears real prose", () => {
    const caught = [
      "the blocker is tm_registration_missing",
      "the blocker is `tm_registration_missing`",
      "recorded in PLATFORM_KEK",
      "see apps/api/compliance/registration.py",
      "as decided in D-410",
      "the server answers HTTP 502",
      "a ValueError escaped",
      "the `status` column",
    ];
    for (const sentence of caught) {
      expect(
        RULES.some(([, pattern]) => pattern.test(sentence)),
        `not caught: ${sentence}`,
      ).toBe(true);
    }

    const clean = [
      "A campaign whose source has not been declared is refused until you record it.",
      "It is never sent over plain HTTP, and it is not readable by any script on the page.",
      "We acknowledge within 2 business days and tell you our decision within 7 business days.",
      "Promotional calls go out on a 140-series number.",
      "The registrar has approved your business as a Principal Entity.",
      "A sole proprietor buying to earn a livelihood by self-employment may.",
    ];
    for (const sentence of clean) {
      const bad = RULES.filter(([, pattern]) => pattern.test(proseOf(sentence)));
      expect(bad.map(([what]) => what), `wrongly flagged: ${sentence}`).toEqual([]);
    }
  });

  /**
   * The tokens are the one machine-spelled thing on these pages, and they are meant to be
   * seen — a blank the founder must fill, marked so a reader cannot mistake it for final
   * text. Stripping them above is therefore load-bearing, and this pins that the strip
   * still finds them rather than silently matching nothing.
   */
  it("still recognises the placeholder tokens it strips before scanning", () => {
    expect(proseOf("write to {{SUPPORT_EMAIL}} today").includes("SUPPORT_EMAIL")).toBe(false);
    expect(CHROME_TOKENS.every((token) => proseOf(token).trim() === "")).toBe(true);
  });
});
