import { onlineManager } from "@tanstack/react-query";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/**
 * Put the browser back online after a test that took it offline (`browserOffline`).
 *
 * `onlineManager` is a MODULE-LEVEL singleton in query-core, so a test that leaves it
 * false hands the next file a tree where nothing ever fetches — which shows up as an
 * unrelated timeout in an unrelated suite, the worst kind of failure to read.
 *
 * Registered BEFORE `cleanup` on purpose: Vitest runs `afterEach` hooks in reverse
 * registration order ("stack" is the default `sequence.hooks`), so this one runs LAST —
 * after the tree is unmounted, so resuming the paused queries cannot fetch into a
 * torn-down component with the `fetch` stub already gone.
 */
afterEach(() => {
  onlineManager.setOnline(true);
});

/**
 * Unmount between tests.
 *
 * React Testing Library auto-registers this when `globals: true`, which we do not use
 * (see `vitest.config.mts`). Without it every render stays in the document and
 * `getByText` starts matching the PREVIOUS test's DOM — which shows up as a test that
 * passes for the wrong reason, the one failure mode a suite must not have.
 */
afterEach(cleanup);

/**
 * The App Router's client hooks, stubbed at the FRAMEWORK boundary and nowhere else.
 *
 * `ClientRealmProvider` (lib/api/session.tsx) reads `useSearchParams()` to decide
 * whether this tab is a D-22 "view as client" handoff. Outside a running Next app that
 * hook throws, so a page cannot be rendered at all without this. Everything BELOW the
 * boundary — the provider, the session it builds, `apiRequest`, the query hooks, the
 * predicates — stays real, because those are the things under test; the repo's rule is
 * fixtures over mocks-of-our-own-code (ENGINEERING-PRACTICES §3) and this obeys it.
 *
 * Registered here rather than per file so no test can forget it and get a confusing
 * "invariant expected app router to be mounted" instead of its assertion.
 */
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * `window.matchMedia`, which jsdom does not implement at all.
 *
 * Registered here rather than per file for the reason above: without it, importing the
 * marketing page fails inside GSAP's `registerPlugin` — a stack trace through
 * `gsap-core.js` that says nothing about the missing browser API, on a test that was
 * about the page's copy.
 *
 * IT REPORTS "reduce", and that is the truthful answer rather than a convenience.
 * jsdom has no layout, no compositor and no scrolling, so there is no smooth scroll for
 * Lenis to drive and no viewport for a ScrollTrigger to intersect — constructing them
 * here does not exercise the animation, it just crashes on browser APIs jsdom does not
 * implement.
 *
 * What this makes the suite test is the STATIC page: the exact markup a reader who asked
 * for reduced motion receives, and the exact markup that renders if the bundle never
 * loads. That is the branch worth pinning, because the design rule for the marketing
 * page is that motion is an enhancement and the page is finished without it — so the
 * a11y sweep and the copy tests asserting against the un-animated DOM is the assertion,
 * not a limitation. Content is visible by default and GSAP animates FROM a displaced
 * state, so nothing here is hidden by the choice.
 *
 * A jsdom gap, not a stub of our own code — ENGINEERING-PRACTICES §3's rule is about
 * not mocking things under test, and this is neither.
 */
Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: (query: string): MediaQueryList =>
    ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }) as unknown as MediaQueryList,
});

/**
 * How long `findBy*`/`waitFor` wait before calling it a failure.
 *
 * RTL's default is 1000ms, which is a statement about how fast a machine is rather than
 * about whether the code is right — and this suite runs 88 files across parallel workers,
 * so the slowest render in a loaded run is nowhere near the slowest render in an isolated
 * one. Two tests proved it: `shellCounters`'s 503 branch and `wireLookup`'s prototype-key
 * branch passed alone, failed inside the full suite, and failed again in CI. Both assert
 * an END STATE that needs a query to settle, so the only thing the old budget measured
 * was the box.
 *
 * RAISING IT WEAKENS NOTHING. A wrong render still fails, because the assertion is
 * unchanged and `findBy` returns the moment the DOM matches — the budget is a CEILING on
 * waiting, not a delay. What it costs is the wall-clock of a genuinely broken test, which
 * is paid once per real failure rather than at every green run.
 *
 * It is deliberately NOT a per-call `{ timeout }` at the two sites that flaked: those two
 * are the ones that happened to lose the race first, and a fix scoped to them would leave
 * every other `findBy` in the suite carrying the same latent flake. One place, one rule.
 */
configure({ asyncUtilTimeout: 5000 });
