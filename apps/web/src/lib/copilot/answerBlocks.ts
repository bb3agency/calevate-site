/**
 * The assistant's answer, cut into blocks — the pure half of `answerText.tsx`.
 *
 * WHY IT IS ITS OWN MODULE. This is a parser: string in, data out, no React. It is also
 * the EXPENSIVE half — it rescans the whole answer on every call, and the panel calls it
 * once per streamed token, so one answer's cost is quadratic in its own length and used to
 * be multiplied again by every settled turn on screen. `AnswerText` is memoised to remove
 * the second of those, and a memo nobody can observe is a claim rather than a fix: a test
 * can count calls to an imported function where it cannot count renders of a component,
 * so the seam that makes the memo assertable is this file
 * (`tests/copilotAnswerText.test.tsx`).
 */

/** `* `, `- ` or `• ` at the start of a line, with any leading indent. */
const BULLET = /^\s*[*\-•]\s+(.*)$/;

/** `1.` / `1)` at the start of a line. */
const NUMBERED = /^\s*(\d{1,2})[.)]\s+(.*)$/;

/** A line that is only `**Something:**` — the model's stand-in for a heading. */
const LEAD_IN = /^\*\*([^*]+)\*\*:?\s*$/;

export type Block =
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
export function blocks(answer: string): Block[] {
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
