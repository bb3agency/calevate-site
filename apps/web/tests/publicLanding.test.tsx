import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import { LEGAL_DOCUMENTS } from "@/lib/legal";

import { stubApi } from "./harness";

/**
 * The landing page — the other screen a stranger sees, and the one with the most room to
 * lie on it.
 *
 * Rendered directly: it is a server component in the app, but a synchronous one with no
 * data fetching and no provider, so React Testing Library renders it as-is. There is no
 * realm, no session and no QueryClient to supply — which is the point of it.
 *
 * These assertions are almost entirely NEGATIVE, because the failure mode of a marketing
 * page is not a crash. Every line on a public page is a promise, and the promises that
 * cost the most are the ones nobody notices being added: a plan price, a customer count,
 * an uptime figure, a turnaround. The product cannot keep any of those today —
 * D-11's pricing is negotiated per client, there is no client #1 in production
 * (ROADMAP M2), and the console itself refuses to print a latency figure because
 * migration `f1a7c39d5be2` dropped the column (SURFACES §2c). A test is the only thing
 * that notices when one is quietly reintroduced.
 */
/**
 * The whole page's text, MINUS the ROI calculator (section 03).
 *
 * The calculator is the one section that deliberately shows a price — Calevate's published
 * self-serve rate, as the input to a comparison the buyer drives (see `roiCalculator.tsx`).
 * Its own positive assertions live in "the ROI calculator" describe below. Everywhere ELSE
 * the no-price / no-percent bans stay in full force, so they run against this subtracted
 * text rather than being deleted. Scoping is NOT weakening: the guard still fails the
 * instant a price, plan or stray percentage appears in any other section, which is the
 * surface those bans exist to protect. The calculator is found by the marker its component
 * renders, so a rename of the section heading cannot silently pull it back under the ban.
 */
function textOutsideCalculator(container: HTMLElement): string {
  const calc = container.querySelector("[data-roi-calculator]");
  const full = container.textContent ?? "";
  if (!calc) return full;
  const inside = calc.textContent ?? "";
  // The calculator's text is one contiguous run in the DOM order `textContent` walks, so
  // removing that substring leaves exactly the rest of the page.
  return full.replace(inside, "");
}

