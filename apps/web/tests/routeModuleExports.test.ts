/**
 * A Next.js route module exports `default` and route fields — nothing else (D-196).
 *
 * `next build` type-checks page and layout modules against a fixed export shape, and a
 * stray named export fails the PRODUCTION BUILD with a message that names neither a line
 * nor a cause beyond *"X is not a valid Page export field"*. That is what happened:
 * `deliveryRowKeys` was exported from `lead-sources/page.tsx` so it could be tested, and
 * the build broke — after `tsc --noEmit`, `eslint` and 1146 vitest tests had all passed,
 * because none of them knows the rule.
 *
 * WHY THIS AND NOT `next build` IN `make web-check`. That target's comment argued the
 * build "catches a different class of thing... so paying for it in the dev loop buys
 * nothing this target does not already have", and this defect is the counter-example. But
 * the honest reading is narrower than "run the build every time": the build is ~30s and
 * mostly re-proves what `tsc` just proved, whereas the rule that actually escaped is
 * syntactic and checkable in milliseconds. So the guard is the rule, not the build.
 *
 * It is a floor, not a ceiling: `next build` still runs in CI and still owns the classes
 * this cannot see (bundle validity, server/client boundary violations, route collisions).
 *
 * ## CORRECTION, measured: on a client-component LAYOUT, `next build` checks nothing
 *
 * The first line above says the build "type-checks page and layout modules against a fixed
 * export shape". That is true of every page and of a SERVER layout, and false of the two
 * layouts this repository actually has. Comparing `src/app/**` with the validators Next
 * emits into `.next/types/app/**` on this tree:
 *
 *     every page.tsx              -> validator emitted
 *     src/app/layout.tsx          -> validator emitted
 *     src/app/admin/layout.tsx    -> NONE
 *     src/app/c/[slug]/layout.tsx -> NONE
 *
 * The two without one are the two carrying `"use client"`, and the experiment closes the
 * loop: delete that directive from `admin/layout.tsx` and rebuild, and
 * `.next/types/app/admin/layout.ts` appears. Next 15.5.21 emits no route-type validator for
 * a client-component layout while emitting one for a client-component page.
 *
 * Driven both ways: an extra export added to `c/[slug]/attention/page.tsx` fails
 * `next build` with *"sabotageRowKeys is not a valid Page export field"*; the same export
 * added to `c/[slug]/layout.tsx` builds GREEN, and only this test objects.
 *
 * So for the two files every screen in the product renders inside — the client shell and
 * the operator shell — this guard is not a faster copy of the build. It is the only check
 * there is, and it must not be deleted on the belief that the build would catch it.
 * (D-223.)
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_DIR = join(import.meta.dirname, "..", "src", "app");

/**
 * What Next.js 15's App Router permits a page or layout to export besides `default`.
 *
 * Deliberately a CLOSED list read from the framework's route-segment-config docs rather
 * than a heuristic like "anything not lowercase": a heuristic would have let
 * `deliveryRowKeys` through, since it is a perfectly ordinary camelCase name.
 */
const ROUTE_FIELDS = new Set([
  "dynamic",
  "dynamicParams",
  "revalidate",
  "fetchCache",
  "runtime",
  "preferredRegion",
  "maxDuration",
  "metadata",
  "generateMetadata",
  "viewport",
  "generateViewport",
  "generateStaticParams",
  "experimental_ppr",
  "config",
]);

function routeModules(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      found.push(...routeModules(full));
    } else if (/^(page|layout|template|error|loading|not-found)\.tsx?$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

/** Named exports in a module, by source scan. `export default` is not one of them. */
function namedExports(source: string): string[] {
  const names: string[] = [];
  // `export function x`, `export const x`, `export async function x`, `export class x`.
  for (const m of source.matchAll(/^export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)/gm)) {
    names.push(m[1]);
  }
  // `export { a, b }` — the re-export form, which is just as invalid on a page.
  for (const m of source.matchAll(/^export\s*\{([^}]*)\}/gm)) {
    for (const part of m[1].split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop()?.trim();
      if (name) names.push(name);
    }
  }
  return names;
}

describe("Next.js route modules", () => {
  const modules = routeModules(APP_DIR);

  it("finds the route modules at all, so an empty sweep cannot pass", () => {
    // Without this, a broken `routeModules` would return [] and the test below would be
    // a green assertion about nothing — the failure mode that lets a guard rot silently.
    expect(modules.length).toBeGreaterThan(20);
  });

  it("export only `default` and route-segment fields", () => {
    const offenders: string[] = [];
    for (const file of modules) {
      const source = readFileSync(file, "utf8");
      for (const name of namedExports(source)) {
        if (!ROUTE_FIELDS.has(name)) {
          offenders.push(`${file.slice(APP_DIR.length + 1)} exports \`${name}\``);
        }
      }
    }
    expect(
      offenders,
      "a page/layout may export only `default` and Next.js route fields — move helpers " +
        "into `src/lib/`, or `next build` fails with a message that names no line",
    ).toEqual([]);
  });

  /**
   * NOTHING MAY RE-ENABLE PRERENDERING, and the reason is the enforced CSP.
   *
   * `src/app/layout.tsx` exports `dynamic = "force-dynamic"` and the comment above it says
   * why: the policy `src/middleware.ts` serves carries a per-request nonce, and an inline
   * `<script>` with no nonce is refused whatever `'self'` says — a host-source expression
   * has never permitted an inline script. A statically prerendered App Router route ships
   * its RSC payload as exactly that: bare `self.__next_f.push(...)` tags baked into the
   * HTML at build time, minted before any request and so before any nonce exists. The
   * result is not a subtle degradation; it is a blank page, and it has already been a
   * production white screen once.
   *
   * `force-dynamic` on the ROOT layout covers every route in the tree — which is what makes
   * the failure mode so quiet, because re-opening the hole does not mean deleting that line.
   * A single `export const dynamic = "force-static"`, a `revalidate`, or a `dynamicParams`
   * on any one page re-enables prerendering for that segment, and the page that breaks is
   * the one nobody opened during review. (`legal/[slug]/page.tsx` exports
   * `generateStaticParams`, which is inert under the root's `force-dynamic` and is left
   * alone deliberately: it describes the slug set and prerenders nothing while the root
   * says dynamic.)
   *
   * So the caching fields are legal on the ROOT LAYOUT and nowhere else. If a route ever
   * genuinely needs to be static, the nonce has to stop being the mechanism first.
   */
  it("lets only the root layout speak about rendering mode, so nothing re-prerenders", () => {
    const CACHING = new Set(["dynamic", "dynamicParams", "revalidate", "fetchCache", "experimental_ppr"]);
    const rootLayout = join(APP_DIR, "layout.tsx");
    expect(
      namedExports(readFileSync(rootLayout, "utf8")),
      "the root layout must keep `export const dynamic` — removing it serves every route " +
        "prerendered RSC scripts with no nonce, which the enforced CSP blocks",
    ).toContain("dynamic");
    expect(readFileSync(rootLayout, "utf8")).toContain('dynamic = "force-dynamic"');

    const offenders: string[] = [];
    for (const file of modules) {
      if (file === rootLayout) continue;
      for (const name of namedExports(readFileSync(file, "utf8"))) {
        if (CACHING.has(name)) offenders.push(`${file.slice(APP_DIR.length + 1)} exports \`${name}\``);
      }
    }
    expect(
      offenders,
      "only `src/app/layout.tsx` may set a rendering-mode field — see the comment above",
    ).toEqual([]);
  });
});

