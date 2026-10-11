import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

const rel = (path: string): string => relPosix(process.cwd(), path);

/**
 * ONE LAYER SCALE (globals.css `--z-*` and the `z-<layer>` utilities). A raw `z-10` or
 * `z-[70]` is how the assistant panel ended up under the call transcript: every file
 * picked its own number, and nobody could say what a number was above. The guard fails on
 * any raw z-index class, and on any CSS `z-index` that does not read a `--z-*` variable.
 */

const SRC = join(process.cwd(), "src");
const SKIP = new Set(["src/lib/api/schema.d.ts"]);

function files(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(tsx?|css)$/.test(entry.name) && !SKIP.has(rel(full))) out.push(full);
    }
  };
  walk(SRC);
  return out;
}

/** `z-10`, `-z-10`, `z-[70]`, `sm:z-20`, `z-(--x)`: anything but a named layer or `z-auto`. */
const RAW_CLASS = /(?<![\w-])-?z-(?:\d+|\[[^\]]*\]|\([^)]*\))(?![\w-])/g;
const LAYERS = ["below", "base", "raised", "sticky", "header", "dropdown", "drawer", "assistant", "modal", "toast"];

describe("the layer scale", () => {
  it("has no raw z-index class anywhere in src", () => {
    const sources = files();
    expect(sources.length).toBeGreaterThan(200);
    const offenders: string[] = [];
    for (const file of sources) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          for (const match of line.matchAll(RAW_CLASS)) offenders.push(`${rel(file)}:${i + 1} ${match[0]}`);
        });
    }
    expect(offenders, `use a z-<layer> utility (${LAYERS.join(", ")}) from globals.css`).toEqual([]);
  });

  it("has no CSS z-index that is not a layer variable", () => {
    const offenders: string[] = [];
    for (const file of files().filter((f) => f.endsWith(".css"))) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          const m = /z-index\s*:\s*([^;]+);/.exec(line);
          if (m && !/^var\(--z-[a-z]+\)$/.test(m[1].trim())) offenders.push(`${rel(file)}:${i + 1} ${m[1]}`);
        });
    }
    expect(offenders).toEqual([]);
  });

  it("defines every layer once, in order", () => {
    const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");
    const values = LAYERS.map((layer) => {
      const m = new RegExp(`--z-${layer}:\\s*(-?\\d+);`).exec(css);
      expect(m, `--z-${layer}`).not.toBeNull();
      expect(css).toContain(`@utility z-${layer} {`);
      return Number(m?.[1]);
    });
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });

  it("puts the overlays that must beat the page in a portal", () => {
    const portalled = [
      "src/components/modalDialog.tsx",
      "src/components/interior/popover.tsx",
      "src/components/console/rowMenu.tsx",
      "src/components/console/drawer.tsx",
      "src/components/interior/command-palette.tsx",
      "src/components/copilot/CopilotDock.tsx",
    ];
    for (const path of portalled) {
      expect(readFileSync(join(process.cwd(), path), "utf8"), path).toMatch(/createPortal\([\s\S]*document\.body/);
    }
  });
});