describe("the landing page's claims", () => {
  it("names no price, plan or fee outside the ROI calculator", () => {
    const { container } = render(<Home />);
    const text = textOutsideCalculator(container);
    expect(text).not.toContain("₹");
    expect(text).not.toMatch(/\bRs\.?\b/);
    expect(text).not.toMatch(/\/mo\b|per month|per minute|\bfree\b|\btrial\b/i);
    expect(text).not.toMatch(/pricing|no setup fee/i);
  });

  it("claims no customers, logos or testimonials", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/trusted by|customers use|businesses use|join \d/i);
    expect(text).not.toMatch(/\d+\+?\s*(businesses|clients|companies)/i);
    // No third-party imagery either: a logo wall is a claim in picture form, and an
    // external image is also a request to a host we do not control (the reason
    // `Avatar` replaced dicebear in ui.tsx).
    //
    // THIS USED TO ASSERT ZERO IMAGES, which was the right intent behind the wrong
    // proxy. The page now carries our OWN wordmark and lockup, which are neither a
    // customer's logo nor a third-party request. What actually has to hold is that
    // every image is first-party — a relative path to our own origin — so the check is
    // now that, stated directly. It still fails on the two things it was written for: a
    // logo wall would have to come from somewhere, and anything on another host has a
    // scheme in its `src`.
    const sources = Array.from(container.querySelectorAll("img")).map(
      (img) => img.getAttribute("src") ?? "",
    );
    expect(sources.length).toBeGreaterThan(0);
    for (const src of sources) {
      expect(src, `${src} is not a first-party asset`).toMatch(/^\/brand\//);
    }
  });

  it("claims no uptime, accuracy or answer-rate figure", () => {
    const { container } = render(<Home />);
    // The percentage ban is scoped off the calculator (attrition and conversion-rate are
    // legitimate, adjustable inputs there); the uptime/accuracy word bans stay over the
    // WHOLE page, since none of those words belong in a cost tool either.
    expect(textOutsideCalculator(container)).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(container.textContent ?? "").not.toMatch(
      /uptime|99\.9|accuracy|instantly|milliseconds/i,
    );
  });

  /**
   * THE RESIDENCY CLAIM, banned by SHAPE rather than corrected once.
   *
   * The page used to say "It stays in India — calls, transcripts and recordings are
   * processed and stored in Indian regions". Nothing in this repository supports it:
   * DEPLOYMENT §0 hosts the site stack, Postgres included, on a general-purpose VPS with
   * India co-location NOT required; §1 puts object storage on Cloudflare R2 at
   * `AWS_REGION=auto`; SECURITY-COMPLIANCE §4 records Bolna recordings observed on S3
   * `us-east-1` with the posture still to be pinned in a contract; Clerk, Resend and
   * Sentry are all elsewhere; and no deploy has ever run, so the region is undecided
   * rather than merely unwritten.
   *
   * The narrower claim that replaced it — model endpoints pinned to an Indian region —
   * is GONE TOO as of D-449: on 22 August 2026 the declared model region moved to Azure
   * OpenAI `eastus2`, so the page has no India residency claim left to make and says the
   * language model is American in the same sentence that says the speech is Indian. What
   * `scripts/check_model_residency.py` guards is the MECHANISM, not the country: one
   * declared region, one endpoint builder, no setting able to carry a region. This test
   * is the frontend half: residency is the claim a buyer in this market asks for FIRST,
   * which is exactly why it grows back, and a softened verb over the same implication is
   * the same misrepresentation. Certifications are in the same list because the company
   * holds none.
   */
  it("claims no data residency, storage location or certification", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/stays? in india|remains? in india|never leaves india/i);
    expect(text).not.toMatch(/stored in india|hosted in india|kept in india|held in india/i);
    expect(text).not.toMatch(/data residency|data sovereignty|sovereign/i);
    expect(text).not.toMatch(/soc\s?2|iso[\s-]?27001|hipaa|pci[\s-]?dss|certified|accredited/i);
    /*
     * THERE IS NO SURVIVING INDIA CLAIM ABOUT THE MODEL, and the two strings below are
     * what replaced the one there used to be (`The AI runs on Indian endpoints`).
     *
     * D-449 moved the declared region to `eastus2`. A page that kept the old card and
     * softened the verb would be making a false residency claim, and a page that simply
     * deleted the card would leave a prospect to assume the Indian speech leg covers
     * everything — the omission shape §9b of the competitor teardown records. So the
     * card is pinned in BOTH directions: it must still say the Indian half is Indian,
     * and it must say in as many words that the language model is not.
     *
     * ⚠ 27 AUG 2026: "the Indian half is Indian" is now a claim about the VENDOR only.
     * Sarvam's published privacy policy permits it to process personal data outside
     * India (US cloud infrastructure, EU model and security vendors) — read by the
     * founder at `www.sarvam.ai/privacy-policy` that day and relayed, since the host is
     * egress-blocked here. The substring below is still pinned because deleting the
     * sentence would restore the omission this test exists for; what follows it on the
     * page now says the vendor being Indian is not a residency claim, and a future edit
     * that drops THAT qualification is the defect to catch.
     */
    expect(text).toContain("Speech and the first reading of your transcript are Indian");
    expect(text).toContain("Microsoft Azure OpenAI account in the United States");
    expect(text).not.toMatch(/(recordings?|transcripts?|database|servers?)[^.]{0,40}\bin india\b/i);

    /*
     * AND IT MUST NOT CLAIM THE BUILD PROVES IT — the over-claim in the other
     * direction, which this page was making until D-410 was read against it.
     *
     * Vertex put `asia-south1` in the hostname and the path, so
     * `scripts/check_model_residency.py` really could prove residency from the source,
     * and the page said so: "pinned to Mumbai by a check that fails our build if a line
     * of code ever points somewhere else". `<resource>.openai.azure.com` names no
     * region. The guard now proves that our code cannot ADDRESS anywhere else — one
     * builder, one spelling of the region, no setting able to carry one — and where the
     * resource sits is attested by a person in the provider's console (OPERATIONS gates
     * 20 and 20c). The DPA had to drop the identical warranty; a marketing page may not
     * keep it. Mumbai is banned outright: it was `asia-south1`, and it has been wrong
     * for South India since D-410 and wrong for East US 2 since D-449.
     */
    // Mumbai was `asia-south1`, Google's region. Naming it at all is now a factual error
    // as well as a residency claim, which makes it the cheapest thing to ban outright.
    expect(text).not.toMatch(/mumbai/i);
    // The affirmative shape only. A broad "build … proves" pattern fires on the sentence
    // that DENIES the claim ("checked, not proved by a build"), which is the trap
    // `legal.test.tsx::claimsOutsideDenial` exists for — so this names the construction
    // the page actually had rather than the vocabulary around it.
    expect(text).not.toMatch(/\b(fails?|breaks?) (our|the) build\b/i);
    expect(text).not.toMatch(/\b(our|the) build (fails|proves|guarantees|ensures)\b/i);
    expect(text).not.toMatch(/\b(guarantee[sd]?|guaranteed|certified)\b[^.]{0,40}\bindia/i);
    // And the correction is PINNED, not merely un-banned: the sentence has to keep
    // saying which half is machine-checked and which half a person confirms, because
    // deleting that clause is how the over-claim comes back looking like a tidy-up.
    // `docs/LEGAL-SURFACE.md` F-1 is where the wording comes from.
    expect(text).toContain("checked, not proved by a build");
    /*
     * AND THE OTHER HALF OF THE PICTURE IS PINNED TOO, for the same reason.
     *
     * A card about the AI, sitting in a section headed "Your customers' data", reads to
     * a prospect as "the call is handled in India" unless it says otherwise — and the
     * platform that actually carries the call runs it on US infrastructure by default,
     * with our
     * BYOK posture foreclosing that vendor's India routing (D-415,
     * `docs/evidence/bolna-compliance-residency.md` §2/§5). Every ban above stops the
     * page SAYING something false; none of them stops it implying it by omission, which
     * is the shape a competitor teardown found on the other side of this market
     * (`docs/evidence/outpero-teardown-aug2026.md` §9b: they admit offshore processing
     * in a privacy policy nobody reads). So the qualifying clause is asserted, not
     * merely permitted.
     */
    expect(text).toContain("runs it on US infrastructure today");
  });

  /**
   * THE AI DISCLOSURE, PROMISED NO WIDER THAN THE PLATFORM ENFORCES IT.
   *
   * The page said "Every call says it is an AI … There is no configuration that turns it
   * off" — written before D-163 split the two obligations and made the OPENING
   * announcement a per-agent toggle. The client's own agents screen ships that switch
   * ("Say it is an AI assistant", off-note "Callers are not told at the start of the
   * call"), so the marketing page was promising a buyer the opposite of a control their
   * staff can operate. `/legal/privacy` already scopes the same sentence correctly — to
   * the truthful ANSWER, not to the opening — which is what made the mismatch a
   * misrepresentation rather than a wording preference.
   *
   * What is unswitchable is the answer when a caller ASKS
   * (`compliance/disclosure.TRUTHFUL_ANSWER_PROMISE`, appended above the client's script
   * by `compose_engine_prompt` on every publish). The page must claim that and not the
   * announcement.
   */
  it("promises the AI disclosure no wider than D-163 leaves it", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/every call says it is an ai/i);
    // "no configuration/setting turns it off" is only true of the ANSWER. Banned in the
    // unqualified form the page had; the surviving sentence says what cannot be
    // overridden and names the thing it is about.
    expect(text).not.toMatch(/no (configuration|setting) that turns it off/i);
    expect(text).toContain("It never denies being an AI");
    expect(text).toMatch(/whether it volunteers that line[^.]*is your setting/i);
  });

  it("does not advertise a self-serve door the deployment has switched off", () => {
    const { container } = render(<Home />);
    // `self_serve_signup_enabled` defaults OFF and the tests run with it unset, so the
    // page must say accounts are opened by hand. "Sign up free" over a closed door is
    // the exact shape this migration bans: a claim dressed as a button.
    expect(container.textContent).toContain("does not open accounts online");
    expect(screen.queryByRole("link", { name: /Create a workspace/i })).toBeNull();
    // The door is still a real destination — `/signup` explains and hands over the
    // contact address — so the link stays, honestly labelled.
    const link = screen.getByRole("link", { name: /How to get one/i });
    expect(link.getAttribute("href")).toBe("/signup");
  });

  it("makes no network request", () => {
    const calls = stubApi({});
    render(<Home />);
    expect(calls).toEqual([]);
  });

  it("hands the document its scrollbar back, without reaching the app shells", () => {
    // THE MECHANISM CHANGED AND THE INVARIANT DID NOT (D-161). This used to assert an
    // `overflow-y-auto` container, because `globals.css` pins
    // `html, body { overflow: hidden }` for the `fixed inset-0` shells under /c and
    // /admin, and a marketing page that simply grew was silently clipped.
    //
    // Lenis drives the WINDOW scroller, so an inner scrolling div would break smooth
    // scroll, ScrollTrigger's defaults, browser scroll restoration and the mobile
    // address-bar collapse all at once. The page now scrolls the document, and the
    // override in globals.css is scoped by `:has([data-marketing-root])` — so it is
    // structurally unable to reach a route that does not render this attribute.
    //
    // Asserted on the attribute rather than on a class: the attribute is the actual
    // contract with the stylesheet, and a class name is a detail either side could
    // rename without the other noticing.
    const { container } = render(<Home />);
    const root = container.querySelector("[data-marketing-root]");
    expect(root).not.toBeNull();
    // And it must be the OUTERMOST element, because `:has()` on <html> only frees the
    // document when the marketing root is genuinely in this page's tree.
    expect(container.firstElementChild?.hasAttribute("data-marketing-root")).toBe(true);
  });
});

