import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every auth and callback screen names itself in the document title (WCAG 2.4.2).
 *
 * These pages are client components, so their title comes from the nearest `layout.tsx`
 * exporting `metadata`. Read off disk so a new auth page without one fails here instead of
 * shipping as a bare "Calevate" tab.
 */

const APP = join(process.cwd(), "src", "app");
const ROOTS = [join(APP, "(auth)", "auth"), join(APP, "oauth")];

function pagesUnder(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return pagesUnder(full);
    return entry.name === "page.tsx" ? [full] : [];
  });
}

function titleFor(page: string): string | undefined {
  for (let dir = dirname(page); dir.startsWith(APP) && dir !== APP; dir = dirname(dir)) {
    const layout = join(dir, "layout.tsx");
    if (!existsSync(layout)) continue;
    const match = /title:\s*"([^"]+)"/.exec(readFileSync(layout, "utf8"));
    if (match) return match[1];
  }
  return undefined;
}

describe("auth screen titles", () => {
  const pages = ROOTS.flatMap(pagesUnder);

  it("finds the auth pages", () => {
    expect(pages.length).toBeGreaterThanOrEqual(12);
  });

  it.each(pages.map((p) => [relative(APP, p), p]))("%s has its own title", (_name, page) => {
    const title = titleFor(page);
    expect(title).toBeDefined();
    expect(title).not.toBe("Calevate");
    expect(title).toMatch(/ — Calevate$/);
  });

  it("no two auth pages share a title", () => {
    const titles = pages.map(titleFor);
    expect(new Set(titles).size).toBe(titles.length);
  });
});
