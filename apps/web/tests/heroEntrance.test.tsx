import { render } from "@testing-library/react";
import gsap from "gsap";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import WhyCalevatePage from "@/app/why-calevate/page";
import { Reveal, SmoothScroll } from "@/components/marketing/motion";

/**
 * THE FIRST VIEWPORT IS NEVER ANIMATED BY SCRIPT.
 *
 * The server paints the hero before the bundle runs. A `gsap.from()` on it at hydration
 * snapped the painted hero back to opacity 0 and played it in again, which the founder saw
 * as the page loading twice (15 Oct 2026). The hero's entrance is a CSS keyframe carried by
 * the server markup, and `Reveal` leaves alone anything already in view when it mounts.
 *
 * `tests/setup.ts` reports reduced motion, under which no GSAP code runs at all, so these
 * tests switch the query to `no-preference`: the branch that replayed the hero.
 */

vi.mock("lenis", () => ({
  default: class {
    on() {}
    raf() {}
    destroy() {}
  },
}));

const reducedMotionQuery = window.matchMedia;

beforeEach(() => {
  window.matchMedia = ((query: string) => ({
    ...reducedMotionQuery(query),
    matches: false,
  })) as typeof window.matchMedia;
});

afterEach(() => {
  window.matchMedia = reducedMotionQuery;
  vi.restoreAllMocks();
});

describe("the hero's entrance", () => {
  it("is in the server markup, on every block of the home hero", async () => {
    const html = renderToStaticMarkup(await Home());
    const doc = new DOMParser().parseFromString(html, "text/html");
    const h1 = doc.querySelector("h1");
    expect(h1?.classList.contains("mk-hero-in")).toBe(true);
    const hero = h1?.parentElement;
    const blocks = [...(hero?.children ?? [])];
    expect(blocks.length).toBeGreaterThan(1);
    for (const block of blocks) expect(block.classList.contains("mk-hero-in")).toBe(true);
  });

  it("is in the server markup of the interior hero, product shot included", async () => {
    const html = renderToStaticMarkup(await WhyCalevatePage());
    const doc = new DOMParser().parseFromString(html, "text/html");
    expect(doc.querySelector("h1")?.classList.contains("mk-hero-in")).toBe(true);
    expect(doc.querySelector('.mk-hero-in [role="img"]')).not.toBeNull();
  });

  it("is never handed to GSAP after hydration", async () => {
    const from = vi.spyOn(gsap, "from").mockImplementation(() => ({}) as gsap.core.Tween);
    const { container } = render(await Home());
    const h1 = container.querySelector("h1");
    expect(h1).not.toBeNull();
    const hero = h1?.closest("section");
    for (const [targets] of from.mock.calls) {
      for (const target of gsap.utils.toArray<Element>(targets)) {
        expect(hero?.contains(target), "GSAP was given an element of the hero").toBe(false);
      }
    }
    expect(h1?.getAttribute("style")).toBeNull();
  });
});

describe("Reveal", () => {
  function placeAt(top: number) {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      top,
      bottom: top + 100,
      left: 0,
      right: 100,
      width: 100,
      height: 100,
      x: 0,
      y: top,
      toJSON: () => ({}),
    });
  }

  it("leaves an element that is already in view as the server painted it", () => {
    placeAt(100);
    const from = vi.spyOn(gsap, "from").mockImplementation(() => ({}) as gsap.core.Tween);
    render(
      <SmoothScroll>
        <Reveal>Visible at load</Reveal>
      </SmoothScroll>,
    );
    expect(from).not.toHaveBeenCalled();
  });

  it("animates an element below the fold on scroll", () => {
    placeAt(window.innerHeight + 400);
    const from = vi.spyOn(gsap, "from").mockImplementation(() => ({}) as gsap.core.Tween);
    render(
      <SmoothScroll>
        <Reveal>Further down</Reveal>
      </SmoothScroll>,
    );
    expect(from).toHaveBeenCalledTimes(1);
    expect(from.mock.calls[0]?.[1]).toMatchObject({ scrollTrigger: { once: true } });
  });
});
