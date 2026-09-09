import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * The browser accessibility gate's runner — deliberately a SECOND config, not a second
 * mode of the first.
 *
 * `vitest.config.mts` runs 156 files under jsdom, in parallel workers, in about two and a
 * half minutes. This one runs a single file that boots a Next server and drives a real
 * Chromium; it needs a node environment, no `tests/setup.ts` (which installs jsdom-shaped
 * globals), no parallelism, and a much larger timeout. Folding those into the main config
 * would mean every unit test paid for settings only this file needs, and one `--exclude`
 * away from silently not running at all.
 *
 * The file is named `*.browsertest.ts` rather than `*.test.ts` so the main config's
 * `include` cannot pick it up; `vitest.config.mts` also excludes this directory outright,
 * because relying on a glob near-miss to keep a two-minute browser run out of the unit
 * suite is the kind of implicit coupling that breaks silently.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    globals: false,
    include: ["tests/browser/**/*.browsertest.ts"],
    // One browser, one server, one file. Threads would fight over the port and the
    // binary for no gain — the cost here is navigation, not CPU.
    fileParallelism: false,
    // A cold `next dev` compiles each route on first request; thirteen of them plus 52
    // axe runs is minutes, not seconds. The hook budget in the file itself is what
    // actually bounds the boot.
    testTimeout: 120_000,
    hookTimeout: 900_000,
    // THE SUMMARY THIS GATE PRINTS IS PART OF THE GATE, so it goes straight to stdout.
    // Vitest's default reporter buffers a passing test's console output and, in a
    // non-TTY run (which is every CI run and every `make web-check`), drops it — so the
    // "here is what actually ran" block never reached the log. A gate whose evidence is
    // invisible is one a reader has to take on trust, which is the thing this file is
    // built not to ask for.
    disableConsoleIntercept: true,
    // `include` above is the whole surface, but an empty run must never read as a pass:
    // vitest exits non-zero when no test file matches, and this keeps that behaviour
    // explicit rather than inherited.
    passWithNoTests: false,
  },
});
