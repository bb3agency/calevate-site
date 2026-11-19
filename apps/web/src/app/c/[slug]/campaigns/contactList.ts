/**
 * A campaign's contact list, as the browser holds it before upload: parsing, checking and
 * the request it becomes. React-free so the rules are tested without a render.
 *
 * Every limit here is the server's, mirrored so a list is refused (or a row marked) before
 * the click rather than by a 422 that rejects the whole upload:
 * - `AddContactsIn.contacts` is 1–5,000 rows (`apps/api/campaigns/routes.py:129`);
 * - `ContactIn.phone` is 8–20 characters and `name` at most 120 (`routes.py:118-119`);
 * - `custom` holds at most 10 variables, names up to 128 and values up to 200 characters
 *   (`routes.py:112-114`); `phone` and `name` cannot be variable names, because the route
 *   writes the row's own phone and name over any variable of that name
 *   (`campaigns/routes.py::add_contacts`);
 * - a request body is at most 2 MiB (`apps/api/core/middleware.py:71`).
 *
 * The phone rules mirror `apps/api/ingest/service.py::normalize_phone`, which the upload
 * runs (`campaigns/service.py::add_contacts`), plus the India-only drop that function's
 * caller applies (`INDIA_E164_PREFIX`). The server stays the authority: it re-normalises,
 * dedupes across uploads, and reports what it added.
 */

import { normalizePhone } from "@/lib/phoneNumber";

export { normalizePhone };

export const MAX_CONTACTS_PER_UPLOAD = 5000;
export const MAX_VARIABLES = 10;
export const MAX_VARIABLE_NAME = 128;
export const MAX_VARIABLE_VALUE = 200;
export const MAX_NAME = 120;
export const MAX_BODY_BYTES = 2 * 1024 * 1024;
/** Larger than any file whose rows could fit the body cap; refused before it is read. */
export const MAX_FILE_BYTES = 4 * 1024 * 1024;

const RESERVED = new Set(["phone", "name"]);

/** One contact as the editor holds it. `id` is local, for React keys and removal. */
export interface ContactEntry {
  id: string;
  phone: string;
  name: string;
  vars: Record<string, string>;
}

/** The shape `POST /v1/campaigns/{id}/contacts` takes for one row. */
export interface ContactPayload {
  phone: string;
  name?: string;
  custom?: Record<string, string>;
}

export type RowStatus =
  | { kind: "ready"; e164: string }
  | { kind: "duplicate"; e164: string }
  | { kind: "invalid"; reason: string };

export interface CheckedRow {
  entry: ContactEntry;
  status: RowStatus;
}

export interface CheckedList {
  rows: CheckedRow[];
  ready: ContactPayload[];
  counts: { ready: number; invalid: number; duplicate: number };
  /** The variable columns, in first-seen order. */
  variables: string[];
  /** Why the list as a whole cannot be sent, if it cannot. */
  refusal: string | null;
}

/**
 * A picked file's bytes as text, by its byte-order mark. Excel's "Unicode Text (*.txt)",
 * the save that keeps Telugu on older Windows Excel, writes tab-separated UTF-16LE behind
 * `FF FE`; `File.text()` always decodes UTF-8 and turned every such file into noise. No
 * mark means UTF-8, the server's rule for uploaded text (`workers/document_text.py`).
 */
export function decodeTextFile(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder("utf-16le").decode(bytes);
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder("utf-16be").decode(bytes);
  return new TextDecoder("utf-8").decode(bytes);
}

/**
 * CSV text → rows of cells. Handles a byte-order mark, CRLF / LF / CR line ends, quoted
 * fields with embedded commas, quotes (`""`) and line breaks, and the delimiter an Excel
 * export uses in locales where the comma is the decimal mark (`;`) or a pasted
 * spreadsheet range (tab). Blank lines are dropped.
 */
export function parseCsv(input: string): string[][] {
  const text = input.replace(/^﻿/, "");
  const firstLine = text.split(/\r\n|\n|\r/, 1)[0] ?? "";
  const delimiter = pickDelimiter(firstLine);
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"' && cell.trim() === "") {
      quoted = true;
      cell = "";
    } else if (char === delimiter) {
      row.push(cell.trim());
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell.trim());
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  row.push(cell.trim());
  rows.push(row);
  return rows.filter((cells) => cells.some((value) => value !== ""));
}