/**
 * The verticals grid shows the field list a new agent REALLY starts with, so the page
 * and `scripts/seed.py` have to agree — and the way that agreement dies is a seed edit
 * nobody carries over, leaving a landing page advertising a column the product stopped
 * shipping. The chips are read back out of the rendered DOM and matched against the
 * seed's own labels rather than against a second copy in this file, which would only
 * move the drift one file along.
 */
const SEED = readFileSync(resolve(process.cwd(), "..", "..", "scripts", "seed.py"), "utf8");

/** Every `"label": "…"` inside one vertical's list in `VERTICAL_TEMPLATES`, in order. */
function seedLabels(vertical: string): string[] {
  const templates = SEED.slice(SEED.indexOf("VERTICAL_TEMPLATES: dict"));
  const start = templates.indexOf(`    "${vertical}": [`);
  expect(start, `seed.py has no ${vertical} template`).toBeGreaterThan(-1);
  // The list ends at the next entry's indentation — `    ],` on its own line.
  const body = templates.slice(start, start + templates.slice(start).indexOf("\n    ],"));
  return [...body.matchAll(/"label": "([^"]+)"/g)].map((m) => m[1]);
}

/** The card heading on the page → the key it is describing in the seed. */
const CARD_TO_SEED: [string, string][] = [
  ["Clinics", "clinic"],
  ["Property offices", "real_estate"],
  ["Insurance", "insurance"],
  ["Coaching and colleges", "education"],
];

