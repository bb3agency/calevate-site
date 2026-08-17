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
describe("the landing page's claims", () => {
  it("names no price, plan or fee", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
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
    expect(container.querySelectorAll("img").length).toBe(0);
  });

  it("claims no uptime, accuracy or answer-rate figure", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(text).not.toMatch(/uptime|99\.9|accuracy|instantly|milliseconds/i);
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
   * The narrower claim that replaced it is the one SECURITY-COMPLIANCE §4 makes in its
   * own words — model endpoints pinned to an Indian region — and it is guarded on the
   * backend by `scripts/check_model_residency.py`. This test is the frontend half:
   * residency is the claim a buyer in this market asks for FIRST, which is exactly why
   * it grows back, and a softened verb over the same implication is the same
   * misrepresentation. Certifications are in the same list because the company holds
   * none.
   */
  it("claims no data residency, storage location or certification", () => {
    const { container } = render(<Home />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/stays? in india|remains? in india|never leaves india/i);
    expect(text).not.toMatch(/stored in india|hosted in india|kept in india|held in india/i);
    expect(text).not.toMatch(/data residency|data sovereignty|sovereign/i);
    expect(text).not.toMatch(/soc\s?2|iso[\s-]?27001|hipaa|pci[\s-]?dss|certified|accredited/i);
    // The one surviving India claim is about MODEL ENDPOINTS, and it must stay attached
    // to the thing that enforces it rather than drifting into a claim about our storage.
    expect(text).toContain("The AI runs on Indian endpoints");
    expect(text).not.toMatch(/(recordings?|transcripts?|database|servers?)[^.]{0,40}\bin india\b/i);
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
