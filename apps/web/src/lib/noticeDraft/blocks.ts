/**
 * The server's draft, split into document blocks for rendering.
 *
 * Only the markdown `compliance/caller_notice.py::_render` actually emits is recognised:
 * `#`/`##` headings, `> ` quote lines (the draft warning), `- ` list items, paragraphs
 * whose hard-wrapped lines join with a space as markdown joins them, and `**bold**`. Any
 * other syntax falls through as literal text, so the worst a new construct can do is show
 * its own markers, never lose words.
 *
 * Blanks are lifted out FIRST and replaced by a sentinel, because a blank can span a line
 * break and the line-based pass below would otherwise cut it in two.
 */

import { segment } from "./blanks";

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; parts: Inline[] }
  | { kind: "blank"; key: string; raw: string };

export type Block =
  | { kind: "heading"; level: 1 | 2; parts: Inline[] }
  | { kind: "quote"; parts: Inline[] }
  | { kind: "list"; items: Inline[][] }
  | { kind: "paragraph"; parts: Inline[] };

const OPEN = "\u0000";
const CLOSE = "\u0001";

export function parseNotice(markdown: string): Block[] {
  const blanks: { key: string; raw: string }[] = [];
  const flat = segment(markdown)
    .map((part) => {
      if (part.kind === "text") return part.text;
      blanks.push({ key: part.key, raw: part.raw });
      return `${OPEN}${blanks.length - 1}${CLOSE}`;
    })
    .join("");

  const inline = (text: string): Inline[] => parseInline(text, blanks);
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let quote: string[] = [];
  let list: string[] | null = null;

  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", parts: inline(paragraph.join(" ")) });
    if (quote.length) blocks.push({ kind: "quote", parts: inline(quote.join(" ")) });
    if (list) blocks.push({ kind: "list", items: list.map(inline) });
    paragraph = [];
    quote = [];
    list = null;
  };

  for (const rawLine of flat.split("\n")) {
    const line = rawLine.trimEnd();
    const heading = /^(#{1,2})\s+(.*)$/.exec(line);
    if (!line.trim()) {
      flush();
    } else if (heading) {
      flush();
      blocks.push({ kind: "heading", level: heading[1].length as 1 | 2, parts: inline(heading[2]) });
    } else if (line.startsWith(">")) {
      if (paragraph.length || list) flush();
      quote.push(line.replace(/^>\s?/, ""));
    } else if (/^- /.test(line)) {
      if (!list) flush();
      (list ??= []).push(line.slice(2));
    } else if (list) {
      // A wrapped continuation of the last item.
      list[list.length - 1] += ` ${line.trim()}`;
    } else {
      if (quote.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

function parseInline(text: string, blanks: { key: string; raw: string }[]): Inline[] {
  const out: Inline[] = [];
  const strong = /\*\*(.+?)\*\*/g;
  let last = 0;
  for (const match of text.matchAll(strong)) {
    const at = match.index ?? 0;
    if (at > last) out.push(...withBlanks(text.slice(last, at), blanks));
    out.push({ kind: "strong", parts: withBlanks(match[1], blanks) });
    last = at + match[0].length;
  }
  if (last < text.length) out.push(...withBlanks(text.slice(last), blanks));
  return out;
}

function withBlanks(text: string, blanks: { key: string; raw: string }[]): Inline[] {
  const out: Inline[] = [];
  const sentinel = new RegExp(`${OPEN}(\\d+)${CLOSE}`, "g");
  let last = 0;
  for (const match of text.matchAll(sentinel)) {
    const at = match.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    const blank = blanks[Number(match[1])];
    if (blank) out.push({ kind: "blank", key: blank.key, raw: blank.raw });
    last = at + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
