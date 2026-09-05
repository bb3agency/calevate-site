import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import IndustriesPage from "@/app/industries/page";
import PricingPage from "@/app/pricing/page";
import ResourcesPage from "@/app/resources/page";
import RoiPage from "@/app/roi/page";
import SecurityPage from "@/app/security/page";
import SolutionsPage from "@/app/solutions/page";
import WhyCalevatePage from "@/app/why-calevate/page";
import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { WHERE_IT_RUNS } from "@/lib/marketing/compliance";
import { INDUSTRIES } from "@/lib/marketing/industries";

import { stubApi } from "./harness";

/**
 * The seven interior marketing pages, held to the homepage's rules.
 *
 * `publicLanding.test.tsx` guards `/` and is where the doctrine is written down. This file
 * is the same doctrine over the pages that were added around it, and it exists because the
 * failure mode is precisely that the rules were understood to apply to the homepage: a
 * customer count, an invented price or a quality score is no less false three clicks in,
 * and the interior pages are the ones a buyer reads last and quotes back at you.
 *
 * The bans below are deliberately the SHAPES rather than the sentences. Copy on these pages
 * will be rewritten; what may not come back is a fabricated number, a borrowed statistic,
 * manufactured urgency, or proof we do not have.
 */

const PAGES: readonly { name: string; element: () => React.ReactElement }[] = [
  { name: "/solutions", element: () => <SolutionsPage /> },
  { name: "/industries", element: () => <IndustriesPage /> },
  { name: "/why-calevate", element: () => <WhyCalevatePage /> },
  { name: "/pricing", element: () => <PricingPage /> },
  { name: "/roi", element: () => <RoiPage /> },
  { name: "/security", element: () => <SecurityPage /> },
  { name: "/resources", element: () => <ResourcesPage /> },
];

/** `<main>` only — the shared chrome names pages and legal documents, it claims nothing. */
function bodyText(container: HTMLElement): string {
  const main = container.querySelector("main");
  expect(main, "the page rendered no <main>").not.toBeNull();
  return main?.textContent ?? "";
}

/**
 * The page's assertions, WITHOUT the section that quotes claims in order to refuse them.
 *
 * `/why-calevate` prints six sentences this company will not say — "Trusted by hundreds of
 * businesses", "Your data never leaves India", "Hear a sample call" — struck through, each
 * with the reason it is absent. That section is the most honest thing on the site and it
 * trips every ban written to catch the same sentences being ASSERTED, which is the classic
 * shape `legal.test.tsx::claimsOutsideDenial` exists for: a guard that cannot tell a claim
 * from its denial fires on the denial and gets deleted.
 *
 * So the bans run over the page MINUS `#refusals`, and the refusals section has its own
 * assertion below — it must still be there, and it must still be a refusal.
 */
function assertedText(container: HTMLElement): string {
  const refusals = container.querySelector("#refusals");
  const full = bodyText(container);
  if (!refusals) return full;
  return full.replace(refusals.textContent ?? "", "");
}

