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

import { packRate, VOICE_TIERS } from "@/lib/api/rateCard";

import { RATE_CARD, RATE_CARD_ROUTES } from "./fixtures/rateCard";
import { stubApi } from "./harness";


/** `"50000.00"` → `"₹50,000"`. The page's own rule: whole rupees drop the paise. */
function formatRateForTest(rate: string): string {
  const tenThousandths = Math.round(Number(rate) * 10_000);
  const paise = Math.floor((tenThousandths + 50) / 100);
  return `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatAmountForTest(amount: string): string {
  const whole = Number(amount.split(".")[0]).toLocaleString("en-IN");
  return `₹${whole}`;
}

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

/**
 * `/pricing` and `/roi` are ASYNC server components since D-545 — they await the public
 * rate card so no price on the site is a number typed into the bundle. `element()` is
 * therefore awaited below, and the union is what lets the seven pages stay in one list
 * rather than splitting into a sync table and an async one that drift apart.
 */
const PAGES: readonly {
  name: string;
  element: () => React.ReactElement | Promise<React.ReactElement>;
}[] = [
  // NOTE the two async entries are CALLED (`PricingPage()`) rather than elemented
  // (`<PricingPage />`). An element whose type is an async function is not a thenable:
  // awaiting it returns the element unchanged, React renders nothing, and every assertion
  // below fails against an empty container for a reason that has nothing to do with the
  // page. Calling it returns the promise of its tree, which is what `render` needs.
  { name: "/solutions", element: () => <SolutionsPage /> },
  { name: "/industries", element: () => <IndustriesPage /> },
  { name: "/why-calevate", element: () => <WhyCalevatePage /> },
  { name: "/pricing", element: () => PricingPage() },
  { name: "/roi", element: () => RoiPage() },
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
  it.each(PAGES)("$name is a complete, single-headed document", async ({ element }) => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await element());
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

  it.each(PAGES)("$name claims no customer, logo or testimonial", async ({ element }) => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await element());
    const text = assertedText(container);
    expect(text).not.toMatch(/trusted by|our customers say|case study|success story/i);
    expect(text).not.toMatch(/\d+\+?\s*(businesses|clients|companies|customers)\b/i);
    // Every image on the site is our own; a third-party logo is both a claim and a request
    // to a host we do not control.
    for (const img of container.querySelectorAll("img")) {
      expect(img.getAttribute("src") ?? "").toMatch(/^\/brand\//);
    }
  });

  it.each(PAGES)("$name manufactures no urgency", async ({ element }) => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await element());
    const text = assertedText(container);
    expect(text).not.toMatch(/limited (time|offer|places?|spots?)|only \d+ (left|spots?)/i);
    // `ends soon` and `ends today`, not a bare `ends in` — "an enquiry that ends in"
    // is ordinary English and a ban that fires on it is a ban somebody deletes.
    expect(text).not.toMatch(/act now|hurry|last chance|offer ends|ends (soon|today)\b/i);
    expect(text).not.toMatch(/\bwait ?list\b|early bird|founding (member|client)s?/i);
  });

  it.each(PAGES)("$name offers no audio and calls nothing a recorded sample", async ({ element }) => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await element());
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
 * THE PRICING PAGE PUBLISHES NO MANAGED-PLAN NUMBER, AND THE BAN IS NOW SCOPED TO SAY SO.
 *
 * ⚠ THIS BAN USED TO COVER THE WHOLE PAGE. It was narrowed on 5 Sep 2026 (D-545), on
 * purpose and with the founder's decision behind it — not because a figure got past it.
 *
 * What has not changed: commercial terms for a MANAGED plan are negotiated per client
 * (D-11) and every money column on `plans` is nullable with no default, two of them saying
 * in their own comments that the figure "is a founder decision" and that no default may be
 * invented. A managed rate typed onto this page would be a quote nobody can honour,
 * invented by whoever was writing marketing copy — hard rule 11's exact failure, and worse
 * here than anywhere, because a price is the one claim a buyer relies on before they have
 * met anybody.
 *
 * What changed: the SELF-SERVE rate card is not that. It is a live, operator-set price
 * (`self_serve_inr_per_min`) with a pack ladder whose effective rates are computed by the
 * same functions the margin guard uses, fetched at request time from
 * `GET /v1/public/rate-card` and never typed into the bundle. Refusing to print it was
 * making the page read as though we would not say what anything costs — while the ₹50,000
 * pack already delivered a rate below the list one.
 *
 * So the ban now runs against the page WITHOUT `#self-serve`, and a second test asserts
 * that the figures inside that section are the ones the API sent. A managed-plan figure
 * appearing anywhere still fails here, which is the property that was always worth having.
 */
describe("the pricing page", () => {
  it("invents no figure — every rupee on the page came from the rate card", async () => {
    // ⚠ THIS ASSERTION WAS A LOCATION BAN AND IS NOW A PROVENANCE ONE (6 Sep 2026).
    //
    // It used to require that no "₹" appeared outside `#self-serve`. That was the wrong
    // shape twice over. It permitted an invented figure INSIDE that section, and it
    // forbade the real self-serve rate anywhere else — which is how the page came to open
    // with "Why there is no price on this page" while a published rate sat below the fold.
    //
    // What actually matters is provenance, so that is what is checked: collect every
    // rupee figure the page renders and require each one to be a figure the API sent.
    // A managed-plan rate typed into the copy fails this — there is no such figure in the
    // response and there cannot be, since every money column on `plans` is nullable with
    // no default. So does a hand-tuned "₹4.99" in the hero. And the real rate is free to
    // appear wherever it helps a buyer, which is the point.
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
    const text = bodyText(container);

    // BOTH RATES OF EVERY PACK, and both "from" figures (D-547). The set used to hold one
    // rate per pack, which was not a weaker rule so much as a rule about a card that no
    // longer exists: the dearer voice's column would have been un-covered, and a hand-typed
    // premium rate — the exact figure a buyer would be angriest about — would have sailed
    // through. `packRate` is the page's own accessor, so the test cannot disagree with the
    // page about which field is which voice.
    const fromCard = new Set(
      [
        RATE_CARD.list_rate_inr_per_min,
        RATE_CARD.from_sarvam_inr_per_min,
        RATE_CARD.from_cartesia_inr_per_min,
        ...RATE_CARD.packs.flatMap((pack) => VOICE_TIERS.map((voice) => packRate(pack, voice))),
      ]
        .map((rate) => formatRateForTest(rate))
        .concat(RATE_CARD.packs.map((pack) => formatAmountForTest(pack.amount_inr))),
    );
    const rendered = text.match(/₹[\d,]+(\.\d{2})?/g) ?? [];
    expect(rendered.length, "the page shows no price at all").toBeGreaterThan(0);
    for (const figure of rendered) {
      expect(fromCard, `₹ figure not in the rate card: ${figure}`).toContain(figure);
    }

    // Rupees are not the only way to write money, and a bare "5 per minute" would slip
    // past the scan above.
    expect(text).not.toMatch(/\bRs\.?\s*\d/i);
    expect(text).not.toMatch(/\b\d+\s*(lakh|crore)\b/i);

    // And it must still be USEFUL: the two facts a buyer needs are pinned rather than
    // merely permitted.
    expect(text).toMatch(/minutes your agents actually talk/i);
    expect(text).toMatch(/agreed with you/i);
  });

  it("prints the self-serve card the API sent, and nothing it did not", async () => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
    const selfServe = container.querySelector("#self-serve");
    const text = selfServe?.textContent ?? "";
    // The two headline figures are the card's own per-voice "from" rates, rounded to the
    // paisa by the page.
    expect(text).toContain(formatRateForTest(RATE_CARD.from_sarvam_inr_per_min));
    expect(text).toContain(formatRateForTest(RATE_CARD.from_cartesia_inr_per_min));
    expect(text).toContain(formatRateForTest(RATE_CARD.list_rate_inr_per_min));
    // Every rung, priced ON BOTH VOICES. A ladder that silently rendered five of six, or a
    // table that dropped the dearer column, would still pass a "contains ₹4.50" assertion —
    // which is why this counts rows against the fixture and then requires every one of the
    // twelve rates to be on screen.
    expect(selfServe?.querySelectorAll("tbody tr")).toHaveLength(RATE_CARD.packs.length);
    for (const pack of RATE_CARD.packs) {
      expect(text).toContain(formatAmountForTest(pack.amount_inr));
      for (const voice of VOICE_TIERS) {
        expect(text, `${pack.pack_id} has no ${voice} rate`).toContain(
          formatRateForTest(packRate(pack, voice)),
        );
      }
    }
  });

  it("names the voices the API named, and never their vendors", async () => {
    // THE PROVENANCE RULE, APPLIED TO A NAME (founder, 7 Sep 2026). A client buys a named
    // voice quality; which vendor speaks it is ours to change without a client-visible
    // rename, so the two names are defined once in `billing/rates.py::VOICE_TIER_LABELS`
    // and travel on the card. A name typed into the page would pass any assertion written
    // against the real labels, so the card handed in here carries DIFFERENT ones: if the
    // page prints these, it is rendering what it was sent.
    stubApi({
      "/v1/public/rate-card": {
        ...RATE_CARD,
        sarvam_tier_label: "Everyday",
        cartesia_tier_label: "Concert",
      },
    });
    const { container } = render(await PricingPage());
    const text = bodyText(container);
    // The COLUMN HEADINGS first, by position rather than by substring: they are the one
    // place a name and a price sit together, and the place a hand-typed name would be
    // hardest to notice because the rest of the page would still read correctly.
    const headings = [...container.querySelectorAll("#self-serve thead th")].map(
      (th) => th.textContent,
    );
    expect(headings).toContain("Everyday voice");
    expect(headings).toContain("Concert voice");
    // And in the prose, which quotes the same two names.
    expect(text).toContain("Everyday");
    expect(text).toContain("Concert");
    // Nothing prints the names this deployment's API happens to send today: a page holding
    // its own copy of them would pass every assertion above except this one.
    expect(text).not.toMatch(/\bClear\b|\bStudio\b/);
    // And no vendor's name anywhere on the page — the failure this rule exists for is a
    // tier called "Sarvam" or "Cartesia" in copy somebody wrote from the field names.
    expect(text).not.toMatch(/sarvam|cartesia|bulbul|sonic/i);
  });

  it("shows no price at all when the rate card cannot be loaded", async () => {
    // The honest state, and the reason it is asserted: a page that fell back to a typed
    // constant would look identical to a working one while quoting a rate nobody set.
    stubApi({});
    const { container } = render(await PricingPage());
    const selfServe = container.querySelector("#self-serve");
    const text = selfServe?.textContent ?? "";
    expect(text).toMatch(/could not be loaded/i);
    expect(text).not.toContain("₹");
    expect(selfServe?.querySelector("table")).toBeNull();
  });

  it("shows no price when the card arrives without a name for a voice", async () => {
    // A card whose rates have no tier name is not a card this page can render honestly: it
    // would print two rate columns headed by nothing, or — worse — headed by a name typed
    // into the page. `isRateCard` refuses it at the seam, and the page takes the same
    // "could not be loaded" branch it takes for an unreachable API, which is the only
    // honest answer to "we cannot tell you what this rate is for".
    const unnamed: Record<string, unknown> = { ...RATE_CARD };
    delete unnamed.sarvam_tier_label;
    delete unnamed.cartesia_tier_label;
    stubApi({ "/v1/public/rate-card": unnamed });
    const { container } = render(await PricingPage());
    const text = container.querySelector("#self-serve")?.textContent ?? "";
    expect(text).toMatch(/could not be loaded/i);
    expect(text).not.toContain("₹");
  });

  it("quotes each voice's ladder as a band, once, with both ends from the card", async () => {
    /*
     * THE PAGE QUOTED THREE DIFFERENT "THE PRICE" IN SIX LINES (audit, 8 Sep 2026): the h1
     * carried the DEAREST rung, the lede said "from" the cheapest, the h2 said "Start today
     * from" the cheapest again and the paragraph under it said the dearest — ₹5.00, ₹4.50,
     * ₹4.50, ₹5.00 in four consecutive elements, none of them the figure somebody's FIRST
     * purchase is at. Every one of those was provenance-clean, which is exactly why the
     * `fromCard` assertion above could not see it: the defect is not an invented number, it
     * is the same true numbers said four ways.
     *
     * So this counts. In the PROSE — the page minus the rate table, which is a ladder and is
     * meant to repeat rungs — each rupee figure may appear ONCE. A band is two figures said
     * once each; the duplicate this test exists for is a third and fourth sighting.
     */
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
    const table = container.querySelector("#self-serve table")?.textContent ?? "";
    const prose = bodyText(container).replace(table, "");
    const counted = new Map<string, number>();
    for (const figure of prose.match(/₹[\d,]+(\.\d{2})?/g) ?? []) {
      counted.set(figure, (counted.get(figure) ?? 0) + 1);
    }
    for (const [figure, times] of counted) {
      expect(times, `${figure} is quoted ${times} times outside the table`).toBe(1);
    }
    // And the band is BOTH ends of the everyday voice's ladder, in one sentence: the entry
    // rung a first purchase is actually at, and the floor the largest pack reaches.
    const dearestSarvam = formatRateForTest(
      RATE_CARD.packs
        .map((pack) => packRate(pack, "sarvam"))
        .reduce((a, b) => (Number(a) >= Number(b) ? a : b)),
    );
    const h1 = container.querySelector("h1")?.textContent ?? "";
    expect(h1).toContain(dearestSarvam);
    expect(h1).toContain(formatRateForTest(RATE_CARD.from_sarvam_inr_per_min));
    // The heading that used to re-quote one end of it says no figure at all now.
    expect(prose).not.toMatch(/start today/i);
  });

  it("says which price is published and which is a conversation, and never the reverse", async () => {
    // BOTH WERE ON THE PAGE AND NEITHER WAS QUALIFIED: "nothing to sign" and "Start today"
    // over the card, and "the price is a conversation" four sections down. They are true of
    // DIFFERENT things — the self-serve card is published, a managed plan is quoted — and a
    // buyer who read both learned that we will not say what a minute costs on the page that
    // says exactly that.
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
    const text = bodyText(container);
    expect(text).toMatch(/published price, not a quote/i);
    expect(text).toMatch(/agreed with you/i);
    expect(text).not.toMatch(/the price is a conversation/i);
    // And no claim about how an ACCOUNT is opened: `self_serve_signup_enabled` decides that
    // at runtime and the homepage door is the one place that reads it.
    expect(text).not.toMatch(/opened by hand|rather than online|nothing to sign/i);
  });

  it("promises no per-voice overage rate on a managed plan", async () => {
    /*
     * `plans` HAS NO SUCH COLUMN. There are two overage columns
     * (`apps/api/billing/models.py:281-296`) and the second is D-36's premium/value TTS
     * ladder, not one of the two VOICE QUALITIES the self-serve card prices — and every
     * call is counted on the base rung regardless (`apps/workers/pipeline.py:2743-2745`,
     * `tts_tier=BASE_OVERAGE_RUNG`). So the plan section may not name a voice: a client
     * order form cannot carry a rate per voice, and the copy promised one.
     *
     * Asserted with the RELABELLED card, so the guard catches a voice name however it got
     * onto the page — the labels arrive on the wire and a hand-typed "Studio" would pass a
     * test written against today's names.
     */
    stubApi({
      "/v1/public/rate-card": {
        ...RATE_CARD,
        sarvam_tier_label: "Everyday",
        cartesia_tier_label: "Concert",
      },
    });
    const { container } = render(await PricingPage());
    const plan = container.querySelector("#plan")?.textContent ?? "";
    expect(plan.length, "the plan section did not render").toBeGreaterThan(100);
    expect(plan).not.toMatch(/Everyday|Concert/);
    expect(plan).not.toMatch(/each voice|per voice|two-rate/i);
  });

  it("does not offer the buyer a voice control the client realm does not have", async () => {
    // D-21 STANDS: the voice picker is mounted in the admin realm only, and the client's
    // own agent screen says so ("Changing it is still ours … which is why there is no
    // control here"). A pricing page telling a buyer they choose it agent by agent sells a
    // control that is not there, and the register that IS true — tell your account manager
    // — is the one the console now uses on both of its own screens.
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
    const text = bodyText(container);
    expect(text).toMatch(/account manager/i);
    expect(text).not.toMatch(/you choose it|choose it agent by agent|you choose which/i);
  });

  it("sends the reader to the one place a real figure lives", async () => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await PricingPage());
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
 * THE RESOURCES PAGE IS THE SITE'S OWN DICTIONARY, so a word that stopped being true there
 * is wrong in the place a buyer goes to look a word up.
 *
 * Three claims on it went stale under D-545/D-547 and each is pinned by the SHAPE of the
 * mistake rather than by the sentence that replaced it — copy will be rewritten, and a test
 * quoting a paragraph is a test somebody deletes rather than a rule somebody keeps:
 *
 *  1. it sent a reader to `/pricing` to be told nothing was printed there, while that page
 *     publishes a six-rung card with a rate on each of the two voices;
 *  2. its "Publishing" entry listed a change of VOICE among the things a client makes and
 *     publishes, and D-21 says the voice is ours (the console's own agent panel: "Changing
 *     it is still ours … which is why there is no control here");
 *  3. its wallet entry was one sentence about a balance running out, and said none of the
 *     three promises the credit actually carries.
 *
 * No figure is asserted, because none may appear: this page fetches no rate card, so every
 * rupee on it would be a number typed into the bundle.
 */
describe("the resources page", () => {
  /** The glossary as `{ term: detail }` — the shape the page renders it in. */
  function glossary(container: HTMLElement): Map<string, string> {
    const entries = new Map<string, string>();
    for (const item of container.querySelectorAll("#glossary dt")) {
      entries.set(item.textContent ?? "", item.nextElementSibling?.textContent ?? "");
    }
    return entries;
  }

  it("does not send a reader to a price list to be told there is no price", () => {
    stubApi({});
    const { container } = render(<ResourcesPage />);
    const text = bodyText(container);
    expect(text).not.toMatch(/no (figure|price|rate) is (printed|published|shown)/i);
    expect(text).not.toMatch(/why there is no price/i);
    // And it still describes the page it links to, rather than dropping the sentence.
    expect(text).toMatch(/two voices/i);
  });

  it("offers no voice control, and says who moves it", () => {
    stubApi({});
    const { container } = render(<ResourcesPage />);
    const entries = glossary(container);
    const publishing = entries.get("Publishing");
    expect(publishing, "the Publishing entry is gone").toBeDefined();
    // The list of things a client changes and publishes may not contain a voice.
    expect(publishing).not.toMatch(/voice/i);
    const voice = entries.get("Voice quality");
    expect(voice, "the glossary defines no voice quality").toBeDefined();
    expect(voice).toMatch(/account manager/i);
    expect(voice).not.toMatch(/you (choose|pick|select)/i);
  });

  it("states the three promises the credit carries", () => {
    stubApi({});
    const { container } = render(<ResourcesPage />);
    const wallet = glossary(container).get("Wallet and credits") ?? "";
    // Rates frozen on the purchase, oldest purchase first, and no expiry — the same three
    // the terms state (`lib/legal/terms.ts`, clause 6.1) and the console's own panel does.
    expect(wallet).toMatch(/never expires|does not expire/i);
    expect(wallet).toMatch(/oldest purchase first/i);
    expect(wallet).toMatch(/fixes what a minute costs|frozen|cannot reprice/i);
    // The one thing it may not say: that a bigger pack buys more credit. It buys a cheaper
    // minute (D-547), and no pack has granted a bonus since.
    expect(wallet).not.toMatch(/bonus|extra credit|free credit/i);
  });
});

/**
 * ONE CALCULATOR, NOT TWO. `/roi` imports the same component the homepage renders rather
 * than forking it — two implementations of an arithmetic argument would agree on the day
 * they were written and disagree about money by the time anybody noticed.
 */
describe("the ROI page", () => {
  it("renders the shared calculator, once", async () => {
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await RoiPage());
    expect(container.querySelectorAll("[data-roi-calculator]")).toHaveLength(1);
    // The methodology the homepage hides is OPEN here — that is the page's reason to exist.
    const text = bodyText(container);
    expect(text).toMatch(/illustrative/i);
    expect(text).toMatch(/costs?\s+MORE|goes against us|cannot lose is a brochure/i);
    /*
     * AND THE THREE REFUSALS AS STRUCTURE, because the alternation above cannot see them.
     * Its weakest arm is "goes against us" — which is the SECTION'S OWN EYEBROW — so a
     * page that deleted every honest branch and kept the label left it green (proved by
     * reverting exactly that, 9 Sep 2026). The count is against the section, and the
     * verdict a buyer is owed is the one that says we cost more.
     */
    const against = container.querySelector("#against");
    expect(against?.querySelectorAll("dt")).toHaveLength(3);
    expect(against?.textContent).toMatch(/costs?\s+MORE/);
  });

  it("labels the defaults where a reader meets the label without opening anything", async () => {
    /*
     * THE CAVEAT OUTLIVED THE SECTION IT LIVED IN (9 Sep 2026). "The working" was a
     * seven-row `<dl>` restating the model that `RoiCalculator`'s own "How we calculate
     * this" disclosure already states at greater length, one screen above it — two
     * spellings of one fact on a public page — and it was deleted. The one thing it
     * carried that the disclosure does not carry IN THE OPEN is the label on the
     * benchmarks: the calculator says "illustrative" only inside two closed `<details>`.
     *
     * So the sentence moved, verbatim, into the calculator section's intro, and this is
     * the assertion that deletion needs. The `/illustrative/i` check above cannot stand in
     * for it: `textContent` reads the inside of a closed `<details>` just as happily as an
     * open one, so it passes on a page where every word of the caveat is hidden.
     */
    stubApi(RATE_CARD_ROUTES);
    const { container } = render(await RoiPage());
    const main = container.querySelector("main");
    for (const disclosure of main?.querySelectorAll("details") ?? []) disclosure.remove();
    expect(main?.textContent).toMatch(/not measurements we have taken/i);
    expect(main?.textContent).toMatch(/slider you can move/i);
  });
});
