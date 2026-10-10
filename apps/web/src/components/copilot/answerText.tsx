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

import { memo, useEffect, useRef, type ReactNode } from "react";

import { blocks, type Block } from "@/lib/copilot/answerBlocks";

/** Bold, then inline code. Ordered so a `**` inside backticks stays literal. */
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;

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

/**
 * Render one assistant answer.
 *
 * A `<div>` and not a `<p>`: the answer can contain a `<ul>`, and a list inside a
 * paragraph is invalid HTML that React will not warn about but the browser silently
 * restructures — which moves the list out of the styled container.
 */
export const AnswerText = memo(function AnswerText({
  text,
  className,
  reveal = false,
}: {
  text: string;
  className?: string;
  /** Fade each block in the first time it is seen (the answer arriving); see `useReveal`. */
  reveal?: boolean;
}) {
  const list = blocks(text);
  const revealClass = useReveal(list, reveal);
  return (
    <div className={className}>
      {list.map((block, i) => {
        const cls = revealClass(i);
        if (block.kind === "lead") {
          return (
            <p key={i} className={`mt-2 font-semibold text-ink first:mt-0 ${cls}`} style={delay(cls, i)}>
              {block.text}
            </p>
          );
        }
        if (block.kind === "bullets") {
          return (
            <ul key={i} className={`mt-1 list-disc space-y-1 pl-5 text-ink first:mt-0 ${cls}`} style={delay(cls, i)}>
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, `${i}-${j}`)}</li>
              ))}
            </ul>
          );
        }
        if (block.kind === "steps") {
          return (
            <ol key={i} className={`mt-1 list-decimal space-y-1 pl-5 text-ink first:mt-0 ${cls}`} style={delay(cls, i)}>
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, `${i}-${j}`)}</li>
              ))}
            </ol>
          );
        }
        return (
          <p key={i} className={`mt-2 whitespace-pre-wrap text-ink first:mt-0 ${cls}`} style={delay(cls, i)}>
            {inline(block.lines.join("\n"), String(i))}
          </p>
        );
      })}
    </div>
  );
});

/**
 * THE ANSWER ARRIVING, AS A QUIET FADE (founder, REDESIGN-2; motion dial 2).
 *
 * Block by block — a paragraph, a list — rather than word by word: an answer arrives in a
 * few large deltas, so a per-word stagger would hold back text that is already here, and a
 * typewriter caret is theatre. Each new block fades in over 200 ms with a 2px blur and lift
 * (`.answer-reveal` in globals.css), later blocks of the same arrival 60 ms apart, capped so
 * the whole answer is readable within about half a second. Reduced motion shows it at once
 * (the CSS turns the animation off).
 *
 * ONCE PER BLOCK, EVER. The streaming buffer and the finished turn are two components, so
 * the finished answer mounts again the moment the stream ends; a block whose text was
 * already shown is recorded in `SHOWN` and does not fade a second time. Whether a block
 * animates is decided when its index is first rendered and never changes afterwards,
 * because toggling the class on a mounted element would restart the animation.
 */
const SHOWN = new Set<string>();
const SHOWN_CAP = 400;

function signature(block: Block): string {
  return JSON.stringify(block);
}

function useReveal(list: Block[], reveal: boolean): (index: number) => string {
  const decided = useRef(new Map<number, boolean>());
  if (reveal) {
    for (let i = 0; i < list.length; i += 1) {
      if (!decided.current.has(i)) decided.current.set(i, !SHOWN.has(signature(list[i]!)));
    }
  }
  useEffect(() => {
    if (!reveal) return;
    if (SHOWN.size > SHOWN_CAP) SHOWN.clear();
    for (const block of list) SHOWN.add(signature(block));
  });
  return (index) => (reveal && decided.current.get(index) ? "answer-reveal" : "");
}

/** Later blocks of one arrival start a little after earlier ones, never more than 240 ms. */
function delay(cls: string, index: number): { animationDelay: string } | undefined {
  return cls ? { animationDelay: `${Math.min(index * 60, 240)}ms` } : undefined;
}
