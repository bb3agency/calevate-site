"use client";

/**
 * A PDF's text, read IN THE BROWSER with Mozilla's pdf.js (D-781), for one purpose: if
 * Gemini cannot read the PDF itself when the question is asked, Pip reads this text instead
 * (and says that tables, charts and scanned pages may not have been read). It is taken out
 * at attach time so it is ready, and uploaded beside the PDF. Our server never opens a PDF.
 *
 * HARDENED, because a PDF is a program format and pdf.js has had two arbitrary-JS advisories:
 *
 * - **pdfjs-dist 6.3.289, pinned exactly.** Published 29 Aug 2026 (npm registry), so past the
 *   two-week rule; above CVE-2024-4367 (GHSA-wgrm-67xf-hhpq, fixed in 4.2.67) and above
 *   CVE-2026-16633 (GHSA-hq66-cqwq-w95j, affects >= 5.6.83, fixed in 6.2.108), read on
 *   github.com/mozilla/pdf.js/security/advisories on 15 Oct 2026. No dependencies; no install
 *   scripts; its one optional dependency (a native canvas for Node) is not installed
 *   (`pnpm-workspace.yaml`, `ignoredOptionalDependencies`).
 * - **No eval path exists to switch off.** CVE-2024-4367 was font glyphs compiled with
 *   `new Function`, which `isEvalSupported: false` disabled; pdf.js 6 removed that path and
 *   the option with it (the 6.3.289 type definitions have no `isEvalSupported`, and the
 *   shipped `build/pdf.mjs` and `build/pdf.worker.mjs` contain no `new Function(` or
 *   `eval(`, checked 15 Oct 2026). **`enableXfa: false`**, and no rendering at all: only
 *   `getTextContent()` runs, so no page script, form or font is executed or drawn, and
 *   pdf.js's scripting sandbox is never loaded.
 * - **In its worker**, served from our own origin by the bundler; the page's CSP allows
 *   `worker-src 'self'` and nothing more (`lib/security/csp.ts`).
 *
 * An empty string means the PDF holds no text (a scanned document) or could not be read;
 * the server then refuses the question if Gemini cannot read the PDF itself.
 */

/** Pages read at most: Gemini's own PDF ceiling (ai.google.dev/gemini-api/docs/
 *  document-processing, read 15 Oct 2026). */
export const MAX_PDF_PAGES = 1000;
/** Characters kept: well past what Pip reads of a text attachment. */
export const MAX_PDF_TEXT_CHARS = 2_000_000;

export async function pdfText(bytes: Uint8Array): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).toString();
  const task = pdfjs.getDocument({
    // A copy: pdf.js transfers the buffer to its worker, and the caller still uploads it.
    data: bytes.slice(),
    enableXfa: false,
    disableFontFace: true,
    useSystemFonts: false,
    stopAtErrors: false,
  });
  try {
    const doc = await task.promise;
    const pages = Math.min(doc.numPages, MAX_PDF_PAGES);
    const out: string[] = [];
    let length = 0;
    for (let number = 1; number <= pages && length < MAX_PDF_TEXT_CHARS; number += 1) {
      const page = await doc.getPage(number);
      const content = await page.getTextContent();
      const line = content.items
        .map((item) => ("str" in item ? item.str + (item.hasEOL ? "\n" : " ") : ""))
        .join("")
        .trim();
      if (line !== "") {
        out.push(`Page ${number}\n${line}`);
        length += line.length;
      }
      page.cleanup();
    }
    return out.join("\n\n").slice(0, MAX_PDF_TEXT_CHARS);
  } catch {
    // Unreadable, encrypted or malformed: there is no text to fall back on.
    return "";
  } finally {
    await task.destroy();
  }
}
