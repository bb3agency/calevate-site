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
     * The DPA's Annex C must LINK rather than restate: two vendor lists is the drift the
     * change-notification clause cannot survive.
     *
     * THE EXCLUSION LIST NAMES VENDORS THAT ARE ON THE REGISTER, which is the change
     * here. It used to lead with "Clerk", and once Clerk left the register (D-177, and
     * the client-facing removal that followed) that assertion became vacuously true —
     * it proved the DPA does not name a company we have nothing to do with. The rule is
     * about the vendors somebody editing Annex C would plausibly paste IN, so the list
     * is drawn from the LIVE register and moves with it.
     */
    const dpa = textOf(bySlug("dpa"));
    for (const vendor of ["Bolna", "Sarvam", "Microsoft", "Resend", "Cartesia", "Razorpay"]) {
      expect(
        dpa.includes(vendor),
        `the DPA names ${vendor} — vendor names belong on the sub-processor page only, ` +
          `or the two lists will disagree`,
      ).toBe(false);
    }
    /*
     * And the register must NAME them. `Microsoft` replaces `Clerk` rather than merely
     * dropping it: an assertion list that only ever shrinks stops being a test that the
     * register is COMPLETE, and Microsoft is the entry D-410 created — Azure OpenAI
     * carries BOTH language legs, so it is the sub-processor a client reading this page
     * is most likely to be looking for and the one whose absence would be the real
     * defect. D-449 moved that account's REGION from South India to East US 2 and left
     * the vendor alone, which is why this assertion is untouched by that change: the
     * exclusion above still keeps the vendor name out of the DPA, and the DPA names the
     * region instead.
     */
    const register = textOf(bySlug("subprocessors"));
    for (const vendor of ["Bolna", "Sarvam", "Microsoft", "Cloudflare", "Resend", "Razorpay"]) {
      expect(register, "sub-processor register").toContain(vendor);
    }
    // Clerk left the product at D-177 and must not come back as a live row: it was
    // listed as a Core sub-processor receiving authentication factors and session state
    // in the United States, which is a declared cross-border transfer of auth data to a
    // vendor this product does not use. A HISTORICAL mention ("until <date> this row
    // named …") is legitimate and is why this checks the CORE rows rather than the page.
    const rows = vendorRowNames(bySlug("subprocessors"));
    // A `not.toContain` over an empty list passes for the wrong reason, which is the
    // shape `tests/a11y.ts::assertScreenRendered` exists to refuse. The register is a
    // table of vendors; if it stops being one, this assertion has stopped meaning
    // anything and should fail rather than go quiet.
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