describe("the verticals section", () => {
  it.each(CARD_TO_SEED)("shows %s the columns seed.py actually ships", (card, vertical) => {
    render(<Home />);
    const heading = screen.getByRole("heading", { name: card, level: 3 });
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const chips = [...(section?.querySelectorAll("li") ?? [])].map((li) => li.textContent);
    expect(chips).toEqual(seedLabels(vertical));
  });

  it("does not imply a tested scenario suite behind all four", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    // Only `cl_*` and `re_*` cases exist in `tests/fixtures/golden_transcripts.json`, so
    // exactly two cards may make the stronger claim and the other two must say plainly
    // that their test calls are not written.
    expect(text.match(/with its own suite of test calls behind it/g)).toHaveLength(2);
    expect(text.match(/the test calls for it are still being written/g)).toHaveLength(2);
  });
});

/**
 * THE QUALIFICATION-LAYER SECTION — positioning, held to the same rule as every other
 * claim on this page: name a behaviour the product already performs, or leave it out.
 *
 * The three cards map to shipped surfaces (`apps/api/ingest/service.py`'s webhook-in →
 * gate → dial, the per-agent extraction schema driving `crm/columns.py`, the fixed lead
 * status enum in `crm/schemas.py:29`, `pipeline.py::HOT_LEAD_FIELD_TRIGGERS`, and
 * `crm/performance.py`'s Calls → Connected → Qualified funnel). What this test guards is
 * the thing a positioning section attracts like nothing else: a borrowed conversion
 * statistic. Every number this play is usually sold with traces back to a study this
 * repository could not read (hbr.org and the rest are egress-blocked here), so hard rule
 * 11 forbids repeating them, and the page argues with the buyer's own arithmetic in the
 * calculator instead. `docs/POSITIONING-QUALIFICATION-LAYER.md` names each refused figure.
 */
describe("the qualification-layer section", () => {
  it("makes the argument without a statistic, and without promising a replacement", () => {
    const { container } = render(<Home />);
    const heading = screen.getByRole("heading", {
      name: /Your salespeople should be closing/i,
    });
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const text = section?.textContent ?? "";

    // The reframe itself, in as many words: augmentation, not replacement.
    expect(text).toContain("This is not your team replaced");
    // No borrowed research: no multiples, no lifts, no "studies show", no percentages.
    // (The page-wide percentage ban is scoped off the calculator only; this section is
    // inside its reach anyway, so this is a second, narrower guard on the exact shapes a
    // conversion claim takes.)
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(text).not.toMatch(/\b\d+(\.\d+)?\s*x\b/i);
    expect(text).not.toMatch(/stud(y|ies)|research|survey|report(s|ed)? that|on average/i);
    expect(text).not.toMatch(/\b(more|higher|faster|better) (conversions?|conversion rate)/i);

    // And no speed claim the product does not measure. "Instantly" is already banned over
    // the whole page; the shipped fact is that the gap is TIMED
    // (`core/alerting.py:611::record_speed_to_lead`), which is what the card says.
    expect(text).toMatch(/the gap between the form and the dial is timed/i);

    // Three cards, each a heading and a body — the same shape as every other card grid.
    const cards = [...(section?.querySelectorAll("h3") ?? [])];
    expect(cards).toHaveLength(3);
    expect(container.textContent).toContain("Where your team's time goes");
  });
});

/**
 * THE KNOWLEDGE CLAIM — banned by SHAPE, because it is the claim this market's buyers
 * assume without being told.
 *
 * **The fact.** In-call retrieval is T0 and nothing else (`docs/TRD.md:948`): the facts a
 * person approves are compiled into the agent's own system prompt at publish time
 * (`apps/api/agents/t0.py`). The engine's built-in knowledge base is OFF
 * (`apps/api/engine/bolna.py:2484`, `knowledge_base=False`) and `attach_kb` refuses in as
 * many words — "The voice platform's knowledge base accepts documents, not text"
 * (`bolna.py:3536`). `POST /v1/kb/sources` takes TEXT: `kind="url"` and `kind="file"` are
 * declared on the wire and REFUSED by the service (`apps/api/kb/routes.py:44`). There is
 * no embedding path in `apps/`, and there is no file input anywhere in this console
 * (`grep 'type="file"' apps/web/src` returns nothing).
 *
 * So a page that says "upload your price list" — which this one did, in the capability
 * card and in the FAQ — sends a buyer looking for a control that does not exist, and lets
 * them infer an agent that reads a 40-page PDF and looks things up mid-call. That is the
 * F-1 shape from `docs/LEGAL-SURFACE.md`: a promise to a prospect, on the surface where it
 * is a CPA 2019 representation rather than an internal note.
 *
 * **The correction is pinned, not merely the ban.** Deleting the sentence would leave the
 * omission — a buyer assuming document retrieval because nothing said otherwise — so the
 * page has to keep saying what DOES happen, and what happens is better: the facts are in
 * the agent before the call, so there is nothing to wait for mid-call.
 *
 * ## Why the bans are shaped the way they are
 *
 * They are deliberately NOT a bare `/upload/i` over the page. "Upload" is legitimate about
 * a client's own systems and about anything a human reads and approves; what is banned is
 * the verb aimed at the agent's KNOWLEDGE, and the retrieval verbs aimed at a live call.
 * Each pattern is bounded by `[^.]{0,60}` so it stays inside one sentence — a ban wide
 * enough to fire on an honest sentence gets deleted by the next person who trips over it,
 * and then nothing guards the real claim.
 */
