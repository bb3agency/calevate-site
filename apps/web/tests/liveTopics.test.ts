import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ALL_LIVE_FAMILIES,
  LIVE_TOPICS,
  STATIC_FAMILIES,
  TOPIC_FAMILIES,
  familyOf,
} from "@/lib/live/topics";

import { toPosix } from "./repoPaths";

/**
 * Every query in the console is reachable from a live change note (D-774), checked over
 * the source rather than trusted to the next author.
 *
 * A query key that no topic maps to is a feed that never updates live: the stream says
 * "calls changed" and that screen keeps showing the old answer until its safety poll. The
 * scan reads every `queryKey:` that DEFINES a query (invalidations are skipped), resolves
 * it to its family the way `familyOf` does at runtime — following key-builder constants,
 * functions and object members through the tree — and requires the family to be under a
 * topic in `lib/live/topics.ts` or in `STATIC_FAMILIES` with a reason. A key the scan
 * cannot resolve fails too, so a clever key cannot opt out by being unreadable.
 */

const SRC = join(process.cwd(), "src");
const API_TOPICS = join(process.cwd(), "..", "api", "live", "topics.py");

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.tsx?$/.test(entry) && !/\.test\./.test(entry)) out.push(full);
  }
  return out;
}

// `lib/live/` itself names `queryKey:` in prose and as a parameter; it defines no query.
const files = sourceFiles(SRC)
  .filter((file) => !toPosix(file).includes("/src/lib/live/"))
  .map((file) => ({ file, text: readFileSync(file, "utf8") }));
const corpus = files.map((f) => f.text).join("\n");

/** The expression starting at `i`, up to the comma, semicolon or newline at its own depth. */
function expressionAt(text: string, i: number): string {
  let depth = 0;
  const start = i;
  for (; i < text.length; i += 1) {
    const c = text[i];
    if (c === "[" || c === "(" || c === "{") depth += 1;
    else if (c === "]" || c === ")" || c === "}") {
      depth -= 1;
      if (depth < 0) break;
    } else if ((c === "," || c === ";" || c === "\n") && depth === 0) break;
  }
  return text.slice(start, i).replace(/\s+/g, " ").trim();
}

/** What a name is bound to: `const NAME = …` or `function NAME(…) { return …`, same file first. */
function definition(name: string, here: string): string | null {
  for (const scope of [here, corpus]) {
    const bound = new RegExp(`(?:const|let)\\s+${name}\\b[^=]*=\\s*`).exec(scope);
    if (bound) return scope.slice(bound.index + bound[0].length);
    const fn = new RegExp(`function\\s+${name}\\s*\\([^)]*\\)[^{]*\\{\\s*return\\s+`).exec(scope);
    if (fn) return scope.slice(fn.index + fn[0].length);
  }
  return null;
}

function staticFamily(expression: string, here: string, depth = 0): string | null {
  const expr = expression.trim();
  if (depth > 5) return null;
  if (expr.startsWith("[")) {
    const spread = /^\[\s*\.\.\.([\w$.]+(?:\([^)]*\))?)/.exec(expr);
    if (spread) return staticFamily(spread[1], here, depth + 1);
    const literals = /^\[\s*"([^"]+)"(?:\s*,\s*"([^"]+)")?(?:\s*,\s*"([^"]+)")?/.exec(expr);
    return literals ? familyOf(literals.slice(1).filter((v): v is string => v !== undefined)) : null;
  }
  const name = /^([A-Za-z_$][\w$]*)(?:\.([A-Za-z_$][\w$]*))?/.exec(expr);
  if (!name) return null;
  let target = definition(name[1], here);
  if (target === null) return null;
  if (name[2]) {
    const member = new RegExp(`\\b${name[2]}\\s*:\\s*`).exec(target);
    if (!member) return null;
    target = target.slice(member.index + member[0].length);
  }
  const arrow = /^(?:\([^)]*\)|[\w$]+)\s*(?::\s*[^=]+)?=>\s*/.exec(target);
  if (arrow) target = target.slice(arrow[0].length);
  return staticFamily(expressionAt(target, 0), here, depth + 1);
}

const INVALIDATION = /(invalidate|cancel|refetch|remove|reset)Queries\(\{\s*$|Quer(y|ies)Data\S*\(\{\s*$/;

function queryFamilies(): { families: Map<string, string[]>; unresolved: string[] } {
  const families = new Map<string, string[]>();
  const unresolved: string[] = [];
  for (const { file, text } of files) {
    const at = /queryKey:\s*/g;
    let match: RegExpExecArray | null;
    while ((match = at.exec(text))) {
      if (INVALIDATION.test(text.slice(Math.max(0, match.index - 60), match.index))) continue;
      const key = expressionAt(text, match.index + match[0].length);
      const where = toPosix(file.slice(SRC.length + 1));
      const family = staticFamily(key, text);
      if (family === null) unresolved.push(`${where} — ${key}`);
      else families.set(family, [...(families.get(family) ?? []), where]);
    }
  }
  return { families, unresolved };
}

describe("live topics → query families", () => {
  const { families, unresolved } = queryFamilies();

  it("scans a tree it actually found", () => {
    expect(files.length).toBeGreaterThan(100);
    expect(families.size).toBeGreaterThan(100);
  });

  it("resolves every query key to a family", () => {
    expect(unresolved, "query keys the scan cannot follow to a literal family").toEqual([]);
  });

  it("maps every query family to a topic, or says why nothing announces it", () => {
    const orphans = [...families.keys()]
      .filter((family) => !ALL_LIVE_FAMILIES.has(family) && !Object.hasOwn(STATIC_FAMILIES, family))
      .map((family) => `${family} (${families.get(family)?.join(", ")})`);
    expect(
      orphans,
      "add each family to the topics that change it in src/lib/live/topics.ts, or to STATIC_FAMILIES with the reason",
    ).toEqual([]);
  });

  it("names no family that no query uses", () => {
    const named = [...ALL_LIVE_FAMILIES, ...Object.keys(STATIC_FAMILIES)];
    expect(named.filter((family) => !families.has(family))).toEqual([]);
    expect(Object.keys(STATIC_FAMILIES).filter((family) => ALL_LIVE_FAMILIES.has(family))).toEqual([]);
  });

  it("speaks exactly the server's topics", () => {
    const source = readFileSync(API_TOPICS, "utf8");
    const block = /Topic = Literal\[([^\]]*)\]/.exec(source);
    expect(block).not.toBeNull();
    const server = [...(block?.[1] ?? "").matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    expect([...LIVE_TOPICS].sort()).toEqual(server);
    expect(Object.keys(TOPIC_FAMILIES).sort()).toEqual(server);
  });
});

describe("familyOf", () => {
  it("is the first segment, with the realm prefixes taking the next", () => {
    expect(familyOf(["calls", "acme", { page: 1 }])).toBe("calls");
    expect(familyOf(["admin", "tenants", { q: "" }])).toBe("admin/tenants");
    expect(familyOf(["admin", "ops", "reply-times", 7])).toBe("admin/ops/reply-times");
    expect(familyOf(["ops", "trial-number"])).toBe("ops/trial-number");
    expect(familyOf([42])).toBeNull();
  });
});
