import { istDateStamp } from "@/components/ui";

/**
 * HAND A CSV TO THE BROWSER TO SAVE — the one way every export in the client console
 * downloads (leads, calls).
 *
 * **The byte-order mark is added HERE and not on the server, and that is the same split
 * `core/spreadsheet_safety.py` makes**: one hazard, two renderings, each written for the
 * consumer that will actually open the bytes. Excel does not sniff UTF-8 — a `.csv` with
 * no mark is decoded in the machine's legacy code page, so on a Telugu-first product
 * every name in the file arrives as mojibake. The API RESPONSE stays clean UTF-8 with no
 * mark, because a script reading it would otherwise find a stray U+FEFF welded to its
 * first header cell. Written as an ESCAPE, never a pasted glyph: U+FEFF is zero-width.
 *
 * The file is named for the IST day, not the UTC one: before 05:30 IST `toISOString()` is
 * still on yesterday. The anchor is in the document and the URL revoked a tick later: a
 * detached anchor is a no-op in some browsers, and revoking synchronously can cancel the
 * save.
 */
const BOM = "﻿";

export function saveCsv(csv: string, basename: string): void {
  const url = URL.createObjectURL(new Blob([BOM, csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${basename}-${istDateStamp()}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
