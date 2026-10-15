/**
 * Word, Excel and PowerPoint files → plain text, IN THE BROWSER (D-781).
 *
 * The founder's rule is that an uploaded file is never parsed on Calevate's servers, so an
 * Office file is opened here, on the person's own device, and only the text it holds is
 * sent. Pip's model reads text; the original file never leaves the browser.
 *
 * NO LIBRARY. A .docx, .xlsx or .pptx is a ZIP of XML parts. The browser already has both
 * halves of reading one: `DecompressionStream("deflate-raw")` inflates a ZIP entry and
 * `DOMParser` reads XML, so this module is a small central-directory reader and three text
 * walkers rather than a new dependency (hard rule 9). The reader only does what the three
 * formats need: stored or deflated entries, no encryption, no ZIP64, no nested archives.
 *
 * Bounded like any reader of files from the internet: the entry count, each entry's
 * inflated size, the total inflated size and the text produced all have ceilings, and an
 * entry is inflated only up to what it declares. A file carrying macros (`vbaProject.bin`,
 * or a macro-enabled content type) is refused, as is any XML part declaring a DOCTYPE.
 */

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;

export const MAX_ZIP_ENTRIES = 5_000;
export const MAX_ENTRY_BYTES = 64 * 1024 * 1024;
export const MAX_TOTAL_INFLATED = 128 * 1024 * 1024;
export const MAX_TEXT_CHARS = 2_000_000;
export const MAX_ROWS_PER_SHEET = 5_000;

export class OfficeTextError extends Error {
  constructor(
    message: string,
    readonly reason: "macros" | "unreadable" | "too_large" | "empty",
  ) {
    super(message);
    this.name = "OfficeTextError";
  }
}

interface ZipEntry {
  name: string;
  method: number;
  flags: number;
  compressedSize: number;
  size: number;
  localOffset: number;
}

function unreadable(): OfficeTextError {
  return new OfficeTextError("This file could not be opened.", "unreadable");
}

