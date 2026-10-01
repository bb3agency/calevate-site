/**
 * The blanks in the server's caller-notice draft, and the filled text built from them.
 *
 * The draft (`compliance/caller_notice.py::_render`) marks every fact only the client can
 * supply as `{{IN CAPITALS}}`, and its disclaimer tells the client so. Two properties of
 * the real text decide how this parses:
 *
 * - A blank can span a line break: the generator hard-wraps its paragraphs, and the
 *   purpose blank ("ADD ANY OTHER PURPOSE — AND IF YOU CALL⏎PEOPLE FOR MARKETING…") is
 *   broken across two lines. So the pattern matches across newlines, non-greedily.
 * - A SINGLE-brace blank is also accepted. The regulator blank was once emitted as
 *   `{IF YOUR OWN SECTOR REGULATOR…}` (an f-string escape), and a cached or older draft
 *   may still carry it. A single-brace match must contain no lowercase letter, so an
 *   ordinary brace in prose or in an agent's name never turns into a field.
 *
 * Not `lib/legal/placeholders.ts`'s pattern: that one is for our own documents, whose
 * tokens are `[A-Z0-9_ ]` on one line, and it matches neither the em dash nor the line
 * break this draft's blanks carry.
 *
 * A blank's KEY is its inside with whitespace collapsed, so the business-name blank that
 * appears twice is one field filled in both places, and a value typed against one blank
 * can never land in a differently-worded one.
 */

import { lookup } from "@/lib/lookup";

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "blank"; key: string; raw: string };

const BLANK = /\{\{([\s\S]+?)\}\}|\{([^{}]+)\}/g;

export function blankKey(inner: string): string {
  return inner.replace(/\s+/g, " ").trim();
}

export function segment(markdown: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const match of markdown.matchAll(BLANK)) {
    const inner = match[1] ?? match[2] ?? "";
    // A single-brace match is a blank only when it reads like one: capitals, no prose.
    if (match[1] === undefined && /[a-z]/.test(inner)) continue;
    const key = blankKey(inner);
    if (!key) continue;
    const start = match.index ?? 0;
    if (start > last) out.push({ kind: "text", text: markdown.slice(last, start) });
    out.push({ kind: "blank", key, raw: match[0] });
    last = start + match[0].length;
  }
  if (last < markdown.length) out.push({ kind: "text", text: markdown.slice(last) });
  return out;
}

/** The distinct blanks, in the order they first appear. */
export function blankKeys(markdown: string): string[] {
  const seen = new Set<string>();
  for (const part of segment(markdown)) if (part.kind === "blank") seen.add(part.key);
  return [...seen];
}

export type BlankValues = Record<string, string>;

/** A non-empty value for `key`, or null. Through `lookup`: the keys are server text. */
export function valueOf(values: BlankValues, key: string): string | null {
  const value = lookup(values, key)?.trim() ?? "";
  return value ? value : null;
}

/**
 * The draft with every FILLED blank replaced by its value. An unfilled blank is left
 * exactly as the server wrote it, braces included, so nothing silently disappears from a
 * notice on its way to an advocate.
 */
export function fill(markdown: string, values: BlankValues): string {
  return segment(markdown)
    .map((part) => (part.kind === "text" ? part.text : (valueOf(values, part.key) ?? part.raw)))
    .join("");
}

/** The filled draft as plain text: heading, bold and quote markers removed, words untouched. */
export function toPlainText(markdown: string): string {
  return markdown
    .split("\n")
    .map((line) => line.replace(/^#{1,6}\s+/, "").replace(/^>\s?/, ""))
    .join("\n")
    .replace(/\*\*(.+?)\*\*/g, "$1");
}

/** "YOUR REGISTERED BUSINESS NAME" → "Your registered business name", for labels only. */
export function blankLabel(key: string): string {
  const lower = key.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
