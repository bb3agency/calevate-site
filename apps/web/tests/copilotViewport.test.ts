/**
 * The root layout's `viewport` export, and why the copilot lane owns a test for it.
 *
 * `CopilotPanel` is `position: fixed`, anchored to `bottom-20`, and its only control is a
 * textarea. Under the viewport meta default — `interactive-widget: resizes-visual` — a
 * mobile virtual keyboard resizes only the VISUAL viewport, and per MDN's own description
 * "elements with `position: fixed` will remain in place and can be obscured by the
 * keyboard" (MDN, `<meta name="viewport">`, read 7 Sep 2026). So focusing the ask box on an
 * Android phone put the keyboard over the box being typed into.
 *
 * `resizes-content` resizes the LAYOUT viewport too, which pushes fixed elements above the
 * keyboard. It is set on the root because a viewport key cannot be scoped to a subtree —
 * there is one meta tag — and because the same hazard belongs to every other fixed element
 * with an input in it (the five modals, `ReceiptSheet`).
 *
 * ## Read as TEXT rather than imported
 *
 * `src/app/layout.tsx` calls `next/font/local` at module scope, which resolves and hashes
 * font files through the bundler. Importing it here would make this a test of the font
 * pipeline. The properties that matter are declarative, so the source is the right
 * instrument — the same choice `routeModuleExports.test.ts` makes, for the same reason.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const LAYOUT = join(import.meta.dirname, "..", "src", "app", "layout.tsx");

describe("the root layout's viewport", () => {
  const source = readFileSync(LAYOUT, "utf8");
  /**
   * Just the object literal. The comment above it NAMES the two fields that must not
   * appear (`maximumScale`, `userScalable`) in order to say why they are absent, so a
   * whole-file `not.toMatch` would fail on the explanation rather than on the code.
   */
  const declaration = (() => {
    const start = source.indexOf("export const viewport: Viewport = {");
    // "" rather than a throw: a throw here happens during COLLECTION and reports as
    // "no tests", which reads like the file was skipped rather than like a failure.
    if (start === -1) return "";
    return source.slice(start, source.indexOf("};", start) + 2);
  })();

  it("finds the file at all, so a moved layout cannot make this pass vacuously", () => {
    expect(source).toContain("export default function RootLayout");
  });

  it("declares interactiveWidget: resizes-content, so the keyboard moves the copilot panel", () => {
    expect(declaration, "no `viewport` export in the root layout").not.toBe("");
    expect(declaration).toMatch(/interactiveWidget:\s*"resizes-content"/);
  });

  it("RESTATES Next's own defaults, because declaring the export replaces them", () => {
    // The trap this pins: `export const viewport` does not EXTEND Next's default tag, it
    // replaces it. A viewport export carrying only `interactiveWidget` would ship a page
    // with no `width=device-width`, and every responsive layout in both consoles would
    // render at desktop width on a phone — a far worse defect than the one being fixed.
    expect(declaration).toMatch(/width:\s*"device-width"/);
    expect(declaration).toMatch(/initialScale:\s*1/);
  });

  it("NEVER suppresses pinch-zoom (WCAG 2.1 SC 1.4.4)", () => {
    // `maximumScale` and `userScalable: false` are the two spellings of "you may not zoom".
    // Neither has ever been in this tree and neither may arrive by way of this export.
    expect(declaration).not.toMatch(/maximumScale/);
    expect(declaration).not.toMatch(/userScalable/);
  });

  it("leaves `force-dynamic` alone — the CSP nonce depends on it", () => {
    // Guarded here as well as in `routeModuleExports.test.ts` because this lane edits this
    // file: removing it served a blank production page once, and adding a neighbouring
    // export is exactly the kind of edit that takes a line with it.
    expect(source).toMatch(/export const dynamic = "force-dynamic";/);
  });
});