function pickDelimiter(line: string): string {
  const counts = [",", ";", "\t"].map((d) => [d, line.split(d).length - 1] as const);
  const [best, count] = counts.reduce((a, b) => (b[1] > a[1] ? b : a));
  return count > 0 ? best : ",";
}

const PHONE_HEADER = /phone|mobile|number|contact|whatsapp|msisdn/i;
/** Words that name a phone column on their own; "number" and "contact" also head
 *  "Registration number", "Number of acres" and "Contact name". */
const STRONG_PHONE_HEADER = /phone|mobile|whatsapp|msisdn/i;
const NAME_HEADER = /name/i;
/** Headers that name the person on the row. "Contact name" heads a phone-header word, so it
 *  is listed here rather than left to the phone rules. */
const PERSON_HEADERS = new Set([
  "contact name",
  "contact person",
  "customer name",
  "customer",
  "client name",
  "full name",
  "person",
  "person name",
]);
/** Words that make a "… name" header name something other than the person called: a place,
 *  a business or a thing, or a relative ("Father name"). Such a column is kept as a variable
 *  unless no other header could be the name. */
const NOT_THE_PERSON =
  /\b(village|town|city|area|place|location|locality|district|mandal|taluk|state|street|road|colony|business|shop|store|company|firm|brand|branch|office|school|college|hospital|clinic|product|item|crop|project|plan|scheme|course|father|mother|husband|wife|spouse|guardian|son|daughter|nominee|reference|referred)\b/;