/** The archive's central directory. */
export function readCentralDirectory(bytes: Uint8Array): ZipEntry[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const floor = Math.max(0, bytes.length - 22 - 0xffff);
  let eocd = -1;
  for (let at = bytes.length - 22; at >= floor; at -= 1) {
    if (view.getUint32(at, true) === EOCD_SIGNATURE) {
      eocd = at;
      break;
    }
  }
  if (eocd < 0) throw unreadable();
  const count = view.getUint16(eocd + 10, true);
  const directoryOffset = view.getUint32(eocd + 16, true);
  if (count === 0xffff || directoryOffset === 0xffffffff) throw unreadable(); // ZIP64
  if (count > MAX_ZIP_ENTRIES) {
    throw new OfficeTextError("This file has too many parts to open.", "too_large");
  }
  const decoder = new TextDecoder("utf-8");
  const entries: ZipEntry[] = [];
  let at = directoryOffset;
  for (let index = 0; index < count; index += 1) {
    if (at + 46 > bytes.length || view.getUint32(at, true) !== CENTRAL_SIGNATURE) {
      throw unreadable();
    }
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    entries.push({
      flags: view.getUint16(at + 8, true),
      method: view.getUint16(at + 10, true),
      compressedSize: view.getUint32(at + 20, true),
      size: view.getUint32(at + 24, true),
      localOffset: view.getUint32(at + 42, true),
      name: decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength)),
    });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflate(data: Uint8Array, limit: number): Promise<Uint8Array> {
  const stream = new Blob([data.slice()]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.length;
    if (total > limit) {
      await reader.cancel();
      throw new OfficeTextError("This file is too large to open.", "too_large");
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

/** Opens entries of one archive, keeping a running total of what was inflated. */
export class ZipReader {
  private inflated = 0;
  readonly entries: ZipEntry[];

  constructor(private readonly bytes: Uint8Array) {
    this.entries = readCentralDirectory(bytes);
  }

  has(name: string): boolean {
    return this.entries.some((entry) => entry.name === name);
  }

  async text(name: string): Promise<string | null> {
    const entry = this.entries.find((candidate) => candidate.name === name);
    if (entry === undefined) return null;
    if ((entry.flags & 0x1) !== 0) throw unreadable(); // encrypted
    if (entry.size > MAX_ENTRY_BYTES || this.inflated + entry.size > MAX_TOTAL_INFLATED) {
      throw new OfficeTextError("This file is too large to open.", "too_large");
    }
    const view = new DataView(this.bytes.buffer, this.bytes.byteOffset, this.bytes.byteLength);
    const at = entry.localOffset;
    if (at + 30 > this.bytes.length || view.getUint32(at, true) !== LOCAL_SIGNATURE) {
      throw unreadable();
    }
    const start = at + 30 + view.getUint16(at + 26, true) + view.getUint16(at + 28, true);
    const raw = this.bytes.subarray(start, start + entry.compressedSize);
    let data: Uint8Array;
    if (entry.method === 0) data = raw;
    else if (entry.method === 8) data = await inflate(raw, entry.size);
    else throw unreadable();
    this.inflated += data.length;
    return new TextDecoder("utf-8").decode(data);
  }
}

function parseXml(source: string): Document {
  if (/<!DOCTYPE/i.test(source)) throw unreadable();
  const doc = new DOMParser().parseFromString(source, "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) throw unreadable();
  return doc;
}

/** Elements by local name, whatever prefix the producer chose. */
function byName(root: Document | Element, local: string): Element[] {
  return Array.from(root.getElementsByTagNameNS("*", local));
}

function refuseMacros(zip: ZipReader, contentTypes: string | null): void {
  const macro =
    zip.entries.some((entry) => /(^|\/)vbaProject\.bin$/i.test(entry.name)) ||
    (contentTypes !== null && /macroEnabled/i.test(contentTypes));
  if (macro) {
    throw new OfficeTextError("Files with macros can't be attached.", "macros");
  }
}

function paragraphText(paragraph: Element): string {
  let out = "";
  const walk = (node: Element) => {
    for (const child of Array.from(node.children)) {
      switch (child.localName) {
        case "t":
          out += child.textContent ?? "";
          break;
        case "tab":
          out += "\t";
          break;
        case "br":
        case "cr":
          out += "\n";
          break;
        default:
          walk(child);
      }
    }
  };
  walk(paragraph);
  return out;
}

async function docxText(zip: ZipReader): Promise<string> {
  const body = await zip.text("word/document.xml");
  if (body === null) throw unreadable();
  return byName(parseXml(body), "p").map(paragraphText).join("\n");
}

function csvCell(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

async function xlsxText(zip: ZipReader): Promise<string> {
  const workbook = await zip.text("xl/workbook.xml");
  const rels = await zip.text("xl/_rels/workbook.xml.rels");
  if (workbook === null || rels === null) throw unreadable();
  const shared = await zip.text("xl/sharedStrings.xml");
  const strings = shared === null ? [] : byName(parseXml(shared), "si").map(paragraphText);
  const targets = new Map(
    byName(parseXml(rels), "Relationship").map((rel) => [
      rel.getAttribute("Id") ?? "",
      rel.getAttribute("Target") ?? "",
    ]),
  );
  const parts: string[] = [];
  for (const sheet of byName(parseXml(workbook), "sheet")) {
    const relId =
      sheet.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") ??
      sheet.getAttribute("r:id");
    const target = targets.get(relId ?? "");
    if (!target) continue;
    const path = target.startsWith("/") ? target.slice(1) : `xl/${target.replace(/^\.\//, "")}`;
    const xml = await zip.text(path);
    if (xml === null) continue;
    const rows = byName(parseXml(xml), "row").slice(0, MAX_ROWS_PER_SHEET);
    const lines = rows.map((row) =>
      byName(row, "c")
        .map((cell) => {
          const type = cell.getAttribute("t");
          if (type === "s") return strings[Number(byName(cell, "v")[0]?.textContent ?? -1)] ?? "";
          if (type === "inlineStr") return byName(cell, "is").map(paragraphText).join("");
          return byName(cell, "v")[0]?.textContent ?? "";
        })
        .map(csvCell)
        .join(","),
    );
    parts.push(`Sheet: ${sheet.getAttribute("name") ?? ""}\n${lines.join("\n")}`);
  }
  return parts.join("\n\n");
}

async function pptxText(zip: ZipReader): Promise<string> {
  const slides = zip.entries
    .map((entry) => /^ppt\/slides\/slide(\d+)\.xml$/.exec(entry.name))
    .filter((match): match is RegExpExecArray => match !== null)
    .sort((a, b) => Number(a[1]) - Number(b[1]));
  const parts: string[] = [];
  for (const match of slides) {
    const xml = await zip.text(match[0]);
    if (xml === null) continue;
    const text = byName(parseXml(xml), "p").map(paragraphText).filter(Boolean).join("\n");
    parts.push(`Slide ${match[1]}\n${text}`);
  }
  return parts.join("\n\n");
}

/** The text of one Word, Excel or PowerPoint file. Throws `OfficeTextError`. */
export async function officeText(bytes: Uint8Array, kind: "docx" | "xlsx" | "pptx"): Promise<string> {
  let zip: ZipReader;
  try {
    zip = new ZipReader(bytes);
  } catch (error) {
    if (error instanceof OfficeTextError) throw error;
    throw unreadable();
  }
  refuseMacros(zip, await zip.text("[Content_Types].xml"));
  let text: string;
  try {
    text = kind === "docx" ? await docxText(zip) : kind === "xlsx" ? await xlsxText(zip) : await pptxText(zip);
  } catch (error) {
    if (error instanceof OfficeTextError) throw error;
    throw unreadable();
  }
  const trimmed = text.trim();
  if (trimmed === "") throw new OfficeTextError("This file has no text in it.", "empty");
  return trimmed.slice(0, MAX_TEXT_CHARS);
}
