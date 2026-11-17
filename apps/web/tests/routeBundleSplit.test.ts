import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { WEB_ROOT } from "./copyScan";

/**
 * A heavy screen downloads only the code of what is open. Each entry names a route module
 * and the modules that must stay OUT of its static import graph, because they are loaded
 * with `next/dynamic` when their tab or panel opens. A static import anywhere below the
 * route (the route itself, or any module it statically imports) would pull the module back
 * into the route's first load, which is what made the agent page about 450 KB of
 * JavaScript on a phone.
 */

const SRC = join(WEB_ROOT, "src");

const SPLITS: { route: string; lazy: string[] }[] = [
  {
    route: "app/c/[slug]/agents/[agentId]/page.tsx",
    lazy: [
      "app/c/[slug]/agents/[agentId]/sections/training.tsx",
      "app/c/[slug]/agents/[agentId]/sections/settingsTab.tsx",
      "app/c/[slug]/agents/actions/Actions.tsx",
      "app/c/[slug]/agents/[agentId]/sections/deletedAgent.tsx",
    ],
  },
  {
    route: "app/c/[slug]/campaigns/[campaignId]/page.tsx",
    lazy: [
      "app/c/[slug]/campaigns/CampaignRun.tsx",
      "app/c/[slug]/campaigns/CampaignTimeline.tsx",
      "app/c/[slug]/campaigns/CampaignCalls.tsx",
      "app/c/[slug]/campaigns/CampaignQuestions.tsx",
      "app/c/[slug]/agents/[agentId]/script/ProposalReview.tsx",
    ],
  },
  {
    route: "app/c/[slug]/inbound/[lineId]/page.tsx",
    lazy: ["app/c/[slug]/agents/[agentId]/script/ProposalReview.tsx"],
  },
  { route: "app/c/[slug]/page.tsx", lazy: ["app/c/[slug]/TrialCallPanel.tsx"] },
];

/** Static `import … from "x"` and `export … from "x"`; `import("x")` is not matched. */
const STATIC_IMPORT = /^\s*(?:import|export)\s+(?:type\s+)?[^;]*?\sfrom\s+["']([^"']+)["']|^\s*import\s+["']([^"']+)["']/gm;

function resolveModule(from: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = resolve(dirname(from), spec);
  else return null;
  for (const candidate of [base, `${base}.tsx`, `${base}.ts`, join(base, "index.tsx"), join(base, "index.ts")]) {
    if (existsSync(candidate) && /\.tsx?$/.test(candidate)) return candidate;
  }
  return null;
}

function staticGraph(entry: string): Set<string> {
  const seen = new Set<string>();
  const stack = [entry];
  while (stack.length) {
    const file = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(STATIC_IMPORT)) {
      const statement = match[0];
      // A type-only import is erased by the compiler and costs no bytes.
      if (/^\s*(?:import|export)\s+type\s/.test(statement)) continue;
      const next = resolveModule(file, match[1] ?? match[2]);
      if (next) stack.push(next);
    }
  }
  return seen;
}

describe("heavy routes load only what is open", () => {
  for (const { route, lazy } of SPLITS) {
    it(`${route} keeps its unopened tabs out of the first load`, () => {
      const graph = staticGraph(join(SRC, route));
      const pulledIn = lazy.filter((file) => graph.has(join(SRC, file)));
      expect(pulledIn).toEqual([]);
    });
  }
});
