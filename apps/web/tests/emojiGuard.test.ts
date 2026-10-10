import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * NO EMOJI OR PICTOGRAPHS IN WHAT THE CONSOLE SAYS (founder, 10 Oct 2026; no-ai-design-slop).
 *
 * A sparkle beside "AI decides", a rocket on a launch button, a tick emoji on a success line:
 * each reads as generated decoration, renders differently on every platform, and is read
 * aloud by a screen reader as its Unicode name. Icons are lucide components and brand
 * marks are the files in `public/brand/services/`, so neither is a string.
 *
 * Every string literal, template part and JSX text in a `.tsx` file under `app/` or
 * `components/` is read through the TypeScript parser, so a ⚠ in a comment (this repo's
 * convention for a load-bearing warning) is not a hit, and a pictograph inside a string is.
 * Nothing is allowed.
 */

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const ROOTS = ["app", "components"].map((r) => join(SRC, r));
const PICTOGRAPH = /\p{Extended_Pictographic}/u;

function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return tsxFiles(path);
    return entry.name.endsWith(".tsx") ? [path] : [];
  });
}

function hits(file: string): string[] {
  const text = readFileSync(file, "utf8");
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    const literal =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node);
    if (literal) {
      const value = ts.isJsxText(node) ? node.getText(source) : node.text;
      if (PICTOGRAPH.test(value)) {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
        found.push(`${relative(SRC, file).replace(/\\/g, "/")}:${line + 1} ${value.trim().slice(0, 60)}`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe("no emoji in the interface", () => {
  it("has no pictograph in any string or JSX text under app/ or components/", () => {
    const files = ROOTS.flatMap(tsxFiles);
    expect(files.length).toBeGreaterThan(100);
    expect(files.flatMap(hits)).toEqual([]);
  });

  it("would catch one", () => {
    expect(PICTOGRAPH.test("✨ AI decides")).toBe(true);
    expect(PICTOGRAPH.test("Add a parameter")).toBe(false);
  });
});
