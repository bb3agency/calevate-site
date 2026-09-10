import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { relPosix, toPosix } from "./repoPaths";

/**
 * A COMPONENT NOBODY IMPORTS IS EITHER UNFINISHED WORK OR A SECOND WAY TO DO SOMETHING.
 *
 * ## What this used to scan, and why that was not enough
 *
 * This guard covered `src/components/interior/` only, where fifteen of nineteen
 * behavioural primitives — about 5,000 lines — are imported by nothing. It caught that
 * class exactly once and then stopped at a directory boundary, so it was blind to the
 * three orphans a later audit found by hand:
 *
 * - `components/deployButton.tsx` — 105 lines, zero importers, and named in
 *   `docs/UX-DOCTRINE.md` §7 under "Also shared, and equally binding", which pointed the
 *   next engineer at a primitive no screen had ever rendered. Deleted.
 * - `components/marketing/isometric.tsx` — 442 lines and five exported figures, orphaned
 *   when the homepage was rebuilt. Deleted; the one file that borrowed its geometry had
 *   already re-derived it and says so.
 * - `app/admin/ops/opsLanguage.tsx::DangerZone` — an exported component with no importer,
 *   which is a class this scan CANNOT see: it is one symbol inside a module a dozen
 *   panels import. It was adopted by `OutboundHaltPanel`, the lever it was written for.
 *
 * So the scan is now the whole of `src/components/**`, which is the directory the
 * doctrine calls shared and binding, and the quarantine list below is scoped to the
 * subtree it was written about. A module-level scan is what a cheap guard can prove; the
 * symbol-level orphan above is why it is not the only thing a reviewer looks for.
 *
 * ## Why this is a quarantine list and not a deletion
 *
 * Whether the fifteen in `interior/` are staged for a redesign or are leftovers is a
 * question this suite cannot answer, and deleting 5,000 lines on a guess is the more
 * expensive mistake. So the list states the fact rather than the verdict, and the test
 * makes the answer DELIBERATE in both directions:
 *
 *  - a component nobody imports that is NOT named below fails — so the next unconsumed
 *    component is caught on the day it lands, not in an audit;
 *  - a file NAMED below that has since gained a consumer, or has been deleted, ALSO
 *    fails — so the list cannot rot into an amnesty for the directory.
 *
 * The list may only shrink, by adopting a component (it gets a consumer) or by deleting
 * it. It may not grow without an argument written beside the entry.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const COMPONENTS = join(WEB_ROOT, "src/components");

/**
 * Written, imported by nothing, and awaiting a decision — adopt or delete. Not an
 * amnesty: see the header. Each is a path under `src/components/`, without its extension.
 */
const AWAITING_A_DECISION = [
  "interior/collapsible-banner",
  "interior/dropdown",
  "interior/floating-label",
  "interior/live-activity",
  "interior/loading-button",
  "interior/new-items-pill",
  "interior/otp-input",
  "interior/progress-bar",
  "interior/show-more",
  "interior/skeleton-swap",
  "interior/sticky-header",
  "interior/streaming-text",
  "interior/task-steps",
  "interior/tree-view",
  "interior/wizard-steps",
];

function filesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...filesUnder(path));
    else if (path.endsWith(".ts") || path.endsWith(".tsx")) found.push(path);
  }
  return found;
}

/** Every module under `src/components/`, as a `/` path without its extension. */
const MODULES = filesUnder(COMPONENTS).map((path) =>
  relPosix(COMPONENTS, path).replace(/\.tsx?$/, ""),
);

/**
 * Which of them are imported, read from the IMPORT SPECIFIER rather than from the file
 * text: a docstring naming `SkeletonSwap` is not a consumer, and that is the mistake
 * `tests/sourceScan.ts` exists because three guards already made.
 *
 * Two specifier shapes reach a component and both are counted, because either one keeps a
 * module alive: the alias (`@/components/x/y`, how the app imports) and a relative path
 * (`./sibling`, how components inside one folder import each other). A relative specifier
 * is resolved against the importing FILE, so a `./band` in `marketing/home/` credits
 * `marketing/home/band` and never a `band` somewhere else.
 */
const IMPORT_SPECIFIER = /from\s+["']([^"']+)["']/g;

/** The module a specifier names, as a `src/components`-relative path, or null. */
function resolveToComponent(fromFile: string, specifier: string): string | null {
  if (specifier.startsWith("@/components/")) {
    return specifier.slice("@/components/".length);
  }
  if (!specifier.startsWith(".")) return null;
  const target = resolve(dirname(fromFile), specifier);
  const rel = toPosix(relative(COMPONENTS, target));
  return rel === "" || rel.startsWith("..") ? null : rel;
}

function consumed(): Set<string> {
  const names = new Set<string>();
  const sources = [...filesUnder(join(WEB_ROOT, "src")), ...filesUnder(join(WEB_ROOT, "tests"))];
  for (const path of sources) {
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(IMPORT_SPECIFIER)) {
      const name = resolveToComponent(path, match[1]);
      // A module never counts as its own consumer — `./x` from `x.tsx`'s own folder is a
      // sibling, but a self-import is not a thing, and the extension-less form makes the
      // two indistinguishable without this.
      if (name !== null && name !== relPosix(COMPONENTS, path).replace(/\.tsx?$/, "")) {
        names.add(name);
      }
    }
  }
  return names;
}

describe("every component in src/components is either used or accounted for", () => {
  it("reads a directory that is actually there", () => {
    // The premise check every source scan in this suite carries: a scan that stopped
    // matching is indistinguishable from a clean tree (see `tests/repoPaths.ts`).
    expect(MODULES.length).toBeGreaterThan(40);
    expect(MODULES).toContain("ui");
  });

  it("has no unconsumed component that nobody has decided about", () => {
    const used = consumed();
    const orphans = MODULES.filter(
      (name) => !used.has(name) && !AWAITING_A_DECISION.includes(name),
    );
    expect(orphans).toEqual([]);
  });

  it("keeps the quarantine list honest — nothing on it is used, and nothing on it is gone", () => {
    const used = consumed();
    const adopted = AWAITING_A_DECISION.filter((name) => used.has(name));
    expect(adopted, "these now have consumers — take them off the list").toEqual([]);
    const missing = AWAITING_A_DECISION.filter((name) => !MODULES.includes(name));
    expect(missing, "these no longer exist — take them off the list").toEqual([]);
  });
});