describe("what the page promises the agent knows", () => {
  it("never offers a document upload, because nothing in the product accepts one", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(
      /\bupload(ing|ed|s)?\b[^.]{0,60}\b(price list|rate card|brochure|document|documents|pdf|file|files|catalogue|menu|material)\b/i,
    );
    expect(text).not.toMatch(
      /\b(document|documents|pdf|pdfs|brochure|file|files)\b[^.]{0,60}\byou\b[^.]{0,20}\bupload/i,
    );
    // No file words in the knowledge register at all: the page has no reason to name a
    // format nothing in the product can read.
    expect(text).not.toMatch(/\bpdfs?\b|\bword docs?\b|\bdocx\b/i);
  });

  it("never implies the agent looks something up while the caller waits", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    // Retrieval verbs pointed at the client's own material — "searches your documents",
    // "reads your price list", "looks it up in your knowledge base". Every one of them
    // describes a system this repository does not contain.
    expect(text).not.toMatch(
      /\b(search(es|ing)?|looks? (it |them )?up|reads?|scans?|consults?)\b[^.]{0,40}\byour\b[^.]{0,30}\b(document|documents|files?|pdfs?|knowledge base|material)\b/i,
    );
    // The open-genre promises. None is backed, and the last one is unbackable by anything.
    expect(text).not.toMatch(/\btrained on your\b|\blearns your\b|\bknows everything\b/i);
    expect(text).not.toMatch(/\banswers? any question\b/i);
  });

  it("says instead what the agent really carries, so the omission cannot come back", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    // The capability card: "built into the agent" is the T0 mechanism in the owner's own
    // words, and the approval half is the product property FLOWS §7 exists for.
    expect(text).toContain("built into the agent");
    expect(text).toContain("until a person approves it");
    // The FAQ answer. Both halves are load-bearing: WHERE the answers come from (facts a
    // person approved, not a document) and WHEN they get there (before the call).
    expect(text).toContain("From facts somebody has approved");
    expect(text).toContain("written into the agent before it takes a call");
  });
});

describe("the questions section", () => {
  it("answers every question it asks", () => {
    const { container } = render(<Home />);
    const items = [...container.querySelectorAll("details")];
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      // Closed by default: an FAQ that renders open is a wall of text, and the reveal
      // below it would be measured against a height that changes on first interaction.
      expect(item.open).toBe(false);
      // A question is a heading inside the summary, and an answer is prose after it.
      expect(item.querySelector("summary h3")?.textContent ?? "").not.toBe("");
      expect(item.querySelector("p")?.textContent ?? "").not.toBe("");
    }
  });

  it("uses the platform's own disclosure widget, so it works with no script at all", () => {
    const { container } = render(<Home />);
    // The whole page's rule is that it is finished without its bundle. A hand-built
    // accordion (button + aria-expanded + hidden panel) renders answers nobody can reach
    // when the bundle fails; `<details>` is keyboard-operable and announced without it.
    const summaries = container.querySelectorAll("summary");
    expect(summaries.length).toBe(container.querySelectorAll("details").length);
    expect(container.querySelectorAll("[aria-expanded]").length).toBe(0);
  });

  it("touches no animation for a reader who asked for none", () => {
    // `tests/setup.ts` reports `prefers-reduced-motion: reduce`, so no ScrollTrigger was
    // ever created and refreshing them on toggle would be work done for nothing — the
    // same rule `Reveal` and `SmoothScroll` follow.
    const refresh = vi.spyOn(ScrollTrigger, "refresh");
    const { container } = render(<Home />);
    const first = container.querySelector("details");
    expect(first).not.toBeNull();
    // `toggle` does not bubble, so there is no `fireEvent.toggle` helper — React attaches
    // this listener to the element itself and a plain event dispatched at it is what the
    // browser would deliver.
    fireEvent(first as HTMLDetailsElement, new Event("toggle"));
    expect(refresh).not.toHaveBeenCalled();
  });
});

/**
 * THE CONVERSION STRUCTURE, pinned in the same negative style as the claims above — and
 * for the same reason. This page has NO social proof available to it: there is no client
 * #1 in production (ROADMAP M2), so testimonials, customer counts, logo walls, star
 * ratings and case studies would all be fabrications, and the borrowed statistics the
 * genre runs on trace to sources this repository could not read (hard rule 11;
 * `docs/POSITIONING-QUALIFICATION-LAYER.md` §6 names each refused figure).
 *
 * What is left is clarity, the buyer's own arithmetic, and risk reversal that is true.
 * Those three are structural rather than textual, which is what these assertions guard: a
 * later edit can reword any of it, but it cannot quietly reintroduce four names for one
 * door, bury the audience below the fold again, or drop the repeated call to action that
 * a page this long needs.
 */
