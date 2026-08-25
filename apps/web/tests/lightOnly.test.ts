import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * THE PRODUCT SHIPS IN LIGHT MODE ONLY (D-471), and this is the guard that keeps it so.
 *
 * Dark mode was wired and then deliberately withdrawn. That withdrawal is unusually easy
 * to undo by accident, because the evidence for dark mode is still sitting in the tree:
 * the `.dark` block and 429 `dark:` utilities REMAIN on purpose — deleting them would be a
 * huge diff for no user-visible gain and would throw away a palette already contrast-checked
 * in both themes. They are dormant only because nothing can set the class.
 *
 * So the property that makes the product light-only is an ABSENCE, and absences rot: the
 * next person sees a full dark palette, concludes the toggle was forgotten, and adds one.
 * This pins the absence itself rather than any screen's appearance.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Every `.tsx`/`.ts` under `src/`, so the scan cannot quietly miss a new screen. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith("schema.d.ts")) out.push(full);
    }
  };
  walk(resolve(WEB_ROOT, "src"));
  return out;
}

describe("the product ships in light mode only (D-471)", () => {
  it("scans a real tree, rather than passing on an empty one", () => {
    // The premise, for the same reason `contrast.test.ts` states one: a moved directory
    // would otherwise make the assertion below vacuously true.
    expect(sourceFiles().length).toBeGreaterThan(100);
  });

  it("has no code anywhere that can set the dark class or read the OS preference", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          // `dark:` UTILITIES are the dormant palette and are allowed — they cannot apply
          // while nothing sets the class. What is banned is anything that could put the
          // class on an element at runtime, or branch on the device's theme.
          const activatesDark =
            /classList\.(add|toggle|remove)\(\s*["'`]dark["'`]/.test(line) ||
            /prefers-color-scheme/.test(line);
          if (activatesDark) offenders.push(`${relPosix(WEB_ROOT, file)}:${i + 1}`);
        });
    }
    expect(
      offenders,
      "D-471: the product is light-only. Nothing may set the `dark` class or read " +
        "`prefers-color-scheme`. Bringing dark mode back is a decision-log entry that " +
        "supersedes D-471, not an edit that slips in under a dormant palette.",
    ).toEqual([]);
  });

  it("declares color-scheme: light, so the BROWSER's own controls stay light", () => {
    // Without this a light page on a dark-OS machine still gets dark scrollbars, dark form
    // controls and dark autofill: the browser's furniture follows this property, not our
    // tokens. It must hold unconditionally — on `:root`, not inside a media query.
    const css = readFileSync(resolve(WEB_ROOT, "src/app/globals.css"), "utf8");
    expect(css).toMatch(/:root\s*\{[^}]*color-scheme:\s*light/);
    expect(css).not.toMatch(/color-scheme:\s*dark/);
  });
});
