/**
 * A server component may not call a formatter through `@/components/ui`.
 *
 * `components/ui.tsx` is a "use client" module, so every function it exports is a client
 * reference on the server: calling `formatINR(...)` from a server component throws at render
 * and the page answers 500. That took `/pricing` down once. The display rule lives in
 * `lib/numberDisplay.ts`, which has no directive and is safe on both sides; server files
 * import it from there.
 *
 * Scoped to what is certainly rendered on the server: route files (page, layout, template,
 * not-found) with no directive, and the public site under components/marketing. A directive-less helper elsewhere is usually
 * only ever imported by client code, where the ui import is fine.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "src");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

const CLIENT = /^\s*["']use client["'];?/m;
const UI_IMPORT = /import\s+\{([^}]*)\}\s+from\s+["']@\/components\/ui["']/g;

describe("server components and the client formatters", () => {
  it("never import a format* function from the client ui module", () => {
    const offenders: string[] = [];
    const serverSide = files(SRC).filter((path) => {
      const rel = relative(SRC, path).split("\\").join("/");
      return /^app\/(.*\/)?(page|layout|template|not-found)\.tsx$/.test(rel) || rel.startsWith("components/marketing/");
    });
    for (const path of serverSide) {
      const source = readFileSync(path, "utf8");
      if (CLIENT.test(source.split("\n").slice(0, 3).join("\n"))) continue;
      for (const match of source.matchAll(UI_IMPORT)) {
        if (/^\s*type\b/.test(match[0].slice(6))) continue;
        const names = match[1]!
          .split(",")
          .map((name) => name.trim())
          .filter((name) => name && !name.startsWith("type "));
        const formatters = names.filter((name) => /^format[A-Z]/.test(name));
        if (formatters.length) offenders.push(`${relative(SRC, path)}: ${formatters.join(", ")}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
