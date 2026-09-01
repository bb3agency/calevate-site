import { render, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LegalIndexPage from "@/app/legal/page";
import LegalDocumentRoute, { generateStaticParams } from "@/app/legal/[slug]/page";
import {
  LEGAL_DOCUMENTS,
  PENDING_LEGAL_REVIEW,
  PENDING_LEGAL_REVIEW_MARKER,
  PLACEHOLDERS,
  blocksOf,
  legalDocument,
  placeholdersIn,
  textOf,
  type LegalDocument,
} from "@/lib/legal";
import {
  CHROME_TOKENS,
  assertLegalSetPublishable,
  resolvePlaceholders,
  unresolvedPlaceholders,
} from "@/lib/legal/placeholders";
import { SUBPROCESSOR_NAMES } from "@/lib/legal/subprocessors";

import { expectNoA11yViolations } from "./a11y";

/**
 * The published legal documents, and the rules about them a person cannot hold in their
 * head across eight files and ~1,300 lines of prose.
 *
 * These are legally operative texts. The failure modes are not visual: a fabricated fact
 * that was supposed to be a placeholder, a placeholder nobody was told to fill in, a
 * document published while still marked draft, a contact section that got lost in an
 * edit, an anchor that two sections claim so the table of contents jumps to the wrong
 * clause. Every one of those type-checks perfectly. So they are asserted here.
 *
 * The accessibility sweep runs over ALL EIGHT documents rather than the one representative
 * `tests/a11y.test.tsx` scans through the router, because the pages differ in content, not
 * in shell: only the sub-processor page has a five-column table, only the privacy notice
 * has nested subsections five deep in a section, and a violation in either would be
 * invisible in a single-document scan.
 */

/**
 * The first column of every table row in a document — the VENDOR NAMES on the
 * sub-processor register, as rows rather than as prose.
 *
 * `textOf` cannot answer this question: the register legitimately mentions a departed
 * vendor in the prose that records its departure ("until 19 August 2026 this row named
 * …"), and a substring search over the page cannot tell that from a live row. The rows
 * are structured data (`LegalBlock` kind `table`), so the structure is what gets asked.
 */
function vendorRowNames(doc: LegalDocument): string[] {
  return blocksOf(doc).flatMap((block) =>
    block.kind === "table" ? block.rows.map((row) => row[0] ?? "") : [],
  );
}

/** Render one document the way its route does, with `params` already resolved. */
async function renderDocument(slug: string): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    const result = render(<LegalDocumentRoute params={Promise.resolve({ slug })} />);
    container = result.container;
  });
  return container;
}

describe("the document set", () => {
  it("routes every document, and the route table matches the registry", () => {
    const params = generateStaticParams().map((p) => p.slug);
    expect(params).toEqual(LEGAL_DOCUMENTS.map((doc) => doc.slug));
    for (const slug of params) expect(legalDocument(slug)?.slug).toBe(slug);
  });

  it("resolves an unknown slug to nothing rather than to a document", () => {
    expect(legalDocument("gdpr")).toBeUndefined();
    expect(legalDocument("")).toBeUndefined();
    // The prototype-chain hazard `src/lib/lookup.ts` documents: a keyed record would
    // answer this with the `Object` function and the page would render whatever that is.
    expect(legalDocument("constructor")).toBeUndefined();
    expect(legalDocument("__proto__")).toBeUndefined();
  });

  it("covers the eight documents the obligations require", () => {
    expect(LEGAL_DOCUMENTS.map((doc) => doc.slug).sort()).toEqual([
      "acceptable-use",
      "cookies",
      "dpa",
      "grievance",
      "privacy",
      "refunds",
      "subprocessors",
      "terms",
    ]);
  });

  it("gives every section and subsection a unique anchor", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const ids: string[] = [];
      for (const section of doc.sections) {
        ids.push(section.id);
        for (const sub of section.subsections ?? []) ids.push(sub.id);
      }
      expect(new Set(ids).size, `duplicate anchor in /legal/${doc.slug}: ${ids.join(", ")}`).toBe(
        ids.length,
      );
      // An anchor is a citable URL fragment — clause references in a signed contract
      // point at them — so they must be URL-safe and they must not change casually.
      for (const id of ids) expect(id, `/legal/${doc.slug}`).toMatch(/^[a-z0-9-]+$/);
    }
  });

  it("has no empty section", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      for (const section of doc.sections) {
        const filled =
          (section.blocks ?? []).length > 0 || (section.subsections ?? []).length > 0;
        expect(filled, `${doc.slug} § ${section.heading} is a heading with nothing under it`).toBe(
          true,
        );
      }
    }
  });

  it("keeps every table rectangular", () => {
    for (const doc of LEGAL_DOCUMENTS) {
      for (const block of blocksOf(doc)) {
        if (block.kind !== "table") continue;
        for (const row of block.rows) {
          expect(
            row.length,
            `${doc.slug}: "${block.caption}" has a row of ${row.length} cells against ` +
              `${block.columns.length} columns — the table would render misaligned`,
          ).toBe(block.columns.length);
        }
      }
    }
  });
});

