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
import { CHROME_TOKENS } from "@/lib/legal/placeholders";

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
    // enforced version — model endpoints are pinned to Indian regions — and nothing wider.
    const pattern =
      /(all data stays in india|never leaves india|entirely within india|stored only in india|only in indian)/;
    for (const doc of LEGAL_DOCUMENTS) {
      const bare = claimsOutsideDenial(textOf(doc), pattern);
      expect(bare, `/legal/${doc.slug} claims ${bare.join(", ")}`).toEqual([]);
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
    // The DPA's Annex C must LINK rather than restate: two vendor lists is the drift the
    // change-notification clause cannot survive.
    const dpa = textOf(bySlug("dpa"));
    for (const vendor of ["Clerk", "Resend", "Cartesia", "Cohere", "Razorpay"]) {
      expect(
        dpa.includes(vendor),
        `the DPA names ${vendor} — vendor names belong on the sub-processor page only, ` +
          `or the two lists will disagree`,
      ).toBe(false);
    }
    const register = textOf(bySlug("subprocessors"));
    for (const vendor of ["Bolna", "Sarvam", "Clerk", "Cloudflare", "Resend", "Razorpay"]) {
      expect(register, "sub-processor register").toContain(vendor);
    }
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
