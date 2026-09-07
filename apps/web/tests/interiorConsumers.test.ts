import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * A COMPONENT NOBODY IMPORTS IS EITHER UNFINISHED WORK OR A SECOND WAY TO DO SOMETHING.
 *
 * `src/components/interior/` holds nineteen components. FOUR are imported by the app
 * (`toaster`, `load-more`, `pagination`, `tabs`); the other FIFTEEN — about 5,000 lines —
 * are imported by nothing at all. (An audit put the number at fourteen and named
 * `wizard-steps` as live; it is not — the only mention of it outside its own file is a
 * comment in `copilot/CopilotPanel.tsx`, which is why this scan reads import specifiers
 * rather than file text. `collapsible-banner` is unconsumed for the same reason and was
 * missed for the same one.) Several of them duplicate a
 * primitive that IS live: `LoadingButton` beside `ActionButton` + `PRIMARY_BUTTON`,
 * `SkeletonSwap` beside `ui.Skeleton`, `tabs` beside the hand-rolled tablist on the
 * billing screen. Nobody experiences that directly. What it costs is the next engineer:
 * they find two spellings of one thing, pick either, and the console grows a third.
 *
 * ## Why this is a quarantine list and not a deletion
 *
 * Whether those fifteen are staged for a redesign or are leftovers is a question this
 * suite cannot answer, and deleting 5,000 lines on a guess is the more expensive mistake.
 * So the list below states the fact rather than the verdict, and the test makes the answer
 * DELIBERATE in both directions:
 *
 *  - a file in `interior/` that nobody imports and that is NOT named below fails —
 *    so the next unconsumed component is caught on the day it lands, not in an audit;
 *  - a file NAMED below that has since gained a consumer, or has been deleted, ALSO
 *    fails — so the list cannot rot into an amnesty for the whole directory.
 *
 * The list may only shrink, by adopting a component (it gets a consumer) or by deleting
 * it. It may not grow without an argument written beside the entry.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const INTERIOR = join(WEB_ROOT, "src/components/interior");

/**
 * Written, imported by nothing, and awaiting a decision — adopt or delete. Not an
 * amnesty: see the header. Each is a module name under `components/interior/`.
 */
const AWAITING_A_DECISION = [
  "collapsible-banner",
  "dropdown",
  "floating-label",
  "live-activity",
  "loading-button",
  "new-items-pill",
  "otp-input",
  "progress-bar",
  "show-more",
  "skeleton-swap",
  "sticky-header",
  "streaming-text",
  "task-steps",
  "tree-view",
  "wizard-steps",
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

/** Every module name in `components/interior/`, without its extension. */
const MODULES = readdirSync(INTERIOR)
  .filter((name) => name.endsWith(".tsx") || name.endsWith(".ts"))
  .map((name) => name.replace(/\.tsx?$/, ""));

/**
 * Which of them are imported, read from the IMPORT SPECIFIER rather than from the file
 * text: a docstring naming `SkeletonSwap` is not a consumer, and that is the mistake
 * `tests/sourceScan.ts` exists because three guards already made.
 */
const IMPORT_OF_INTERIOR = /from\s+["'][^"']*components\/interior\/([\w-]+)["']/g;

function consumed(): Set<string> {
  const names = new Set<string>();
  const sources = [
    ...filesUnder(join(WEB_ROOT, "src")),
    ...filesUnder(join(WEB_ROOT, "tests")),
  ].filter((path) => !relPosix(WEB_ROOT, path).startsWith("src/components/interior/"));
  for (const path of sources) {
    for (const match of readFileSync(path, "utf8").matchAll(IMPORT_OF_INTERIOR)) {
      names.add(match[1]);
    }
  }
  return names;
}

describe("every component in components/interior is either used or accounted for", () => {
  it("reads a directory that is actually there", () => {
    expect(MODULES.length).toBeGreaterThan(5);
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
