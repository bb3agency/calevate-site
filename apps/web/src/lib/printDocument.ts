"use client";

/**
 * PRINT ONE DOCUMENT, NOT THE CONSOLE.
 *
 * `window.print()` on a console screen prints the SHELL: the app shell is a fixed,
 * full-window box whose `<main>` scrolls internally (`c/[slug]/layout.tsx`), so the printer
 * gets the visible viewport — sidebar, header and a document cut off where the screen
 * ended. This prints a given node (or an HTML string) on its own instead, through a
 * hidden same-origin iframe that carries the app's stylesheets plus a print sheet, and
 * removes the iframe afterwards.
 *
 * - The node is CLONED, so the live screen is untouched and no React handler travels with
 *   it; form values typed into inputs are not carried (print a rendered document, not a
 *   form).
 * - The app's `<link rel="stylesheet">` and `<style>` elements are copied, and the root
 *   and body classes too, because the fonts and the theme tokens hang off them
 *   (`app/layout.tsx`). Printing waits for those sheets and for web fonts, so the first
 *   page is not printed in a fallback face.
 * - The iframe is `about:blank`, which inherits this page's origin and CSP; nothing is
 *   fetched from anywhere new.
 * - Resolves once `print()` has been called. The frame is removed on `afterprint`, which a
 *   blocking dialog (Chrome) has already fired by then and an asynchronous one fires
 *   later; a frame nobody closes is removed after a minute.
 *
 * Mark anything inside the node that should not print with `print:hidden` as usual.
 */
export async function printDocument(
  source: HTMLElement | string,
  {
    title,
    pageCss = DEFAULT_PAGE_CSS,
    print = (win: Window) => win.print(),
  }: {
    /** The document title, which browsers use as the default PDF file name. */
    title?: string;
    /** Extra print CSS; replaces the default `@page` rules. */
    pageCss?: string;
    /** The print call itself. A test seam; leave it alone in the app. */
    print?: (win: Window) => void;
  } = {},
): Promise<void> {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("tabindex", "-1");
  frame.title = title ?? "Print";
  Object.assign(frame.style, {
    position: "fixed",
    right: "0",
    bottom: "0",
    width: "0",
    height: "0",
    border: "0",
    visibility: "hidden",
  });
  document.body.appendChild(frame);

  try {
    const win = frame.contentWindow;
    const doc = frame.contentDocument;
    if (!win || !doc) throw new Error("The print frame could not be opened.");

    doc.title = title ?? document.title;
    doc.documentElement.className = document.documentElement.className;
    doc.documentElement.lang = document.documentElement.lang;

    const loads: Promise<void>[] = [];
    for (const node of Array.from(document.querySelectorAll('link[rel="stylesheet"], style'))) {
      const copy = doc.importNode(node, true) as HTMLElement;
      if (copy.tagName === "LINK") {
        loads.push(
          new Promise<void>((resolve) => {
            copy.addEventListener("load", () => resolve(), { once: true });
            copy.addEventListener("error", () => resolve(), { once: true });
            // A sheet that never answers must not hold the print forever.
            setTimeout(resolve, 3000);
          }),
        );
      }
      doc.head.appendChild(copy);
    }
    const sheet = doc.createElement("style");
    sheet.textContent = pageCss;
    doc.head.appendChild(sheet);

    doc.body.className = document.body.className;
    if (typeof source === "string") {
      doc.body.innerHTML = source;
    } else {
      doc.body.appendChild(doc.importNode(source, true));
    }

    await Promise.all(loads);
    await (doc as Document & { fonts?: FontFaceSet }).fonts?.ready;

    let printed = false;
    const cleanup = () => frame.remove();
    win.addEventListener(
      "afterprint",
      () => {
        printed = true;
        cleanup();
      },
      { once: true },
    );
    win.focus();
    print(win);
    // Chrome blocks in `print()` and has fired `afterprint` by now. Browsers whose dialog
    // is asynchronous fire it later; the frame stays until they do, or a minute passes.
    if (!printed) setTimeout(cleanup, 60_000);
  } catch (error) {
    frame.remove();
    throw error;
  }
}

/**
 * A4 with print margins, white paper, and no app chrome backgrounds. A document that needs
 * its own page rules passes `pageCss`.
 */
export const DEFAULT_PAGE_CSS = `
@page { size: A4; margin: 16mm 14mm; }
html, body { background: #ffffff !important; height: auto !important; overflow: visible !important; }
body { margin: 0; color: #171a1c; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
`;
