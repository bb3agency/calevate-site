/**
 * The assistant's answer, rendered — bold, bullets, numbered steps and inline code.
 *
 * WHY THIS EXISTS. `prompt.py` tells the model to answer in plain sentences and not to
 * emit "markdown headings, no bullet-point walls". Models comply with that most of the
 * time and not always, and a question like "list every action you can perform" is exactly
 * the shape that makes one reach for a list whatever the prompt says. Rendered through
 * `whitespace-pre-wrap` the result reached the client as literal `**Features:**` and `*`
 * bullets — the assistant visibly failing to format its own answer, on the one screen
 * whose job is to look competent.
 *
 * WHY NOT A LIBRARY. `react-markdown` and friends bring a parser, a plugin chain and a
 * sanitiser to render four constructs, and hard rule 9 makes every new dependency in this
 * tree something to justify rather than assume. This builds React ELEMENTS from the text,
 * so there is no `dangerouslySetInnerHTML`, no HTML parsing, and nothing a model could
 * emit — a `<script>` tag, an `onerror=`, a `javascript:` URL — is anything but literal
 * characters in a text node. That is a smaller attack surface than a sanitiser, not a
 * bigger one, because there is no path from text to markup at all.
 *
 * WHY NOT MORE MARKDOWN. Links, images, tables and raw HTML are deliberately NOT
 * supported and render as their literal characters. A link would let a model put a
 * clickable destination in front of a client — and the one thing this assistant must not
 * do is hand somebody a URL it invented (`prompt.py`'s "do not fabricate a FACT"). The
 * subset here is what makes a list readable and nothing that navigates.
 *
 * IT RUNS ON PARTIAL TEXT. The same component renders the streaming buffer, so it is
 * called on every chunk with a string that may end mid-construct. An unterminated `**`
 * therefore renders as literal asterisks rather than swallowing the rest of the answer —
 * the alternative is text that flickers between bold and not as tokens arrive.
 */

import type { JSX, ReactNode } from "react";

/** Bold, then inline code. Ordered so a `**` inside backticks stays literal. */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;

/** `* `, `- ` or `• ` at the start of a line, with any leading indent. */
const BULLET = /^\s*[*\-•]\s+(.*)$/;

/** `1.` / `1)` at the start of a line. */
const NUMBERED = /^\s*(\d{1,2})[.)]\s+(.*)$/;

/** A line that is only `**Something:**` — the model's stand-in for a heading. */
const LEAD_IN = /^\*\*([^*]+)\*\*:?\s*$/;

function inline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((piece, i) => {
    const key = `${keyPrefix}-${i}`;
    if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
      return (
        <strong key={key} className="font-semibold">
          {piece.slice(2, -2)}
        </strong>
      );
    }
    if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 2) {
      return (
        <code key={key} className="rounded bg-black/5 px-1 py-0.5 text-[0.9em] dark:bg-white/10">
          {piece.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{piece}</span>;
  });
}

type Block =
  | { kind: "text"; lines: string[] }
  | { kind: "lead"; text: string }
  | { kind: "bullets"; items: string[] }
  | { kind: "steps"; items: string[] };

/**
 * Lines into blocks, so a run of bullets becomes ONE list rather than N paragraphs.
 *
 * A single pass with an accumulator rather than a grammar: the input is a few hundred
 * characters of chat, and a parser would be more code than the thing it parses.
 */
function blocks(answer: string): Block[] {
  const out: Block[] = [];
  const flush = (): void => {
    const last = out[out.length - 1];
    if (last?.kind === "text" && last.lines.every((line) => line.trim() === "")) out.pop();
  };
  for (const line of answer.split("\n")) {
    const lead = LEAD_IN.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const last = out[out.length - 1];
    if (lead) {
      flush();
      out.push({ kind: "lead", text: lead[1].trim() });
    } else if (bullet) {
      flush();
      if (last?.kind === "bullets") last.items.push(bullet[1]);
      else out.push({ kind: "bullets", items: [bullet[1]] });
    } else if (numbered) {
      flush();
      if (last?.kind === "steps") last.items.push(numbered[2]);
      else out.push({ kind: "steps", items: [numbered[2]] });
    } else if (line.trim() === "") {
      flush();
      out.push({ kind: "text", lines: [] });
    } else if (last?.kind === "text") {
      last.lines.push(line);
    } else {
      out.push({ kind: "text", lines: [line] });
    }
  }
  return out.filter((block) => block.kind !== "text" || block.lines.length > 0);
}

/**
 * Render one assistant answer.
 *
 * A `<div>` and not a `<p>`: the answer can contain a `<ul>`, and a list inside a
 * paragraph is invalid HTML that React will not warn about but the browser silently
 * restructures — which moves the list out of the styled container.
 */
export function AnswerText({ text, className }: { text: string; className?: string }): JSX.Element {
  return (
    <div className={className}>
      {blocks(text).map((block, i) => {
        if (block.kind === "lead") {
          return (
            <p key={i} className="mt-2 font-semibold text-ink first:mt-0">
              {block.text}
            </p>
          );
        }
        if (block.kind === "bullets") {
          return (
            <ul key={i} className="mt-1 list-disc space-y-1 pl-5 text-ink first:mt-0">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, `${i}-${j}`)}</li>
              ))}
            </ul>
          );
        }
        if (block.kind === "steps") {
          return (
            <ol key={i} className="mt-1 list-decimal space-y-1 pl-5 text-ink first:mt-0">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, `${i}-${j}`)}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={i} className="mt-2 whitespace-pre-wrap text-ink first:mt-0">
            {inline(block.lines.join("\n"), String(i))}
          </p>
        );
      })}
    </div>
  );
}