describe("the page's structure asks for one thing, once", () => {
  /**
   * ONE DESTINATION, ONE LABEL, OFFERED MORE THAN ONCE.
   *
   * `/signup` was reached under four different names — "Get a workspace" twice, "How to
   * get one" and "Start a conversation" — which is CLAUDE.md's "two ways of doing one
   * thing" defect on a surface where it also costs conversion: a reader cannot tell
   * whether four buttons are four things or one, so repetition reads as clutter instead
   * of confidence. GOV.UK's rule is about multiple DIFFERENT default buttons ("having
   * more than one main call to action reduces their impact", alphagov/govuk-design-system
   * `main`, `src/components/button/index.md`, read 1 Sep 2026); the same action repeated
   * down a long page is not that, and is what the assertion below requires.
   *
   * "How to get one" is the one deliberate exception and is pinned separately above: it
   * answers the question its own card heading asks.
   */
  it("offers the same door under one name, at more than one point on the page", () => {
    const { container } = render(<Home />);
    const toSignup = [...container.querySelectorAll('a[href="/signup"]')];
    // Header, hero, the block under the calculator, the doors card and the closing panel.
    expect(toSignup.length).toBeGreaterThanOrEqual(4);

    const labels = new Set(toSignup.map((a) => (a.textContent ?? "").trim()));
    labels.delete("How to get one");
    // Two spellings, not one, and the second is measured rather than stylistic: the
    // header shares a row with the logo and "Sign in", and `MarketingAccountNav` records
    // that the row was 374px of content in a 320px viewport before it was tightened. The
    // short form is a prefix of the long one, so it reads as the same offer.
    expect(
      [...labels].sort(),
      "every other link to /signup must carry the SAME label — one door, one name for it",
    ).toEqual(["Talk to us", "Talk to us about your calls"]);

    // And it is offered again where the reader has just done work, rather than only at the
    // top and the very bottom with the whole page in between.
    const cost = container.querySelector("#cost");
    expect(cost, "the cost section did not render").not.toBeNull();
    expect(cost!.querySelectorAll('a[href="/signup"]').length).toBe(1);
  });

  /**
   * WHO THIS IS FOR, ABOVE THE BUTTON RATHER THAN BELOW IT.
   *
   * The audience sentence used to be the last item in the hero, under the call to action
   * and under the three-item list, so on a phone the reader this page is written for had
   * to scroll past the button to learn it was addressed to them. Asserted on ORDER in the
   * DOM rather than on the words, because the words may legitimately be rewritten and the
   * order is the thing that regressed.
   */
  it("says who it is for before it asks for anything", () => {
    const { container } = render(<Home />);
    const hero = container.querySelector("h1")?.closest("section");
    expect(hero, "the hero section did not render").not.toBeNull();

    const audience = [...hero!.querySelectorAll("p")].find((p) =>
      /Andhra Pradesh and Telangana/.test(p.textContent ?? ""),
    );
    expect(audience, "the hero no longer names who it is for").toBeDefined();

    const cta = hero!.querySelector('a[href="/signup"]');
    expect(cta).not.toBeNull();
    // `compareDocumentPosition` reads DOM order, which is reading order.
    expect(
      audience!.compareDocumentPosition(cta!) & Node.DOCUMENT_POSITION_FOLLOWING,
      "the audience sentence must come BEFORE the hero's call to action",
    ).toBeTruthy();
  });

  /**
   * THE BANDS ARE NUMBERED, AND THE NUMBERS ARE THE READING ORDER.
   *
   * The eyebrow index is decoration until it disagrees with the order of the sections,
   * at which point it is a small visible defect that says nobody checked. It also pins
   * the objection order itself: fit ("is it for me, in my language, for my trade") ahead
   * of value ahead of the sceptic's objections. See `app/page.tsx`'s header for why that
   * order and not the one it replaced.
   */
  it("numbers its bands in the order they are read", () => {
    const { container } = render(<Home />);
    const eyebrows = [...container.querySelectorAll("main p > span.font-mono")]
      .map((s) => s.textContent ?? "")
      .filter((t) => /^\d\d$/.test(t));
    expect(eyebrows).toEqual([
      "01",
      "02",
      "03",
      "04",
      "05",
      "06",
      "07",
      "08",
      "09",
      "10",
    ]);
  });

  /**
   * RISK REVERSAL, AND EVERY LINE OF IT A SHIPPED FACT.
   *
   * This is the slot a landing page normally fills with a testimonial or a money-back
   * guarantee. We have neither: no client is in production to quote, and there is no
   * refund term to promise (D-11's commercial terms are negotiated per client). What we
   * do have is three things the buyer keeps control of, each enforced in code — approval
   * before anything is answerable (`apps/api/agents/t0.py`, `kb_sources` review states),
   * the campaign launch gate (`apps/api/campaigns/service.py`), and the pause that stops
   * the next dispatch tick. Pinned so a later edit cannot swap one of them for a promise
   * nothing enforces.
   */
  it("reverses risk with three things the product actually enforces", () => {
    const { container } = render(<Home />);
    const cost = container.querySelector("#cost");
    const text = cost?.textContent ?? "";
    expect(text).toContain("You approve every word before it goes live");
    expect(text).toContain("Nothing dials anybody until you launch it");
    expect(text).toContain("Pause it from your dashboard whenever you want");
    // And it may not reach for the thing it does not have. A guarantee, a refund, a
    // no-commitment claim and a trial are each a commercial term nobody has agreed;
    // "free" and "trial" are already banned page-wide by the price rule above.
    expect(text).not.toMatch(/guarantee|money[- ]back|refund|no commitment|risk[- ]free/i);
  });

  /**
   * NO MANUFACTURED URGENCY, anywhere on the page.
   *
   * Scarcity and countdowns are the other half of the playbook this page cannot use, and
   * unlike social proof they are not merely unavailable — they would be false. There are
   * no limited places, no closing date and no offer. Banned by shape rather than by
   * example, because the phrasing varies and the shape does not.
   */
  it("manufactures no urgency or scarcity", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/limited (time|offer|places?|spots?)|only \d+ (left|spots?|places?)/i);
    expect(text).not.toMatch(/act now|hurry|don'?t miss|last chance|ends (soon|today|in)/i);
    expect(text).not.toMatch(/\bwait ?list\b|early bird|founding (member|client)s?/i);
  });
});