/** Lower case, separators as single spaces, so "Customer_Name " reads "customer name". */
function headerWords(cell: string): string {
  return cell
    .toLowerCase()
    .replace(/[_\-./:'’]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * The name column of a list with a header row, best first: a column headed exactly "name";
 * one that names the person (`PERSON_HEADERS`, or the business's own word for its callers,
 * "Farmer name" for a business whose callers are farmers); one containing "name" that does
 * not qualify a place, business, thing or relative; and only then any header containing
 * "name". The first header containing the word used to win, which took "Village name" or
 * "Business name" as every contact's name.
 */
function nameColumn(header: string[], phoneIdx: number, callerNoun: string | null): number {
  const noun = callerNoun ? headerWords(callerNoun) : "";
  const person = (words: string) => PERSON_HEADERS.has(words) || (noun !== "" && (words === noun || words === `${noun} name`));
  const ranks: ((words: string, raw: string) => boolean)[] = [
    (words) => words === "name",
    person,
    (words, raw) => NAME_HEADER.test(raw) && !NOT_THE_PERSON.test(words),
    (_words, raw) => NAME_HEADER.test(raw),
  ];
  for (const matches of ranks) {
    const index = header.findIndex((cell, i) => i !== phoneIdx && matches(headerWords(cell), cell));
    if (index >= 0) return index;
  }
  return -1;
}

/**
 * The phone column of a list with a header row: of the columns whose header could name
 * one, the one whose cells read as phone numbers most often, a strong header word breaking
 * a tie. The first matching header alone took "Registration number" over a later "Phone"
 * and read every row as a bad number, or an ID as one.
 */
function phoneColumn(header: string[], body: string[][]): number {
  let best = -1;
  let bestScore = -1;
  header.forEach((cell, index) => {
    if (!PHONE_HEADER.test(cell)) return;
    const readable = body.filter((cells) => normalizePhone(cells[index] ?? "") !== null).length;
    const score = readable * 2 + (STRONG_PHONE_HEADER.test(cell) ? 1 : 0);
    if (score > bestScore) {
      best = index;
      bestScore = score;
    }
  });
  return best;
}

let nextId = 0;
const newId = () => `c${(nextId += 1)}`;

/**
 * Cells → entries. A first row naming a phone column is a header: its phone and name
 * columns are found by name, and every other named column becomes a variable. Without a
 * header the first column is the phone and the second the name, and nothing else is kept,
 * because a variable needs a name. `callerNoun` is what the business calls its callers
 * (`BusinessCapabilities.callerNoun`), when known.
 */
export function rowsToEntries(
  table: string[][],
  callerNoun: string | null = null,
): { entries: ContactEntry[]; dropped: string[] } {
  if (table.length === 0) return { entries: [], dropped: [] };
  const header = table[0];
  const hasHeader = header.some((cell) => PHONE_HEADER.test(cell)) && !header.some((cell) => normalizePhone(cell));
  const dropped: string[] = [];
  if (!hasHeader) {
    return {
      entries: table.map((cells) => ({ id: newId(), phone: cells[0] ?? "", name: cells[1] ?? "", vars: {} })),
      dropped,
    };
  }
  const phoneIdx = phoneColumn(header, table.slice(1));
  const nameIdx = nameColumn(header, phoneIdx, callerNoun);
  const varCols: { index: number; key: string }[] = [];
  header.forEach((cell, index) => {
    if (index === phoneIdx || index === nameIdx || cell === "") return;
    if (RESERVED.has(cell.toLowerCase()) || cell.length > MAX_VARIABLE_NAME || varCols.length >= MAX_VARIABLES) {
      dropped.push(cell);
      return;
    }
    varCols.push({ index, key: cell });
  });
  const entries = table.slice(1).map((cells) => {
    const vars: Record<string, string> = {};
    for (const { index, key } of varCols) {
      const value = cells[index] ?? "";
      if (value !== "") vars[key] = value;
    }
    return { id: newId(), phone: cells[phoneIdx] ?? "", name: nameIdx >= 0 ? (cells[nameIdx] ?? "") : "", vars };
  });
  return { entries, dropped };
}

export function newEntry(phone: string, name: string): ContactEntry {
  return { id: newId(), phone: phone.trim(), name: name.trim(), vars: {} };
}

/** Each row's verdict, the request the ready ones become, and the counts the screen shows. */
export function checkContacts(entries: ContactEntry[]): CheckedList {
  const seen = new Set<string>();
  const variables: string[] = [];
  const rows: CheckedRow[] = entries.map((entry) => {
    for (const key of Object.keys(entry.vars)) if (!variables.includes(key)) variables.push(key);
    return { entry, status: verdict(entry, seen) };
  });
  const ready: ContactPayload[] = [];
  const counts = { ready: 0, invalid: 0, duplicate: 0 };
  for (const { entry, status } of rows) {
    counts[status.kind] += 1;
    if (status.kind === "ready") {
      ready.push({
        phone: status.e164,
        ...(entry.name ? { name: entry.name } : {}),
        ...(Object.keys(entry.vars).length ? { custom: entry.vars } : {}),
      });
    }
  }
  return { rows, ready, counts, variables, refusal: refusalFor(ready) };
}

function verdict(entry: ContactEntry, seen: Set<string>): RowStatus {
  const e164 = normalizePhone(entry.phone);
  if (!e164) return { kind: "invalid", reason: "We can't read this number" };
  if (!e164.startsWith("+91")) return { kind: "invalid", reason: "Only Indian (+91) numbers are called" };
  if (entry.name.length > MAX_NAME) return { kind: "invalid", reason: `Name is over ${MAX_NAME} characters` };
  if (Object.values(entry.vars).some((value) => value.length > MAX_VARIABLE_VALUE)) {
    return { kind: "invalid", reason: `A value is over ${MAX_VARIABLE_VALUE} characters` };
  }
  if (seen.has(e164)) return { kind: "duplicate", e164 };
  seen.add(e164);
  return { kind: "ready", e164 };
}

function refusalFor(ready: ContactPayload[]): string | null {
  if (ready.length > MAX_CONTACTS_PER_UPLOAD) {
    return `One upload takes at most ${MAX_CONTACTS_PER_UPLOAD.toLocaleString("en-IN")} contacts. Remove some, and add the rest from the campaign afterwards.`;
  }
  const bytes = new TextEncoder().encode(JSON.stringify({ contacts: ready })).length;
  if (bytes > MAX_BODY_BYTES) {
    return "This list is too large to send in one upload. Remove some columns or rows, and add the rest from the campaign afterwards.";
  }
  return null;
}

/**
 * The sample file: a header, two contacts in the non-dialable demo range, one variable. The
 * variable is the core lead detail "preferred time" (`calevate_shared.lead_fields`), which
 * every business has; a booking column assumed bookings (L3-22).
 */
export const SAMPLE_CSV = [
  "phone,name,preferred_time",
  "+919900000001,Priya,Tuesday 4pm",
  "+919900000002,Ravi,Wednesday 11am",
].join("\r\n");