describe("every marketing page", () => {
  it.each(PAGES)("$name is a complete, single-headed document", ({ element }) => {
    stubApi({});
    const { container } = render(element());
    // One `<h1>`: these are documents, and a page with two of them (or none) has no
    // subject a screen-reader user can land on.
    expect(container.querySelectorAll("h1")).toHaveLength(1);
    // The shared chrome: a page rendered without it would have no way back to the rest of
    // the site, which is the defect that made the interior pages worth building at all.
    expect(container.querySelector("header")).not.toBeNull();
    expect(container.querySelector("footer")).not.toBeNull();
    expect(container.firstElementChild?.hasAttribute("data-marketing-root")).toBe(true);
    // Enough of a page to be worth serving. A stub that renders three cards and a heading
    // is the thing the founder ruled out, and it is invisible to every other assertion.
    expect(bodyText(container).length).toBeGreaterThan(1500);
  });

  it.each(PAGES)("$name claims no customer, logo or testimonial", ({ element }) => {
    stubApi({});
    const { container } = render(element());
    const text = assertedText(container);
    expect(text).not.toMatch(/trusted by|our customers say|case study|success story/i);
    expect(text).not.toMatch(/\d+\+?\s*(businesses|clients|companies|customers)\b/i);
    // Every image on the site is our own; a third-party logo is both a claim and a request
    // to a host we do not control.
    for (const img of container.querySelectorAll("img")) {
      expect(img.getAttribute("src") ?? "").toMatch(/^\/brand\//);
    }
  });

  it.each(PAGES)("$name manufactures no urgency", ({ element }) => {
    stubApi({});
    const { container } = render(element());
    const text = assertedText(container);
    expect(text).not.toMatch(/limited (time|offer|places?|spots?)|only \d+ (left|spots?)/i);
    // `ends soon` and `ends today`, not a bare `ends in` — "an enquiry that ends in"
    // is ordinary English and a ban that fires on it is a ban somebody deletes.
    expect(text).not.toMatch(/act now|hurry|last chance|offer ends|ends (soon|today)\b/i);
    expect(text).not.toMatch(/\bwait ?list\b|early bird|founding (member|client)s?/i);
  });

  it.each(PAGES)("$name offers no audio and calls nothing a recorded sample", ({ element }) => {
    stubApi({});
    const { container } = render(element());
    // There is no call audio in this repository. A "hear a sample call" control would be a
    // button with nothing behind it, which is the same defect as a link to a route nobody
    // mounted. `/why-calevate` names the phrase in order to REFUSE it, so the ban is on the
    // offer — an audio element or a play control — rather than on the words.
    expect(container.querySelector("audio")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
  });
});

/**
 * The refusals section is the page's argument, so it is pinned rather than merely allowed.
 *
 * `assertedText` above subtracts it from every ban, which is correct and is also exactly
 * how it could be hollowed out without anything failing: delete the section and the bans
 * pass, delete the strike-through and the page starts making the claims it was quoting.
 * Both are checked here.
 */
describe("the why-calevate page's refusals", () => {
  it("still refuses, in as many words", () => {
    stubApi({});
    const { container } = render(<WhyCalevatePage />);
    const refusals = container.querySelector("#refusals");
    expect(refusals, "the refusals section is gone").not.toBeNull();
    const text = refusals?.textContent ?? "";
    // Every quoted claim is framed as one this company does not make.
    expect(text).toMatch(/you will not find on this website/i);
    // And the two that are easiest to quietly re-assert are named with their reason.
    expect(text).toMatch(/no client in production/i);
    expect(text).toMatch(/not true of every leg of a call/i);
    // The quoted claims are struck through, so a screenshot cannot be read as a boast.
    expect(refusals?.querySelectorAll(".line-through").length).toBeGreaterThan(0);
  });
});

/**
 * THE PRICING PAGE PUBLISHES NO NUMBER, AND THAT IS THE WHOLE POINT OF IT.
 *
 * Commercial terms are negotiated per client (D-11) and every money column on `plans` is
 * nullable with no default — two of them say in their own comments that the figure "is a
 * founder decision" and that no default may be invented. So a rate typed onto that page
 * would be a quote nobody can honour, invented by whoever was writing marketing copy. That
 * is the exact failure hard rule 11 exists for, and it is worse here than anywhere because
 * a price is the one claim a buyer relies on before they have met anybody.
 *
 * The ban is on DIGITS NEXT TO MONEY rather than on the word "price", because the page's
 * entire job is to describe the shape of the bill.
 */
describe("the pricing page", () => {
  it("describes the shape of the bill and names no figure", () => {
    stubApi({});
    const { container } = render(<PricingPage />);
    const text = bodyText(container);
    expect(text).not.toContain("₹");
    expect(text).not.toMatch(/\bRs\.?\s*\d/i);
    expect(text).not.toMatch(/\d[\d,]*\s*(per minute|\/min|a minute|per month|\/mo\b)/i);
    expect(text).not.toMatch(/\b\d+\s*(lakh|crore|k)\b\s*(a|per)\s*(month|year)/i);
    // And it must still be USEFUL: the shape is what the page is for, so the two facts a
    // buyer needs are pinned rather than merely permitted.
    expect(text).toMatch(/minutes your agents actually talk/i);
    expect(text).toMatch(/agreed with you/i);
  });

  it("sends the reader to the one place a real figure lives", () => {
    stubApi({});
    const { container } = render(<PricingPage />);
    const hrefs = [...container.querySelectorAll("main a[href]")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain("/roi");
  });
});

/**
 * THE SECURITY PAGE REUSES THE CORRECTED COPY AND PUBLISHES NO SCORE.
 *
 * Both halves have been got wrong before. The residency paragraph has been narrowed four
 * times and then withdrawn as an India claim; it is held in `lib/marketing/compliance.ts`
 * so the homepage and this page cannot drift apart, and the assertion here is IDENTITY with
 * that constant rather than a substring match — a paraphrase is the failure to catch.
 *
 * The score half is the founder's instruction of 5 Sep 2026: nothing records a per-scenario
 * result, so nothing may render one. Not a percentage, not a rating, not a bar.
 */
describe("the security page", () => {
  it("carries the residency paragraph verbatim, and the sub-processor link with it", () => {
    stubApi({});
    const { container } = render(<SecurityPage />);
    expect(bodyText(container)).toContain(WHERE_IT_RUNS);
    const hrefs = [...container.querySelectorAll("main a[href]")].map((a) =>
      a.getAttribute("href"),
    );
    expect(hrefs).toContain("/legal/subprocessors");
  });

  it("links to every published legal document rather than paraphrasing one", () => {
    stubApi({});
    const { container } = render(<SecurityPage />);
    const hrefs = new Set(
      [...container.querySelectorAll("main a[href]")].map((a) => a.getAttribute("href")),
    );
    for (const doc of LEGAL_DOCUMENTS) {
      expect(hrefs, `no link to /legal/${doc.slug}`).toContain(`/legal/${doc.slug}`);
    }
  });

  it("lists the tested scenarios and scores none of them", () => {
    stubApi({});
    const { container } = render(<SecurityPage />);
    const text = bodyText(container);
    expect(text).toContain("A wrong number");
    expect(text).toContain("A silent line");
    // No score of any shape.
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(text).not.toMatch(/\d+\s*(\/|out of)\s*\d+/);
    expect(text).not.toMatch(/\bpass rate\b|\bscored?\s+\d/i);
    // And it says so, so the omission cannot be read as an oversight.
    expect(text).toMatch(/publish no score/i);
    // No certification, because we hold none.
    expect(text).not.toMatch(/\b(we are|calevate is)\b[^.]{0,40}\bcertified\b/i);
  });
});

/**
 * THE FOUR VERTICALS KEEP EQUAL WEIGHT — the founder's decision of 5 Sep 2026, and the
 * reason `lib/marketing/industries.ts` gives every one of them the same fields.
 *
 * "Equal" is checked as STRUCTURE rather than as word count: every vertical must render its
 * question set, its example result and its suite statement, and clinics must not be the
 * only one with a full section. A page that quietly grew one trade richer than the others
 * would still pass a text-length check and would read exactly like a favourite.
 */
describe("the industries page", () => {
  it("gives all four verticals the same treatment", () => {
    stubApi({});
    const { container } = render(<IndustriesPage />);
    const text = bodyText(container);
    for (const industry of INDUSTRIES) {
      const section = container.querySelector(`#${industry.id}`);
      expect(section, `${industry.name} has no section`).not.toBeNull();
      const fields = [...(section?.querySelectorAll("[data-seed-fields] li") ?? [])].map(
        (li) => li.textContent,
      );
      expect(fields, `${industry.name} does not show its field list`).toEqual([
        ...industry.fields,
      ]);
      expect(section?.textContent).toContain(industry.advantage);
    }
    // The suite statement appears on all four, in one direction or the other — two
    // verticals have golden-transcript cases today (`cl_*`, `re_*`) and two do not.
    expect(text.match(/with its own suite of test calls behind it/g)).toHaveLength(2);
    expect(text.match(/the test calls for it are still being written/g)).toHaveLength(2);
  });
});

/**
 * ONE CALCULATOR, NOT TWO. `/roi` imports the same component the homepage renders rather
 * than forking it — two implementations of an arithmetic argument would agree on the day
 * they were written and disagree about money by the time anybody noticed.
 */
describe("the ROI page", () => {
  it("renders the shared calculator, once", () => {
    stubApi({});
    const { container } = render(<RoiPage />);
    expect(container.querySelectorAll("[data-roi-calculator]")).toHaveLength(1);
    // The methodology the homepage hides is OPEN here — that is the page's reason to exist.
    const text = bodyText(container);
    expect(text).toMatch(/illustrative/i);
    expect(text).toMatch(/costs?\s+MORE|goes against us|cannot lose is a brochure/i);
  });
});
