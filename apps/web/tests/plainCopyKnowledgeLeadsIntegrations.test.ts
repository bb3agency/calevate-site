import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { uploadState } from "@/app/c/[slug]/knowledge/uploadCopy";
import type { KbUpload } from "@/lib/api/kb";

/**
 * "BUTTONS, NOT PARAGRAPHS" for the knowledge, lead-sources and integrations screens.
 *
 * Their readers are small-business owners, often on a phone and often reading English as
 * a second language, so every line a screen shows BY DEFAULT is short. An explanation is
 * allowed to be longer only behind a tap: an `InfoTip` (ⓘ), a section's `info`, a
 * checklist row's `info`. Those are stripped before the scan, so moving a sentence behind
 * a tap is the way to pass, and adding a paragraph back to the default view fails here.
 *
 * Pip's own context (`copilot.ts`) is never shown and is skipped.
 */

const LIMIT = 60;
const ROOT = join(__dirname, "..", "src", "app", "c", "[slug]");
const AREAS = ["knowledge", "lead-sources", "integrations"];

/**
 * Lines that stay longer on purpose, each with its reason. A setup step that names the
 * exact values a person must find in another product is shortened around the values,
 * never by dropping them.
 */
const ALLOWED: { file: string; startsWith: string; why: string }[] = [
  {
    file: "knowledge/TeachBox.tsx",
    startsWith: "Read the photo or file I attach",
    why: "READ_FILE_REQUEST, the words prefilled in Pip's own ask box, which the person edits",
  },
  {
    file: "integrations/whatsapp/KeyGuides.tsx",
    startsWith: "Generate a token with business management",
    why: "names the three exact permissions Meta lists",
  },
  {
    file: "knowledge/uploadCopy.ts",
    startsWith: "Send what you already have",
    why: "READ_KINDS_SENTENCE, shown only inside the File view's ⓘ",
  },
  {
    file: "knowledge/uploadCopy.ts",
    startsWith: "You can save a PDF too",
    why: "PDF_NOTE, shown only inside the File view's ⓘ",
  },
  {
    file: "knowledge/uploadCopy.ts",
    startsWith: "We read that one page so you and",
    why: "LINK_NOTE, shown only inside the Link view's ⓘ",
  },
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

/** Comments, and everything that only appears behind a tap, removed. */
function defaultViewSource(source: string): string {
  return source
    .replace(/\r\n/g, "\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1")
    .replace(/<InfoTip\b[\s\S]*?<\/InfoTip>/g, "")
    .replace(/\binfo=\{[\s\S]*?\}\s*(?=\n|\/?>)/g, "")
    .replace(/\binfo=("[^"]*")/g, "")
    .replace(/\binfo:\s*"[^"]*"/g, "");
}

/** Visible-copy candidates: JSX text, and string literals that read as a sentence. */
function sentences(source: string): string[] {
  const out: string[] = [];
  for (const match of source.matchAll(/>([^<>{}]+)</g)) {
    const text = match[1]!.replace(/\s+/g, " ").trim();
    if (/[A-Za-z]{2,} [A-Za-z]/.test(text) && !/[;=]|=>/.test(text)) out.push(text);
  }
  for (const match of source.matchAll(/"((?:[^"\\\n]|\\.)*)"|`([^`]*)`/g)) {
    const text = (match[1] ?? match[2] ?? "").replace(/\$\{[^}]*\}/g, "12").replace(/\s+/g, " ").trim();
    // Copy starts like a sentence; class lists, paths and keys do not.
    if (/^[A-Z0-9₹“"'(]/.test(text) && / [a-z]/.test(text)) out.push(text);
  }
  return out;
}

describe("default copy on the knowledge, lead-sources and integrations screens", () => {
  for (const area of AREAS) {
    it(`keeps every default line on ${area} to ${LIMIT} characters or fewer`, () => {
      const long: string[] = [];
      for (const path of files(join(ROOT, area))) {
        if (path.endsWith("copilot.ts")) continue;
        const file = relative(ROOT, path).replace(/\\/g, "/");
        for (const text of sentences(defaultViewSource(readFileSync(path, "utf8")))) {
          if (text.length <= LIMIT) continue;
          if (ALLOWED.some((a) => a.file === file && text.startsWith(a.startsWith))) continue;
          long.push(`${file}: (${text.length}) ${text}`);
        }
      }
      expect(long).toEqual([]);
    });
  }

  it("says every file and link state in one short line", () => {
    const base: KbUpload = {
      source_id: "s1",
      version: 1,
      id: "u1",
      name: "Price list",
      filename: "price.docx",
      source_kind: "docx",
      source_url: null,
      ingest_status: "received",
      review_state: "approved",
      is_live: false,
      text_provenance: null,
      reaches_agents: true,
      read_state: null,
      read_detail: null,
    };
    const variants: Partial<KbUpload>[] = [
      { is_live: true },
      { ingest_status: "error" },
      { ingest_status: "conversion_failed" },
      { ingest_status: "conversion_unavailable" },
      { review_state: "rejected" },
      { review_state: "archived" },
      { text_provenance: "ocr", review_state: "pending_approval" },
      { text_provenance: "parsed", review_state: "pending_approval" },
      { ingest_status: "received" },
      { ingest_status: "converting", source_kind: "url" },
      { ingest_status: "processing" },
      { ingest_status: "ready", review_state: "approved" },
      { ingest_status: "ready", review_state: "pending_approval" },
      { source_kind: "pdf", read_state: "reading" },
      { source_kind: "pdf", read_state: "failed" },
      { source_kind: "pdf", read_state: "read", reaches_agents: false },
      { source_kind: "url", read_state: "read", reaches_agents: false },
    ];
    for (const variant of variants) {
      const state = uploadState({ ...base, ...variant });
      expect(state.label.length, state.label).toBeLessThanOrEqual(30);
      expect(state.meaning.length, state.meaning).toBeLessThanOrEqual(LIMIT);
    }
  });
});
