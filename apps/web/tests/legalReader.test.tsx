import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LegalIndexPage from "@/app/legal/page";
import LegalDocumentRoute from "@/app/legal/[slug]/page";
import { LEGAL_DOCUMENTS, textOf } from "@/lib/legal";
import { resolvePlaceholders } from "@/lib/legal/placeholders";

/**
 * THE READER IS PRESENTATION, AND PRESENTATION MAY NOT MOVE A WORD.
 *
 * `tests/legalContentHash.test.ts` guards the words in the document modules. It cannot
 * see the renderer: a layout change that dropped a list item, rendered a cell twice or
 * reordered two paragraphs would leave every hash green while the page said something
 * else. This file closes that half — every string `textOf` reaches is in the rendered
 * document body, in document order — and pins the reading aids the layout adds (the
 * collapsible contents, the scroll spy's marker, copy-link, back to top).
 */

async function renderDocument(slug: string): Promise<HTMLElement> {
  let container!: HTMLElement;
  await act(async () => {
    container = render(<LegalDocumentRoute params={Promise.resolve({ slug })} />).container;
  });
  return container;
}

/**
 * The document's own text: `<main>` without the navigation lists and the reader controls,
 * so a heading cannot be "found" in the table of contents instead of in the body.
 */
function bodyText(container: HTMLElement): string {
  const main = container.querySelector("main");
  if (!main) throw new Error("no <main> rendered");
  const copy = main.cloneNode(true) as HTMLElement;
  for (const node of copy.querySelectorAll("nav, button, [role=status]")) node.remove();
  return copy.textContent ?? "";
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the legal reader renders every word, once, in order", () => {
  it.each(LEGAL_DOCUMENTS.map((doc) => [doc.slug, doc] as const))(
    "/legal/%s",
    async (slug, doc) => {
      const text = bodyText(await renderDocument(slug));
      let cursor = 0;
      for (const part of resolvePlaceholders(textOf(doc)).split("\n")) {
        const at = text.indexOf(part, cursor);
        expect(at, `/legal/${slug}: missing or out of order: ${part.slice(0, 80)}`).toBeGreaterThanOrEqual(0);
        cursor = at + part.length;
      }
    },
  );
});

describe("the reading aids", () => {
  it("collapses the contents behind a disclosure that says what it controls", async () => {
    const container = await renderDocument("privacy");
    const toc = container.querySelector('nav[aria-label="On this page"]');
    const toggle = toc?.querySelector("button[aria-expanded]");
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    const list = container.querySelector(`#${CSS.escape(toggle?.getAttribute("aria-controls") ?? "")}`);
    expect(list, "aria-controls points at nothing").not.toBeNull();
    expect(list?.className).toMatch(/(^|\s)hidden(\s|$)/);
    // From `lg` the list is always shown, so the collapse is a phone layout only.
    expect(list?.className).toContain("lg:block");

    fireEvent.click(toggle!);
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(list?.className).not.toMatch(/(^|\s)hidden(\s|$)/);

    // Following a link from the open panel closes it.
    fireEvent.click(list!.querySelector("a")!);
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
  });

  it("marks exactly one contents entry as the reader's location", async () => {
    const container = await renderDocument("terms");
    const toc = container.querySelector('nav[aria-label="On this page"]');
    expect(toc?.querySelectorAll('a[aria-current="location"]').length).toBe(1);
  });

  it("offers a copy-link control beside every heading, outside the heading", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    for (const doc of LEGAL_DOCUMENTS) {
      const container = await renderDocument(doc.slug);
      for (const heading of container.querySelectorAll("section h2, section h3")) {
        expect(heading.querySelector("button"), "a button inside a heading renames it").toBeNull();
        const button = heading.parentElement?.querySelector("button");
        expect(button?.getAttribute("aria-label"), `/legal/${doc.slug}`).toBe(
          `Copy link to ${heading.textContent}`,
        );
      }
    }

    const container = await renderDocument("dpa");
    const first = LEGAL_DOCUMENTS.find((doc) => doc.slug === "dpa")!.sections[0];
    const button = container.querySelector(
      `button[aria-label="Copy link to ${first.heading}"]`,
    )!;
    await act(async () => {
      fireEvent.click(button);
    });
    expect(writeText).toHaveBeenCalledWith(expect.stringMatching(new RegExp(`#${first.id}$`)));
    expect(button.parentElement?.querySelector("[role=status]")?.textContent).toBe("Link copied");
  });

  it("says so when the clipboard refuses, rather than failing silently", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    const container = await renderDocument("refunds");
    const button = container.querySelector("section button")!;
    await act(async () => {
      fireEvent.click(button);
    });
    expect(button.parentElement?.querySelector("[role=status]")?.textContent).toContain(
      "address bar",
    );
  });

  it("links back to the top of the document, and the target exists", async () => {
    const container = await renderDocument("cookies");
    const back = container.querySelector('a[aria-label="Back to top"]');
    expect(back?.getAttribute("href")).toBe("#top");
    expect(container.querySelector("#top")?.querySelector("h1")).not.toBeNull();
  });

  it("lists every document on the index, with its own summary and version", () => {
    const { container } = render(<LegalIndexPage />);
    for (const doc of LEGAL_DOCUMENTS) {
      const link = container.querySelector("main")?.querySelector(`a[href="/legal/${doc.slug}"]`);
      expect(link, `/legal has no card for ${doc.slug}`).not.toBeNull();
      expect(link?.textContent).toContain(doc.summary);
    }
  });
});