describe("the footer's legal links", () => {
  /**
   * THE ONE SURFACE A PAYMENT AGGREGATOR'S REVIEWER LOOKS FOR.
   *
   * Razorpay/Cashfree merchant review checks that the site publishes its terms, privacy,
   * refund and contact pages and that they are REACHABLE — a document at a URL nothing
   * links to reads as absent. The legal documents shipped before anything linked to them,
   * which is the "half-wired feature" CLAUDE.md names: eight real pages, zero ways in.
   *
   * Asserted against `LEGAL_DOCUMENTS` rather than against a list typed here, so a ninth
   * document is covered the moment it is registered. A hand-written expectation would be
   * the second enumeration whose drift this test exists to prevent.
   */
  it("links to every legal document, derived from the registry", () => {
    stubApi({});
    render(<Home />);

    for (const doc of LEGAL_DOCUMENTS) {
      const link = screen.getByRole("link", { name: doc.title });
      expect(link.getAttribute("href")).toBe(`/legal/${doc.slug}`);
    }
  });

  it("groups them in a labelled navigation landmark", () => {
    stubApi({});
    render(<Home />);

    // A bare list of links in a footer is reachable but unnavigable: a screen-reader user
    // moving by landmark needs this group to announce itself, and "Legal" is what
    // distinguishes it from the page's other navigation.
    // `getByRole` throws when absent, so reaching the assertion is most of the proof;
    // the link count is what stops an empty labelled nav from satisfying it.
    const nav = screen.getByRole("navigation", { name: "Legal" });
    expect(nav.querySelectorAll("a").length).toBe(LEGAL_DOCUMENTS.length);
  });
});

/**
 * The ROI calculator — the one priced section, whose honesty is the whole point.
 *
 * The negative bans above are scoped OFF this section (`textOutsideCalculator`), so these
 * positive assertions are what hold the line here: it must show the published self-serve
 * rate, recompute live as the buyer changes an input, and expose the assumptions.
 */
