import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

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
