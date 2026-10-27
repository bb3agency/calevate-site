/**
 * Server-rendered code may not call into a "use client" module.
 *
 * Every export of a "use client" module is a client reference on the server: rendering a
 * component from one is fine, but calling a function (`formatINR(...)`) or reading a
 * constant from one throws at render and the page answers 500. That took `/pricing` down
 * once. Shared helpers such as the display rule live in directive-less modules
 * (`lib/numberDisplay.ts`) that are safe on both sides.
 *
 * The walk starts at every server entry (route files with no directive, and the public
 * site under components/marketing) and follows imports through directive-less modules,
 * because a helper with no directive imported by a server page runs on the server too.
 * It stops at a "use client" module: what is imported FROM it is checked, what it imports
 * runs in the browser. A PascalCase name is taken to be a component and allowed.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "src");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

const ENTRY = /^app\/(.*\/)?(page|layout|template|not-found|loading|default|opengraph-image)\.tsx?$/;
const CLIENT = /^\s*["']use client["'];?/m;
const IMPORT = /(?:^|\n)\s*import\s+(type\s+)?([^;]*?)\s+from\s+["']([^"']+)["']/g;
const COMPONENT = /^[A-Z][a-z0-9]/;

const sourceCache = new Map<string, string>();
function source(path: string): string {
  let text = sourceCache.get(path);
  if (text === undefined) {
    text = readFileSync(path, "utf8");
    sourceCache.set(path, text);
  }
  return text;
}

function isClient(path: string): boolean {
  return CLIENT.test(source(path).split("\n").slice(0, 3).join("\n"));
}

function resolveImport(from: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) base = join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = resolve(dirname(from), spec);
  else return null;
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** The value names an import clause brings in: default and named, minus type-only ones. */
function valueNames(clause: string): string[] {
  const names: string[] = [];
  const braces = clause.match(/\{([^}]*)\}/);
  const head = clause.replace(/\{[^}]*\}/, "").replace(/,/g, " ").trim();
  if (head && !head.startsWith("*")) names.push(head.split(/\s+/)[0]!);
  if (head.startsWith("*")) names.push("*");
  for (const part of braces?.[1]?.split(",") ?? []) {
    const name = part.trim();
    if (!name || name.startsWith("type ")) continue;
    names.push(name.split(/\s+as\s+/)[0]!.trim());
  }
  return names;
}

describe("server-rendered code and client modules", () => {
  it("never calls a function or reads a constant from a use-client module", () => {
    const rel = (path: string) => relative(SRC, path).split("\\").join("/");
    const entries = files(SRC).filter((path) => {
      const name = rel(path);
      return (ENTRY.test(name) || name.startsWith("components/marketing/")) && !isClient(path);
    });
    expect(entries.length).toBeGreaterThan(10);

    const offenders = new Set<string>();
    const seen = new Set<string>();
    const queue = [...entries];
    while (queue.length) {
      const path = queue.pop()!;
      if (seen.has(path)) continue;
      seen.add(path);
      for (const match of source(path).matchAll(IMPORT)) {
        if (match[1]) continue;
        const target = resolveImport(path, match[3]!);
        if (!target) continue;
        if (isClient(target)) {
          const bad = valueNames(match[2]!).filter((name) => !COMPONENT.test(name));
          if (bad.length) offenders.add(`${rel(path)} -> ${match[3]}: ${bad.join(", ")}`);
        } else {
          queue.push(target);
        }
      }
    }
    expect([...offenders]).toEqual([]);
  });
});
