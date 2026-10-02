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
 *   spreads `custom` over them (`routes.py:585`);
 * - a request body is at most 2 MiB (`apps/api/core/middleware.py:71`).
 *
 * The phone rules mirror `apps/api/ingest/service.py::normalize_phone`, which the upload
 * runs (`campaigns/service.py::add_contacts`), plus the India-only drop that function's
 * caller applies (`INDIA_E164_PREFIX`). The server stays the authority: it re-normalises,
 * dedupes across uploads, and reports what it added.
 */

export const MAX_CONTACTS_PER_UPLOAD = 5000;
export const MAX_VARIABLES = 10;
export const MAX_VARIABLE_NAME = 128;
export const MAX_VARIABLE_VALUE = 200;
export const MAX_NAME = 120;
export const MAX_BODY_BYTES = 2 * 1024 * 1024;
/** Larger than any file whose rows could fit the body cap; refused before it is read. */
export const MAX_FILE_BYTES = 4 * 1024 * 1024;

const RESERVED = new Set(["phone", "name"]);
const E164 = /^\+[1-9]\d{7,14}$/;

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

/** Mirror of `ingest/service.py::normalize_phone`. `null` means "not a number we can read". */
export function normalizePhone(raw: string): string | null {
  const text = raw.trim();
  const plusCount = (text.match(/\+/g) ?? []).length;
  if (plusCount > 1 || (plusCount === 1 && !text.startsWith("+"))) return null;
  const digits = text.replace(/\D/g, "");
  let candidate: string | null = null;
  if (text.startsWith("+")) {
    candidate = digits.length >= 10 && digits.length <= 15 ? `+${digits}` : null;
  } else if (digits.length === 10 && "6789".includes(digits[0])) {
    candidate = `+91${digits}`;
  } else if (digits.length === 11 && digits[0] === "0" && "6789".includes(digits[1])) {
    // The trunk prefix an Indian writes before a mobile; it is not part of the number.
    candidate = `+91${digits.slice(1)}`;
  } else if (digits.length === 12 && digits.startsWith("91")) {
    candidate = `+${digits}`;
  }
  return candidate && E164.test(candidate) ? candidate : null;
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
const NAME_HEADER = /name/i;

let nextId = 0;
const newId = () => `c${(nextId += 1)}`;

/**
 * Cells → entries. A first row naming a phone column is a header: its phone and name
 * columns are found by name, and every other named column becomes a variable. Without a
 * header the first column is the phone and the second the name, and nothing else is kept,
 * because a variable needs a name.
 */
export function rowsToEntries(table: string[][]): { entries: ContactEntry[]; dropped: string[] } {
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
  const phoneIdx = header.findIndex((cell) => PHONE_HEADER.test(cell));
  const nameIdx = header.findIndex((cell, i) => i !== phoneIdx && NAME_HEADER.test(cell));
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

/** The sample file: a header, two contacts in the non-dialable demo range, one variable. */
export const SAMPLE_CSV = [
  "phone,name,appointment_time",
  "+919900000001,Priya,Tuesday 4pm",
  "+919900000002,Ravi,Wednesday 11am",
].join("\r\n");
