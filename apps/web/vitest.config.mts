import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * The frontend's test harness — the gate `tsc` cannot be.
 *
 * Until this existed, every guarantee `apps/web` had rested on the type checker, ESLint
 * and a successful `next build`. None of those can see a RULE ABOUT BEHAVIOUR, and this
 * app is now carrying several that are load-bearing and compliance-shaped: a hold that
 * must fail CLOSED on an unknown rule, a hold-queue lookup that must fail VISIBLE on
 * one, verdicts that must key on the server's `is_verified`/`messageable`/`held` rather
 * than on `status`, and money that must never become a JS number. Every one of those
 * type-checks perfectly while being wrong, and several of them WERE wrong in an earlier
 * draft. `tests/` is where they get asserted; this file is what runs it.
 *
 * ## Toolchain, and what was deliberately left out
 *
 * Vitest, not Jest. Next.js's own testing guide ships a Vitest setup, and for a fresh
 * TypeScript/ESM codebase Vitest is the current default — native ESM, no `ts-jest` or
 * `babel-jest` layer to keep in step with the compiler. Jest remains the right answer
 * for a large suite already written against it; there is no such suite here.
 *
 * Everything below the runner is chosen to keep the dependency tree SMALL, because
 * adding dependencies is exactly the activity hard rule 9 governs and this repo has an
 * incident report about it (`incident_report.md`: a transitive package with a
 * `postinstall` script, waved through into `allowBuilds`). Four direct devDependencies
 * went in — `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/dom` — and
 * three conventional ones were deliberately NOT taken:
 *
 * - **`@vitejs/plugin-react`** — the standard scaffold's JSX plugin. Its job here would
 *   be to override `tsconfig.json`'s `"jsx": "preserve"` (which Next requires and Vite
 *   would otherwise honour, emitting untransformed JSX). `oxc.jsx` below does that in
 *   one line and keeps a Babel toolchain out of the tree entirely. If this file ever
 *   needs Fast Refresh or the React Compiler, take the plugin — it is the standard and
 *   the reason to depart from it is only ever the dependency count.
 * - **`vite-tsconfig-paths`** — one package to read one `paths` entry. The alias is
 *   below, spelled out.
 * - **`@testing-library/jest-dom`** — matcher sugar (`toBeInTheDocument`). The
 *   assertions in `tests/` are about the presence and the COUNT of specific sentences,
 *   which `queryAllByText(...).length` states directly and without a fourth dependency.
 *
 * `jsdom` is a direct devDependency because Vitest 4 no longer auto-installs the
 * environment package (v4 migration guide) — an implicit one is a CI-only failure.
 */
export default defineConfig({
  // Vite 8 transforms with oxc rather than esbuild. `automatic` is React 17+'s JSX
  // runtime, which is what React 19 wants and what Next compiles the same files with.
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    // No `globals: true`: it would need `vitest/globals` added to tsconfig `types`,
    // which puts `describe`/`it` in scope for the APPLICATION's type check too. Tests
    // import what they use, like every other module in this repo.
    globals: false,
    setupFiles: ["./tests/setup.ts"],
    // Tests live in `tests/`, never beside the component. A `page.test.tsx` inside
    // `src/app/` is a file Next's router walks and `next build` type-checks as route
    // code; keeping the suite out of the route tree removes the question entirely.
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    // Every test that stubs `fetch` or a clock gets it undone for the next one, from
    // here rather than from a hand-written `afterEach` each file could forget.
    restoreMocks: true,
    unstubGlobals: true,
    /**
     * HEADROOM ABOVE `asyncUtilTimeout`, WITHOUT WHICH THAT SETTING CANNOT BE SPENT.
     *
     * `tests/setup.ts` raises RTL's `findBy`/`waitFor` budget to 5000ms and argues the case
     * — 93 files across parallel workers, and the slowest render in a loaded run is nowhere
     * near the slowest in an isolated one. Vitest's own `testTimeout` DEFAULTS TO 5000 too,
     * so the two were equal and the RTL budget was unreachable: a `findBy` that needed even
     * a second of real waiting killed the test on vitest's clock first, and reported it as
     * "Test timed out" rather than as the assertion that was still waiting.
     *
     * That is not hypothetical — it is what a loaded box produced here, on a test whose
     * only fault was waiting for a query instead of assuming it had already landed.
     *
     * RAISING IT WEAKENS NOTHING, which is `setup.ts`'s own argument for the same move: a
     * wrong render still fails on its assertion, and `findBy` returns the moment the DOM
     * matches. What this buys is that a slow run reports the real failure instead of a
     * timeout, and that the 5000ms above means what it says.
     */
    testTimeout: 15_000,
  },
});