describe("the placeholders", () => {
  /**
   * Every token used across the whole document set, plus the ones the page SHELL renders
   * (the effective date sits in the header of all eight pages and in no document's prose).
   */
  const used = new Set([
    ...LEGAL_DOCUMENTS.flatMap((doc) => placeholdersIn(textOf(doc))),
    ...CHROME_TOKENS.flatMap((token) => placeholdersIn(token)),
  ]);

  it("declares every token that any document uses", () => {
    const undeclared = [...used].filter((token) => !Object.hasOwn(PLACEHOLDERS, token));
    expect(
      undeclared,
      `these tokens appear in a document but are not declared in ` +
        `src/lib/legal/placeholders.ts, so the founder is never told to fill them in: ` +
        undeclared.join(", "),
    ).toEqual([]);
  });

  it("uses every token it declares", () => {
    const unused = Object.keys(PLACEHOLDERS).filter((token) => !used.has(token));
    expect(
      unused,
      `these tokens are declared but appear in no document — either the fact got ` +
        `hard-coded somewhere (which is the defect this table exists to prevent) or the ` +
        `entry is dead: ` + unused.join(", "),
    ).toEqual([]);
  });

  it("tells the founder what each one is and where to get it", () => {
    for (const [token, entry] of Object.entries(PLACEHOLDERS)) {
      expect(entry.describes.length, `${token}.describes`).toBeGreaterThan(40);
      expect(entry.source.length, `${token}.source`).toBeGreaterThan(10);
    }
  });

  it("invents no company identity anywhere in the prose", () => {
    // The specific fabrications that would be worst: a made-up GSTIN, CIN or PIN-coded
    // address reads as authoritative and is a false statement to a regulator. Each
    // pattern below must only ever appear as a placeholder, never as a literal.
    const patterns: [string, RegExp][] = [
      ["a GSTIN", /\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b/],
      ["a CIN", /\b[LUu]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b/],
      ["a PAN", /\b[A-Z]{5}\d{4}[A-Z]\b/],
      ["a bare 6-digit PIN code", /\bPIN\s*\d{6}\b/i],
    ];
    for (const doc of LEGAL_DOCUMENTS) {
      const prose = textOf(doc);
      for (const [what, pattern] of patterns) {
        expect(pattern.test(prose), `/legal/${doc.slug} appears to contain ${what}`).toBe(false);
      }
    }
  });

  /*
   * THE DEFECT THIS BLOCK EXISTS FOR, stated once so the three assertions below read as
   * one rule: `{{PRIMARY_HOSTING_LOCATION}}` rendered as a raw token on `/legal/dpa`
   * clause 9 and `/legal/privacy` §8 for weeks AFTER D-180 decided the answer. Nothing
   * was broken — nothing connected a taken decision to the prose, so filling a blank
   * meant editing every document that used it and hoping none was missed. A decided fact
   * now carries a `value`, the renderer substitutes it, and publishing with any fact
   * still blank throws.
   */
  it("substitutes a fact that has been decided, so it never renders as a blank", async () => {
    const decided = Object.entries(PLACEHOLDERS).filter(([, entry]) => entry.value !== undefined);
    expect(
      decided.length,
      "no placeholder carries a value, so the substitution path is untested",
    ).toBeGreaterThan(0);

    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      const marked = [...container.querySelectorAll("mark")].map((node) => node.textContent);
      for (const [token] of decided) {
        expect(
          marked,
          `/legal/${doc.slug} still shows {{${token}}} as a blank, though its value is decided`,
        ).not.toContain(`{{${token}}}`);
      }
    }

    // And the value actually reaches the page, rather than the token merely vanishing.
    const hosting = PLACEHOLDERS.PRIMARY_HOSTING_LOCATION?.value ?? "";
    expect(hosting.length, "PRIMARY_HOSTING_LOCATION carries no value").toBeGreaterThan(0);
    const dpa = await renderDocument("dpa");
    expect(dpa.textContent ?? "").toContain(hosting);
    // The token stays in the SOURCE, which is what keeps the two-way audit above honest.
    expect(textOf(legalDocument("dpa")!)).toContain("{{PRIMARY_HOSTING_LOCATION}}");
    // An undeclared token is left standing rather than swallowed: the audit above fails
    // on one, and quietly dropping it here would turn that failure into a hole in a page.
    expect(resolvePlaceholders("a {{NOT_A_DECLARED_TOKEN}} b")).toBe(
      "a {{NOT_A_DECLARED_TOKEN}} b",
    );
  });

  it("refuses to publish the set while any fact is still blank", () => {
    // While the banner stands, blanks are the point — they are how the founder and their
    // advocate see what is missing — so the check must be silent here.
    expect(() => assertLegalSetPublishable(true)).not.toThrow();

    const missing = unresolvedPlaceholders();
    expect(
      missing.length,
      "every fact is filled in; if that is real, delete this assertion in the same " +
        "commit that removes PENDING_LEGAL_REVIEW",
    ).toBeGreaterThan(0);
    // Removing the banner is the act of publishing. Doing it with `{{GSTIN}}` still in
    // the text puts a document's drafting state in front of a regulator, so it throws
    // and names every outstanding fact rather than failing on the first one.
    expect(() => assertLegalSetPublishable(false)).toThrowError(new RegExp(missing[0]!));
    expect(() => assertLegalSetPublishable(false)).toThrowError(
      new RegExp(missing[missing.length - 1]!),
    );
  });

  it("renders a token as a visible mark rather than as bare text", async () => {
    const container = await renderDocument("privacy");
    const marks = [...container.querySelectorAll("mark")].map((node) => node.textContent);
    expect(marks.length).toBeGreaterThan(0);
    for (const mark of marks) expect(mark).toMatch(/^\{\{[A-Z0-9_ ]+\}\}$/);
    // And no token escapes the marking: nothing outside a <mark> may contain `{{`.
    // The pending-review marker is the one exception and is deliberately literal — it is
    // a banner a human must read and delete, not a value anyone fills in.
    for (const mark of container.querySelectorAll("mark")) mark.remove();
    const unmarked = (container.textContent ?? "").split(PENDING_LEGAL_REVIEW_MARKER).join("");
    expect(unmarked).not.toContain("{{");
  });
});