describe("the ROI calculator", () => {
  function calc(container: HTMLElement): HTMLElement {
    const el = container.querySelector<HTMLElement>("[data-roi-calculator]");
    expect(el, "the calculator did not render").not.toBeNull();
    return el as HTMLElement;
  }

  it("shows the published self-serve rate as its Calevate input", () => {
    const { container } = render(<Home />);
    // ₹5.00/min must appear, and it must be inside the calculator (never leaking into the
    // rest of the page, which the no-price bans still guard).
    expect(calc(container).textContent).toContain("₹5.00/min");
  });

  it("computes headcount and recomputes live when call volume changes", () => {
    const { container } = render(<Home />);
    // Two controls share the "Calls a day" name (a number field and a slider); the
    // spinbutton is the one a buyer types into.
    const callsField = screen.getByRole("spinbutton", { name: "Calls a day" });

    // 200 calls ÷ 100/agent = 2 telecallers by default. (The rendered text runs the count
    // straight into the word, so the assertions allow zero spacing.)
    expect(calc(container).textContent).toMatch(/hire\s*2\s*telecallers/);

    fireEvent.change(callsField, { target: { value: "500" } });
    // 500 ÷ 100 = 5, live.
    expect(calc(container).textContent).toMatch(/hire\s*5\s*telecallers/);
    // And the singular is handled: 90 ÷ 100 rounds up to one telecaller — singular, so the
    // word must NOT be followed by an "s".
    fireEvent.change(callsField, { target: { value: "90" } });
    expect(calc(container).textContent).toMatch(/hire\s*1\s*telecaller(?!s)/);
  });

  it("recomputes the Calevate monthly figure as inputs change", () => {
    const { container } = render(<Home />);
    // Default 200 × 26 × 2 min × ₹5 = ₹52,000.00.
    expect(calc(container).textContent).toContain("₹52,000.00");
    fireEvent.change(screen.getByRole("spinbutton", { name: "Calls a day" }), {
      target: { value: "100" },
    });
    // 100 × 26 × 2 × ₹5 = ₹26,000.00.
    expect(calc(container).textContent).toContain("₹26,000.00");
  });

  it("exposes an assumptions disclosure, closed by default and labelled illustrative", () => {
    const { container } = render(<Home />);
    // The calculator now carries two disclosures (the benchmark assumptions and the "How
    // we calculate" note). This asserts the ASSUMPTIONS one — where working days and the
    // telecaller benchmarks now live, collapsed so the two primary inputs stay uncluttered.
    const details = [...calc(container).querySelectorAll("details")];
    expect(details.length).toBeGreaterThan(0);
    const disclosure = details.find((d) =>
      /assumptions/i.test(d.querySelector("summary")?.textContent ?? ""),
    );
    expect(disclosure, "the assumptions disclosure did not render").toBeDefined();
    expect(disclosure!.open).toBe(false);
    expect(disclosure!.querySelector("summary")?.textContent).toMatch(/assumptions/i);
    // The honesty note the brief requires: the benchmarks are framed as illustrative and
    // adjustable, not asserted as fact.
    expect(disclosure!.textContent).toMatch(/pre-filled with illustrative benchmarks/i);
  });

  /**
   * THE TWO-STAGE MODE — the comparison that is honest once a call is a sales
   * conversation rather than an enquiry being written down.
   *
   * The head-to-head mode compares Calevate against a telecaller on the SAME calls, which
   * at six minutes compares two things nobody was ever choosing between: the alternative
   * to a closer is not a cheaper closer. The second mode compares a team working the whole
   * list against a team working only the qualified share of it. These assertions pin the
   * default (the head-to-head, because the default call length here is two minutes), the
   * shape of the extra controls, the worked arithmetic, and — the load-bearing one — that
   * the verdict still admits a loss.
   */
  function chooseTwoStage() {
    fireEvent.click(screen.getByRole("radio", { name: /Calevate calls first/i }));
  }

  it("defaults to the head-to-head comparison and offers the two-stage one", () => {
    render(<Home />);
    const group = screen.getByRole("radiogroup", { name: "What you want Calevate to do" });
    expect(group).not.toBeNull();
    const answers = screen.getByRole("radio", { name: /Calevate answers the calls/i });
    const qualifies = screen.getByRole("radio", { name: /Calevate calls first/i });
    expect(answers.getAttribute("aria-checked")).toBe("true");
    expect(qualifies.getAttribute("aria-checked")).toBe("false");
    // The two-stage inputs are progressive disclosure: absent until the mode is chosen, so
    // the everyday buyer is never handed five sliders they did not ask for.
    expect(screen.queryByRole("spinbutton", { name: "Leads worth a real conversation" })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Calevate's first call" })).toBeNull();
  });

  it("reveals exactly two extra controls in the two-stage mode, both labelled", () => {
    render(<Home />);
    chooseTwoStage();
    expect(screen.getByRole("radio", { name: /Calevate calls first/i }).getAttribute("aria-checked")).toBe("true");
    // Labelled number field AND slider for each, the same pair every other input uses.
    expect(screen.getByRole("spinbutton", { name: "Leads worth a real conversation" })).not.toBeNull();
    expect(screen.getByRole("slider", { name: "Leads worth a real conversation" })).not.toBeNull();
    expect(screen.getByRole("spinbutton", { name: "Calevate's first call" })).not.toBeNull();
    expect(screen.getByRole("slider", { name: "Calevate's first call" })).not.toBeNull();
    // And the call-length control is renamed, because in this mode it is the SALESPERSON's
    // conversation rather than the agent's call — the same number meaning a different thing
    // is the bug this rename exists to prevent.
    expect(
      screen.getByRole("spinbutton", { name: "How long a real sales conversation runs" }),
    ).not.toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "Average call length" })).toBeNull();
  });

  it("shows the worked two-stage arithmetic at 200 calls a day and 6-minute conversations", () => {
    const { container } = render(<Home />);
    chooseTwoStage();
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "How long a real sales conversation runs" }),
      { target: { value: "6" } },
    );
    const text = calc(container).textContent ?? "";
    // Four salespeople on the whole list at ₹1,48,000 …
    expect(text).toMatch(/hire\s*4\s*salespeople/);
    expect(text).toContain("₹1,48,000.00");
    // … versus ₹52,000 of first calls plus two salespeople at ₹74,000 = ₹1,26,000.
    expect(text).toContain("₹52,000.00");
    expect(text).toContain("₹74,000.00");
    expect(text).toContain("₹1,26,000.00");
    expect(text).toContain("₹22,000.00");
    // The capacity line — the actual argument, and pure arithmetic off the buyer's inputs.
    expect(text).toMatch(/3,640[^]*never reach a person/);
    expect(text).toMatch(/364[^]*hours a month/);
  });

  it("says so plainly when the two-stage funnel costs MORE", () => {
    const { container } = render(<Home />);
    chooseTwoStage();
    // Everything on the list worth a conversation = nothing for a first call to filter, so
    // it is an extra call on top of the same team. A calculator that cannot lose is a
    // brochure; this is the branch that proves it can.
    fireEvent.change(screen.getByRole("spinbutton", { name: "Leads worth a real conversation" }), {
      target: { value: "100" },
    });
    expect(calc(container).textContent).toMatch(/costs\s*₹[\d,]+\.\d\d\s*more a month, not less/);
  });

  it("points a long-call buyer at the two-stage mode instead of losing the argument", () => {
    const { container } = render(<Home />);
    // At six minutes the head-to-head comparison is not a comparison of alternatives. The
    // page must name that rather than quietly showing a losing number.
    expect(calc(container).textContent).not.toMatch(/is a sales conversation/);
    fireEvent.change(screen.getByRole("spinbutton", { name: "Average call length" }), {
      target: { value: "6" },
    });
    expect(calc(container).textContent).toMatch(/6-minute call is a\s*sales conversation/);
  });

  it("offers the missed-lead value as an opt-in, off by default", () => {
    const { container } = render(<Home />);
    const toggle = screen.getByRole("checkbox", {
      name: /value of the leads at stake/i,
    });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    // The conversion-rate input is only present once the option is turned on.
    expect(screen.queryByRole("spinbutton", { name: "Conversion rate" })).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByRole("spinbutton", { name: "Conversion rate" })).not.toBeNull();
    expect(calc(container).textContent).toMatch(/converted-lead value/i);
  });
});
