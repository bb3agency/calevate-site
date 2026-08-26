import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandIcon, BrandLockup, BrandWordmark } from "@/components/brand";

/**
 * The logo, and the two ways this replacement could have gone wrong silently.
 *
 * The founder supplied three masters; five screens carried a lucide placeholder. What is
 * pinned here is not "an image renders" — a broken `src` renders too — but the pair of
 * decisions that are invisible once they are wrong:
 *
 * 1. **The mark is dark-green ink on transparency, not a white glyph.** Every placeholder
 *    it replaced sat inside a `bg-brand-strong text-white` chip. Dropping the real
 *    artwork into that chip renders green on green: it disappears, and it disappears in a
 *    way that looks intentional on a screenshot. `tests/contrast.test.ts` now carries an
 *    EMPTY `BRAND_FILL_EXEMPT` for the same reason, so a re-introduced brand fill fails
 *    there too.
 * 2. **Which form carries a name and which does not.** The wordmark and lockup REPLACE
 *    the product name, so they must have a real `alt` or the marketing header and the
 *    sign-in door lose their accessible name entirely. The square mark always sits beside
 *    that name in text, so a non-empty `alt` there would make a screen reader say
 *    "Calevate" twice.
 *
 * The assets themselves are checked as FILES rather than mocked: a test that stubs the
 * image cannot tell a shipped asset from a 404, and the whole failure mode here is a
 * reference to something that is not there.
 */

const PUBLIC = join(process.cwd(), "public");

describe("the brand assets exist as files, at the size that ships", () => {
  /** `[file, expected width, expected height]` — the ratios the masters actually have. */
  const ASSETS: [string, number, number][] = [
    ["brand/icon.png", 216, 216],
    ["brand/wordmark.png", 720, 240],
    ["brand/lockup.png", 720, 240],
  ];

  it.each(ASSETS)("%s is a PNG of the stated size", (file, width, height) => {
    const bytes = readFileSync(join(PUBLIC, file));
    expect(bytes.subarray(0, 8)).toEqual(
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    );
    // IHDR is always the first chunk: width and height are big-endian at bytes 16..24.
    expect([bytes.readUInt32BE(16), bytes.readUInt32BE(20)]).toEqual([width, height]);
  });

  it("ships derivatives rather than the masters, which are print-sized", () => {
    // The square master is 412 KB. Referencing it directly would put that on every
    // console page for a 36px mark, on a 1 vCPU box. The generator exists for this.
    for (const [file] of ASSETS) {
      const size = readFileSync(join(PUBLIC, file)).length;
      expect(size, `${file} is ${Math.round(size / 1024)}KB`).toBeLessThan(80 * 1024);
    }
  });
});

describe("which form carries the product name", () => {
  it("gives the wordmark and the lockup a real accessible name", () => {
    render(
      <>
        <BrandWordmark />
        <BrandLockup />
      </>,
    );
    expect(screen.getByAltText("Calevate")).toBeTruthy();
    expect(screen.getByAltText("Calevate — AI voice calling agents")).toBeTruthy();
  });

  it("leaves the square mark decorative, because its callers render the name in text", () => {
    const { container } = render(<BrandIcon />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("alt")).toBe("");
  });

  it("states width and height on every form, so nothing reflows as they load", () => {
    const { container } = render(
      <>
        <BrandIcon size={36} />
        <BrandWordmark height={52} />
        <BrandLockup height={52} />
      </>,
    );
    const sizes = Array.from(container.querySelectorAll("img")).map((img) => [
      img.getAttribute("width"),
      img.getAttribute("height"),
    ]);
    // The wordmark and lockup canvases are 3:1; the mark is square.
    expect(sizes).toEqual([
      ["36", "36"],
      ["156", "52"],
      ["156", "52"],
    ]);
  });
});