describe("the pending-review marker", () => {
  it("is on every document while the flag stands", async () => {
    expect(
      PENDING_LEGAL_REVIEW,
      "PENDING_LEGAL_REVIEW has been turned off. That is a deliberate publication " +
        "decision and it must be made by a person who has had these documents reviewed " +
        "by an Indian advocate — not as a side effect of another change. If that has " +
        "happened, delete this assertion in the same commit.",
    ).toBe(true);

    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      expect(
        container.textContent ?? "",
        `/legal/${doc.slug} does not carry the pending-review banner`,
      ).toContain(PENDING_LEGAL_REVIEW_MARKER);
    }
  });

  it("is on the index page too", async () => {
    const { container } = render(<LegalIndexPage />);
    expect(container.textContent ?? "").toContain(PENDING_LEGAL_REVIEW_MARKER);
  });
});

describe("what each document must contain", () => {
  const bySlug = (slug: string): LegalDocument => {
    const doc = legalDocument(slug);
    if (!doc) throw new Error(`no document ${slug}`);
    return doc;
  };

  it("names a grievance contact and a data-protection contact somewhere reachable", () => {
    // Rule 5(9) SPDI 2011 and rule 4(6) of the Consumer Protection (E-Commerce) Rules
    // require the grievance officer's NAME to be published; rule 9 of the DPDP Rules 2025
    // requires the data-protection contact. Both must be on the two pages a reader
    // actually lands on with a complaint.
    for (const slug of ["privacy", "grievance"]) {
      const prose = textOf(bySlug(slug));
      expect(prose, `/legal/${slug}`).toContain("{{GRIEVANCE_OFFICER_NAME}}");
      expect(prose, `/legal/${slug}`).toContain("{{DATA_PROTECTION_CONTACT_EMAIL}}");
    }
  });

  it("states the processor/fiduciary split in the privacy notice and the DPA", () => {
    for (const slug of ["privacy", "dpa"]) {
      const prose = textOf(bySlug(slug));
      expect(prose, `/legal/${slug}`).toContain("Data Fiduciary");
      expect(prose, `/legal/${slug}`).toContain("Data Processor");
    }
  });

  it("states the India-only scope and forbids outbound outside India", () => {
    // The founder froze scope to India-only B2B (docs/legal/LEGAL-OPS-PLAYBOOK.md §0, §2):
    // India-established clients, calls to Indian recipients, no foreign-destination
    // outbound. The product enforces it at dispatch (`destination_not_india`); these two
    // client-facing documents must SAY it, and this keeps the clause from silently
    // dropping out the way a removed vendor once did. It is a scope limit, not a data-
    // residency claim, so it does not collide with the "never leaves India" ban above.
    for (const slug of ["acceptable-use", "terms"]) {
      const prose = textOf(bySlug(slug));
      expect(prose, `/legal/${slug}`).toMatch(/outside India/i);
      expect(prose, `/legal/${slug}`).toMatch(/India-only|non-Indian number|not an Indian/i);
    }
  });

  /**
   * Every occurrence of `pattern` in `prose` that is NOT inside a denial.
   *
   * The two assertions below are both "this must never be CLAIMED", and both documents
   * legitimately name the thing in order to say we do not have it — which is the honest
   * use and the one a template would omit. A flat substring ban would therefore forbid
   * the candid sentence and permit nothing useful, so the window around each hit is
   * inspected for a negation. Crude, and correct in the direction that matters: a hit
   * with no negation nearby fails, so a genuine claim cannot slip through.
   */
  const claimsOutsideDenial = (prose: string, pattern: RegExp): string[] =>
    [...prose.matchAll(new RegExp(pattern.source, "gi"))]
      .filter((match) => {
        const at = match.index;
        const around = prose.slice(Math.max(0, at - 200), at + 120);
        return !/\b(no|not|never|without|holds no|declines|overrides|intention)\b/i.test(around);
      })
      .map((match) => match[0]);

  it("claims no security certification anywhere", () => {
    // The single most tempting sentence to add to a security section, and the one that
    // would be false. `docs/LEGAL-SURFACE.md` records that there is none.
    for (const doc of LEGAL_DOCUMENTS) {
      const bare = claimsOutsideDenial(textOf(doc), /\b(ISO[\s/]?27001|SOC\s?2|PCI[-\s]?DSS)\b/);
      expect(
        bare,
        `/legal/${doc.slug} mentions ${bare.join(", ")} outside a denial — a ` +
          `certification claim must not be published while none is held`,
      ).toEqual([]);
    }
  });

  it("does not claim data never leaves India", () => {
    // The claim the marketing page makes and the deployment blueprint does not support
    // (docs/LEGAL-SURFACE.md, finding F-1). These documents must state the narrow,
    // enforced version — every model endpoint is pinned to the single region the source
    // declares — and nothing wider. Since D-449 that region is `eastus2`, so the India
    // half of the old claim is withdrawn outright rather than restated more softly; the
    // ban below is unchanged, because a withdrawn claim is exactly what must not grow
    // back.
    const pattern =
      /(all data stays in india|never leaves india|entirely within india|stored only in india|only in indian)/;
    for (const doc of LEGAL_DOCUMENTS) {
      const bare = claimsOutsideDenial(textOf(doc), pattern);
      expect(bare, `/legal/${doc.slug} claims ${bare.join(", ")}`).toEqual([]);
    }
  });

  it("does not place the voice platform in India, and says where it actually is", () => {
    /*
     * The narrower version of the test above, on the one vendor where getting it wrong is
     * a live legal exposure rather than a marketing overreach.
     *
     * This register said "India for the platform" for the voice engine and described only
     * that vendor's RECORDING STORAGE as being in the United States. Their own published
     * documentation says the opposite and says it twice: "By default, all Bolna AI
     * services operate in United States (US)-hosted infrastructure" (enterprise/data-
     * residency) and "By default, Bolna processes calls on infrastructure in the US (AWS
     * us-east-1)" (concepts/security). India is an enterprise option nobody here has
     * bought — and their own India-routing requirements exclude the bring-your-own-model-
     * key posture this product is built on, so buying it would not by itself move the
     * calls. `docs/evidence/bolna-compliance-residency.md` §2 carries the quotes.
     *
     * A DPA that tells a client their calls are handled in India when they are handled in
     * the United States is a misstatement in a contract, which is why this is asserted on
     * the ROW rather than left to the prose sweep above: the Location cell is the sentence
     * a buyer's counsel reads.
     */
    const register = bySlug("subprocessors");
    const voiceRows = blocksOf(register).flatMap((block) =>
      block.kind === "table"
        ? block.rows.filter((row) => (row[0] ?? "").startsWith("Bolna"))
        : [],
    );
    expect(voiceRows, "the voice platform must have exactly one register row").toHaveLength(1);
    const location = voiceRows[0]?.[3] ?? "";
    expect(location).toMatch(/United States/);
    expect(location, "the Location cell may not place the voice platform in India").not.toMatch(
      /India/,
    );
    for (const slug of ["subprocessors", "privacy", "dpa"]) {
      expect(textOf(bySlug(slug)), `/legal/${slug}`).toMatch(/United States infrastructure/);
    }
  });

  it("describes the AI disclosure as a client setting with a truthful-answer floor", () => {
    // The founder's posture, and the one paragraph a template would get wrong: the
    // announcement is a toggle, the truthful answer is not, and the duty sits with the
    // client. All three must be present in both places a reader could look.
    for (const slug of ["privacy", "acceptable-use"]) {
      const prose = textOf(bySlug(slug));
      expect(prose, `/legal/${slug}`).toMatch(/answers? truthfully/i);
      expect(prose, `/legal/${slug}`).toMatch(/setting|settings/i);
    }
  });

  it("keeps the sub-processor register as the only copy of the vendor list", () => {
    /*
     * The register is the single source of truth for the vendor list (docs/legal/
     * README.md). This test used to pin two HAND-TYPED vendor arrays — one the DPA must
     * exclude, one the register must contain — and they had already DRIFTED apart: the
     * exclusion list named Cartesia, the inclusion list named Cloudflare-but-not-Cartesia.
     * Two literals maintained by hand is the exact mechanism that let a deleted vendor
     * (Clerk, D-177) and a replaced one (Vertex → Microsoft, D-449) survive in
     * client-facing copy after they left the register. So both loops now read ONE derived
     * inventory, `SUBPROCESSOR_NAMES`, built from the same rows the page renders — a
     * vendor added to or removed from the register moves through here automatically and
     * cannot be silently missed.
     */
    expect(SUBPROCESSOR_NAMES.length, "the register exports no vendor names").toBeGreaterThan(0);

    /*
     * The DPA's Annex C must LINK rather than restate: two vendor lists is the drift the
     * change-notification clause cannot survive. The DPA prose may therefore name NONE of
     * the register's vendors — every one, not a curated subset that rots out of step.
     */
    const dpa = textOf(bySlug("dpa"));
    for (const vendor of SUBPROCESSOR_NAMES) {
      expect(
        dpa.includes(vendor),
        `the DPA names ${vendor} — vendor names belong on the sub-processor page only, ` +
          `or the two lists will disagree`,
      ).toBe(false);
    }

    /*
     * And the register must actually RENDER every identity it exports: the constant is the
     * page's own data, so this proves the derivation still reflects the rendered prose
     * (e.g. the "Google — Gemini API" row really does say "Google") rather than having
     * drifted from it.
     */
    const register = textOf(bySlug("subprocessors"));
    for (const vendor of SUBPROCESSOR_NAMES) {
      expect(register, "sub-processor register").toContain(vendor);
    }

    /*
     * GENUINE INVARIANTS, pinned as literals so the two derived loops above cannot decay
     * into a tautology against their own source. These say what the inventory MUST and
     * MUST NOT hold whatever shape the rows take:
     *
     *  - Microsoft (Azure OpenAI) carries BOTH language legs since D-410, and D-449 left
     *    the vendor alone when it moved the region to East US 2. It is the sub-processor a
     *    client reading this page is most likely to be looking for, so its ABSENCE would
     *    be the real defect — deleting the row fails this line rather than slipping
     *    through a list that only ever shrinks.
     *  - Clerk left at D-177 and Vertex was replaced at D-449; "Gemini" is a Google
     *    PRODUCT the register names in prose but which is NOT a vendor identity (the row's
     *    identity is "Google"). None may reappear as a canonical name — a re-introduction
     *    is exactly what those removals guard against.
     */
    expect(SUBPROCESSOR_NAMES, "the US language-model vendor must be on the register").toContain(
      "Microsoft",
    );
    for (const gone of ["Clerk", "Vertex", "Gemini"]) {
      expect(
        SUBPROCESSOR_NAMES,
        `${gone} is not a current sub-processor and must not be a register identity`,
      ).not.toContain(gone);
    }

    /*
     * Clerk must also not come back as a live TABLE ROW: it was a Core sub-processor
     * receiving authentication factors and session state in the United States — a
     * declared cross-border transfer of auth data to a vendor this product does not use.
     * A HISTORICAL mention in prose ("until <date> this row named …") is legitimate,
     * which is why this checks the row first-cells rather than the page text.
     */
    const rows = vendorRowNames(bySlug("subprocessors"));
    // A `not.toContain` over an empty list passes for the wrong reason, which is the
    // shape `tests/a11y.ts::assertScreenRendered` exists to refuse. The register is a
    // table of vendors; if it stops being one, this must fail rather than go quiet.
    expect(rows, "the register has no vendor rows to check").toContain("Bolna");
    expect(rows, "a sub-processor table row still names Clerk").not.toContain("Clerk");
  });

  it("dates the cross-border clause and says section 16 is not yet in force", () => {
    /*
     * The clause used to read: "Section 16 of the DPDP Act permits transfer of personal
     * data outside India except to a country the Central Government notifies as
     * restricted; no such notification has been made. Rule 15 … requires us to observe
     * any conditions the Government imposes, and we will."
     *
     * Every word of that is defensible and the paragraph as a whole flattered us. It
     * omitted that sections 3–17 — section 16 among them — commence on 13 May 2027, so
     * the permission it leans on is an absence of notification rather than a statutory
     * authorisation; it omitted Rule 13(4), the only real localisation power in the
     * instrument; and it omitted that the operative regime today is the IT Act 2000 and
     * the 2011 rules, which carry a transfer test the DPDP Act does not. The omissions
     * all ran one way, which is the shape this whole document set is written against.
     *
     * These are the load-bearing halves. A clause that states a permission without its
     * commencement date is the defect coming back.
     */
    const dpa = textOf(bySlug("dpa"));
    expect(dpa, "the commencement date of the section the clause relies on").toContain(
      "13 May 2027",
    );
    expect(dpa, "Rule 13(4) — the localisation power the clause used to omit").toMatch(
      /Rule 13\(4\)/,
    );
    expect(dpa, "the regime that is actually in force today").toMatch(
      /Information Technology Act 2000/,
    );
    // Dated, because two of the three instruments change on a known date and a reader in
    // 2027 must be able to tell when this was written.
    expect(dpa).toMatch(/as at \d{1,2} \w+ 202\d/);
  });

  it("gives the DPDP commencement as a period, not a printed day, outside the one derivation", () => {
    /*
     * The gazette publication date of the DPDP Rules 2025 is unverified in this tree
     * (13 or 14 November 2025 — docs/LEGAL-SURFACE.md §9 item 9), and the
     * substantive-commencement date is DERIVED from it by rule 1's eighteen months, so
     * the documents give it as "the middle of May 2027" rather than a day nobody has
     * checked against the gazette. The DPA's clause 9 is the one place specific days may
     * appear, because it SHOWS the derivation ("Published on 13 November 2025, that is
     * 13 May 2027; published on 14 November, it is a day later") — a worked example, not
     * a claim. Privacy §8 printed "13 May 2027" as a bare fact until this audit; this
     * pins the correction so it cannot regress in any document but the derivation.
     */
    for (const doc of LEGAL_DOCUMENTS) {
      if (doc.slug === "dpa") continue;
      expect(
        textOf(doc),
        `/legal/${doc.slug} prints a commencement day the set deliberately gives as a period`,
      ).not.toMatch(/\b1[0-9] May 2027\b/);
    }
    for (const slug of ["privacy", "grievance", "dpa"]) {
      expect(textOf(bySlug(slug)), `/legal/${slug}`).toMatch(/middle of May 2027/);
    }
  });

  it("does not claim every grievance commitment sits inside every statutory limit", () => {
    /*
     * Found by this audit: the grievance page's §2 callout said the middle-column
     * commitments were "shorter than every limit in the right-hand column", and row 1
     * falsifies it — the acknowledgement commitment is 2 BUSINESS days, which across a
     * weekend passes the E-Commerce Rules' 48 CALENDAR hours (if those Rules reach us,
     * which is itself with the advocate). The false comparative must not return, and
     * the honest arithmetic that replaced it is pinned so a trim cannot drop it.
     */
    const grievance = textOf(bySlug("grievance"));
    expect(grievance).not.toMatch(/shorter than every\s+limit/i);
    expect(grievance).toMatch(/can pass the 48-hour mark/);
  });

  it("puts the voice-recording question to the advocate rather than answering it", () => {
    /*
     * The 2011 rules define biometric information to include VOICE PATTERNS, and
     * sensitive personal data carries a transfer test ordinary personal data does not.
     * Whether a business call recording is "biometric information" for that purpose is
     * undecided — the definition reads as though written for authentication — and it is
     * live until 13 May 2027, when DPDP removes the sensitive tier. It is the provision
     * most likely to bite this product and nothing in the tree mentioned it.
     *
     * What is asserted is that the document ASKS rather than ANSWERS. A later edit that
     * resolves it in our favour ("call recordings are not biometric information") is
     * exactly the overclaim the pending-review banner exists to prevent, and it would
     * pass a test that only checked the topic was present.
     */
    const dpa = textOf(bySlug("dpa"));
    expect(dpa, "the 2011 definition that makes this a question at all").toMatch(
      /voice patterns/i,
    );
    expect(dpa, "the document must say the question is undecided").toMatch(
      /never been decided|has no settled answer/i,
    );
    expect(dpa, "and that it is with counsel rather than answered by us").toMatch(/advocate/i);
    // The privacy notice must point at it too — a caller reading only that page should
    // not have to find the DPA to learn the question exists.
    expect(textOf(bySlug("privacy"))).toMatch(/voice patterns/i);
  });

  it("states a refund timeline, which an Indian payment gateway requires", () => {
    const refunds = textOf(bySlug("refunds"));
    expect(refunds).toContain("{{REFUND_PROCESSING_DAYS}}");
    expect(refunds).toMatch(/business days/i);
  });

  /**
   * WHAT THE BUILD PROVES ABOUT THE MODEL REGION, AND THE SENTENCE THAT OVERSTATED IT.
   *
   * Three documents warranted that no setting could move the language leg: the DPA
   * ("No setting, console control or environment variable can move it"), privacy §8 and
   * the sub-processor page's §3.2. This repository contradicts that in its own code —
   * `config.py` calls `azure_openai_resource` "the value that decides residency in
   * practice … no code here can check it", `platform_config.py`'s `AppliesRule` for the
   * same field says "a resource in the wrong region is a residency change no code here
   * can detect", and the ops console renders it as a text box under "Language model".
   *
   * The guard is not the missing half either: `check_model_residency.py` proves four
   * things about the SOURCE, all of which stay true while an operator points the
   * resource somewhere else. OPERATIONS §2 gate 20 is what covers it, by a person.
   *
   * So the absolute shape is banned by SHAPE, the way the India claim is: the documents
   * may warrant what the code cannot do, and may not warrant what an operator cannot.
   * `residencyWarrantyMirror.test.ts` pins the four substrings that survive.
   */
  it("does not claim a setting cannot move the model region", () => {
    /*
     * ASSERTED DIRECTLY, NOT THROUGH `claimsOutsideDenial`, and the reason is worth
     * writing down because it is a trap in the helper rather than in the rule: the
     * banned sentence CONTAINS its own negation ("**No** setting … can move it") and
     * sits one clause after another ("**no** configuration setting may carry a
     * region"). The helper's window would find a negation and read the claim as a
     * denial, so routing this through it would have produced a guard that passes on the
     * exact text it was written to forbid. The shapes below are narrow enough that no
     * honest sentence matches one.
     */
    const banned = [
      // "no setting/console control/environment variable can move it"
      /\bno (setting|console control|environment variable)[^.]{0,80}\bcan move\b/i,
      // "no change to our software or our settings can move …"
      /\bno change to (our|the) (software|code) (or|and) (our|the) settings\b/i,
      /\bsettings?\b[^.]{0,40}\bcannot move\b[^.]{0,40}\bregion\b/i,
    ];
    for (const doc of LEGAL_DOCUMENTS) {
      const prose = textOf(doc);
      for (const pattern of banned) {
        expect(
          prose,
          `/legal/${doc.slug} warrants that no setting can move the model region. ` +
            `\`azure_openai_resource\` is a console field and the region is a property ` +
            `of the resource it names — see F-13 in docs/LEGAL-SURFACE.md.`,
        ).not.toMatch(pattern);
      }
    }
    // And the correction is PINNED, not merely un-banned: deleting the clause that says
    // WHICH resource is a setting is how the over-claim comes back looking like a trim.
    for (const slug of ["dpa", "privacy", "subprocessors"]) {
      expect(textOf(bySlug(slug)), `/legal/${slug} no longer says the resource is ours to set`)
        .toMatch(/resource[^.]{0,120}\b(operational setting|setting of ours|setting our own operators)\b/i);
    }
  });

  /**
   * A RECORDING CONTROL NOBODY BUILT (F-14).
   *
   * `/legal/privacy` §4.1 and `/legal/acceptable-use` §2.6 both said a caller who
   * declines recording has the recording stopped and the refusal written to the consent
   * ledger. `Call.consent_recording` is on `scripts/check_wiring.py`'s known-unwired
   * list ("the engine reports no per-call recording consent yet (pilot gate 3)"),
   * nothing writes a `recording`-purpose ledger row, and voice-runtime has exactly one
   * in-call tool — opt-out. SECURITY-COMPLIANCE §2.2 says it outright: nothing in this
   * codebase can switch recording off.
   *
   * Both halves are asserted, because the pair is what makes the notice honest: the
   * promise must not come back, and the documents must keep saying that recording is not
   * a switch anyone holds.
   */
  it("claims no recording control the product does not have", () => {
    // Direct, for the reason the region ban above states at length: the sentence sat
    // beside "declines", which the denial heuristic reads as a negation. The PRESENT
    // tense is what is forbidden — the withdrawal narrative reports the old promise in
    // the past ("has the recording stopped") and must stay sayable.
    const banned = [
      /\brecording stops\b/i,
      /\brecording is stopped\b/i,
      /\brecording (?:will|would) stop\b/i,
    ];
    for (const slug of ["privacy", "acceptable-use", "dpa", "terms"]) {
      const prose = textOf(bySlug(slug));
      for (const pattern of banned) {
        expect(
          prose,
          `/legal/${slug} says a decline stops the recording. Nothing can stop one ` +
            `mid-call — pilot gate 3, and F-14 in docs/LEGAL-SURFACE.md.`,
        ).not.toMatch(pattern);
      }
    }
    // What replaced it, on the notice a caller reads and the policy a client reads.
    expect(textOf(bySlug("privacy"))).toMatch(/Calls handled by a client's agent are recorded\./);
    expect(textOf(bySlug("privacy"))).toMatch(/does not stop the recording|cannot do today/i);
    expect(textOf(bySlug("acceptable-use"))).toMatch(
      /does not stop the\s+recording|Nothing in the product can stop one/i,
    );
  });

  /**
   * THE MODEL PICKER'S PRICE IS OUR COST, AND THE CONTRACT HAS TO SAY WHICH (F-15).
   *
   * THIS TEST USED TO PIN THE OPPOSITE, AND THE REASON IT CHANGED IS THE POINT.
   *
   * D-454 gave clients a model choice and clause 6.1 correctly said it moved nothing they
   * were charged — because nothing could. D-455 built `plans.llm_model_surcharge`, and the
   * old clause became a sentence that was true only while every plan left the column NULL.
   * A contract term whose truth depends on a column nobody has filled in yet is not a
   * term, it is a countdown: the first operator to price a surcharge would have shipped a
   * false one without touching the document.
   *
   * So 6.1 is now true in BOTH states — no surcharge means nothing changes, a surcharge
   * means the order form quotes it — and this pins the properties that must survive
   * either way: only a commercial term can introduce it, and a model WE chose is never
   * surcharged (`CLIENT_CHOSEN_LLM_SOURCES` excludes `platform`, so flipping the platform
   * default cannot raise the bill of a client who never touched the picker).
   */
  it("prices the model choice as a plan term, and only as a plan term", () => {
    const terms = textOf(bySlug("terms"));
    expect(terms).toMatch(/changes what you pay only if your plan says so/);
    expect(terms).toMatch(/no model\s+list, setting or screen can introduce or raise it/);
    expect(terms).toMatch(/model we choose for you\s+is never surcharged/);
    // The old promise must not survive anywhere: it is the sentence that goes false the
    // moment a number is set, and its return would be silent.
    expect(terms).not.toMatch(/does not change what you pay/);
    // The DPA and the register point at that clause rather than restating the figure —
    // two statements of what a client pays is the drift clause 6.1 exists to prevent.
    for (const slug of ["dpa", "subprocessors"]) {
      expect(textOf(bySlug(slug)), `/legal/${slug} does not point at the fees clause`).toMatch(
        /clause 6\.1 of the\s+Terms of Service/i,
      );
    }
  });

  /**
   * CLAUSE NUMBERS ARE CROSS-REFERENCES AND NOTHING TYPE-CHECKS ONE.
   *
   * Found by this audit: sub-processors are DPA clause 5, and the DPA twice plus the
   * register three times sent a reader to "clause 6" — the data-principal help clause —
   * for the change-notification right they were being told they had. The AUP sent a
   * reader to "clause 6" for what happens on a breach (fees, in the Terms). The Terms'
   * own header comment cited clause 15 for the AI disclaimer, which is clause 13.
   *
   * A wrong pointer in a contract is not cosmetic: it is the sentence a buyer's counsel
   * follows, and it resolves to something that does not say what they were told. So
   * every reference in the published set is resolved against the numbered headings of
   * the document it names — "of the Terms of Service" reads that document, "of this
   * policy" and a bare reference read their own.
   */
  /**
   * THE IN-APP ASSISTANT BECAME AN AGENT AND GAINED A MEMORY, AND NO DOCUMENT SAID SO
   * (docs/LEGAL-SURFACE.md F-16).
   *
   * The failure this pins is the OMISSION shape rather than the misstatement shape, which
   * is why nothing was red while it was true. `apps/api/copilot/__init__.py` said in
   * capitals that nothing in the package persisted, and the panel told the user "it never
   * saves anything"; `copilot_memories` (migration `d4a9c17e6b02`) then shipped a
   * tenant-scoped, per-user store of what a client's staff asked and what an hourly worker
   * distilled out of it. A new CATEGORY of stored personal data that no published document
   * mentions is a DPDP notice defect, not a documentation one — so the category, its
   * period, its purpose and the one thing an erasure does NOT do with it are asserted
   * here, on the four documents that carry them.
   */
  it("says the in-app assistant persists, and never claims it acts alone", () => {
    const privacy = textOf(bySlug("privacy"));
    // The CATEGORY (privacy §3.2) — what is kept, and the limit of the redaction pass.
    expect(privacy).toMatch(/keeps a record of what you asked it and what it answered/);
    expect(privacy).toMatch(/recognises identifiers and\s+not names/i);
    // The PERIOD (privacy §9) — the number `scripts/seed.py` installs for `copilot_memory`,
    // stated in the same table as every other category rather than in a footnote.
    expect(privacy).toMatch(/What the in-app assistant remembers/);
    expect(privacy).toMatch(/180 days/);
    // The ERASURE LIMIT (privacy §12.4). Disclosed BEFORE the certificate carries it, and
    // marked as such — FOLLOW-UP-12 closes the mechanism half. If somebody adds the
    // `ERASURE_LIMITATIONS` entry, this assertion is what tells them to drop the marker.
    expect(privacy).toMatch(/an erasure does not search what the in-app assistant remembers/);

    // PROPOSES, NEVER PERFORMS — the promise the write tools have to keep, in the two
    // documents a client is bound by. `write_tools.confirm()` is the only code there that
    // mutates, and it runs the same gated service function a human's click runs.
    expect(textOf(bySlug("dpa"))).toMatch(/It never\s+makes one/);
    expect(textOf(bySlug("terms"))).toMatch(/carries none of them out by itself/);

    // The store must never be described as absent again. This is the sentence the code
    // itself had to withdraw, so the document may not reintroduce it.
    for (const slug of ["privacy", "dpa", "subprocessors", "terms"]) {
      expect(
        textOf(bySlug(slug)),
        `/legal/${slug} says the assistant stores nothing — it stores copilot_memories`,
      ).not.toMatch(/assistant (?:never saves|saves nothing|stores nothing|keeps nothing)/i);
    }
  });

  /**
   * WHICH PROVIDER SERVES WHICH LEG, AND THE ONE THE REGISTER GOT WRONG (F-16).
   *
   * The register told a client that the OpenAI row served "the dashboard assistant on
   * redacted data". `agents/llm_models.DASHBOARD_TERMS_UNREAD` holds `{"openai"}` and
   * `dashboard_leg_reason` bars it — deliberately fail-closed, because nobody here has
   * read that vendor's data-use position from a primary source and an unread position is
   * not a permission. Over-disclosing a data flow is a smaller wrong than hiding one and
   * it is still wrong: it tells a buyer's counsel that a vendor receives content it never
   * sees, on the page whose entire job is saying where data goes.
   */
  it("does not claim the unread-terms provider serves the in-app assistant", () => {
    const openAiRows = blocksOf(bySlug("subprocessors")).flatMap((block) =>
      block.kind === "table" ? block.rows.filter((row) => (row[0] ?? "") === "OpenAI") : [],
    );
    expect(openAiRows, "the OpenAI register row").toHaveLength(1);
    const row = openAiRows[0] as readonly string[];
    expect(row[1] ?? "", "the OpenAI row must say it does not serve the assistant leg").toMatch(
      /does NOT serve the in-app assistant/,
    );
    expect(row[2] ?? "", "the OpenAI row must not claim assistant content reaches it").toMatch(
      /Nothing from the in-app assistant reaches it/,
    );

    // And the page must state the general rule the bar comes from, so the next vendor
    // added is measured against it rather than against this one row.
    expect(textOf(bySlug("subprocessors"))).toMatch(
      /provider serves it only where somebody here has read/,
    );
  });

  it("resolves every clause reference in the published prose", () => {
    /** "6" and "6.1" for every numbered heading, section and subsection alike. */
    const numbersIn = (doc: LegalDocument): Set<string> => {
      const found = new Set<string>();
      for (const section of doc.sections) {
        const top = /^(\d+)\./.exec(section.heading);
        if (top) found.add(top[1] as string);
        for (const sub of section.subsections ?? []) {
          const nested = /^(\d+\.\d+)/.exec(sub.heading);
          if (nested) found.add(nested[1] as string);
        }
      }
      return found;
    };
    const byTitle = new Map(LEGAL_DOCUMENTS.map((doc) => [doc.title, doc]));

    /**
     * Which document a reference points at.
     *
     * The document TITLES are matched as prefixes of what follows "of the ", longest
     * first, rather than captured by a regex group: "the Terms of Service" contains its
     * own " of ", so any lazy group stops at "Terms" and any greedy one swallows the
     * rest of the sentence. A prefix test against the eight real titles cannot be
     * ambiguous, and an unrecognised name resolves to the document doing the citing —
     * which is the reading a bare "clause 5" gets and the one that fails loudest.
     */
    const titlesLongestFirst = [...byTitle.keys()].sort((a, b) => b.length - a.length);
    const referenced = (rest: string, self: LegalDocument): LegalDocument => {
      const title = titlesLongestFirst.find((candidate) => rest.startsWith(candidate));
      return title === undefined ? self : (byTitle.get(title) as LegalDocument);
    };

    for (const doc of LEGAL_DOCUMENTS) {
      const prose = textOf(doc);
      // `clause 6.1 of the Terms of Service`, `clause 5 of the Data Processing
      // Addendum`, `clause 5 of this policy`, or a bare `clause 5`.
      const pattern = /\bclause (\d+(?:\.\d+)?)(?:\s+of\s+(?:the|this)\s+)?/gi;
      for (const match of prose.matchAll(pattern)) {
        const number = match[1] as string;
        const rest = prose.slice((match.index ?? 0) + match[0].length);
        const target = referenced(rest, doc);
        expect(
          numbersIn(target),
          `/legal/${doc.slug} cites clause ${number} of ` +
            `${target === doc ? "itself" : target.title}, which /legal/${target.slug} ` +
            `does not have`,
        ).toContain(number);
      }
    }
  });
});

describe("every legal screen is scanned by axe", () => {
  it("the index", async () => {
    const { container } = render(<LegalIndexPage />);
    await expectNoA11yViolations(container, "legal/page.tsx");
  });

  it.each(LEGAL_DOCUMENTS.map((doc) => [doc.slug] as const))("/legal/%s", async (slug) => {
    const container = await renderDocument(slug);
    await expectNoA11yViolations(container, `legal/[slug]/page.tsx::${slug}`);
  });
});

describe("the rendered page's structure", () => {
  it("has one h1, and no heading level is skipped", async () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      const levels = [...container.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((node) =>
        Number(node.tagName.slice(1)),
      );
      expect(levels.filter((level) => level === 1).length, `/legal/${doc.slug} h1 count`).toBe(1);
      expect(levels[0], `/legal/${doc.slug} starts below h1`).toBe(1);
      for (let i = 1; i < levels.length; i += 1) {
        expect(
          levels[i] - levels[i - 1],
          `/legal/${doc.slug} skips from h${levels[i - 1]} to h${levels[i]}`,
        ).toBeLessThanOrEqual(1);
      }
    }
  });

  it("gives the table of contents a link for every section", async () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      const toc = container.querySelector('nav[aria-label="On this page"]');
      expect(toc, `/legal/${doc.slug} has no table of contents`).not.toBeNull();
      const targets = new Set(
        [...(toc?.querySelectorAll("a") ?? [])].map((a) => a.getAttribute("href")),
      );
      for (const section of doc.sections) {
        expect(targets, `/legal/${doc.slug} § ${section.heading}`).toContain(`#${section.id}`);
        // And the anchor exists: a contents entry pointing at nothing is worse than none.
        expect(
          container.querySelector(`#${CSS.escape(section.id)}`),
          `/legal/${doc.slug}: #${section.id} is linked but no element carries it`,
        ).not.toBeNull();
      }
    }
  });

  it("makes every horizontally scrolling table reachable from a keyboard", async () => {
    // axe's `scrollable-region-focusable` cannot fire under jsdom (no layout), so the
    // property it would check is asserted structurally instead.
    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      for (const table of container.querySelectorAll("table")) {
        const wrapper = table.parentElement;
        expect(wrapper?.className, `/legal/${doc.slug} table wrapper`).toContain("overflow-x-auto");
        expect(wrapper?.getAttribute("tabindex"), `/legal/${doc.slug} table wrapper`).toBe("0");
        expect(wrapper?.getAttribute("aria-label"), `/legal/${doc.slug} table wrapper`).toBeTruthy();
        expect(table.querySelector("caption"), `/legal/${doc.slug} table caption`).not.toBeNull();
      }
    }
  });

  it("links every other document from each document, so none is orphaned", async () => {
    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      const hrefs = new Set([...container.querySelectorAll("a")].map((a) => a.getAttribute("href")));
      for (const other of LEGAL_DOCUMENTS) {
        if (other.slug === doc.slug) continue;
        expect(hrefs, `/legal/${doc.slug} does not link /legal/${other.slug}`).toContain(
          `/legal/${other.slug}`,
        );
      }
    }
  });
});
