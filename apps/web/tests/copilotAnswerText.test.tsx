/**
 * The copilot's answer rendering, and the history bound that stopped a conversation dead.
 *
 * Both defects were reported from a live screen on the same panel, and both were invisible
 * to every existing test because the suite drives the copilot with one short exchange and
 * a plain-prose answer — the two shapes neither bug appears in.
 */

import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { AnswerText } from "../src/components/copilot/answerText";
import { MAX_HISTORY, recentTurns, type CopilotTurn } from "../src/lib/copilot/useCopilotConversation";

/**
 * COUNT THE PARSES. `vi.mock` with the real implementation behind it: the assertion is
 * about how OFTEN `blocks` runs, never about what it returns, so the rendering below is
 * the real one and a wrong answer still fails the rest of this file.
 */
const parses = vi.hoisted(() => [] as string[]);

vi.mock("@/lib/copilot/answerBlocks", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/copilot/answerBlocks")>();
  return {
    ...real,
    blocks: (answer: string) => {
      parses.push(answer);
      return real.blocks(answer);
    },
  };
});

const REPO_ROOT = join(__dirname, "..", "..", "..");

function turn(role: "user" | "assistant", n: number): CopilotTurn {
  return { role, content: `${role} ${n}`, wire: `${role} ${n}` };
}

/** `n` complete exchanges, oldest first. */
function exchanges(n: number): CopilotTurn[] {
  return Array.from({ length: n }, (_, i) => [turn("user", i), turn("assistant", i)]).flat();
}

describe("the history the browser replays", () => {
  it("never exceeds the server's ceiling, however long the panel stays open", () => {
    // THE REPORTED BUG. The panel sent every turn it held, so the sixth exchange in one
    // open conversation was rejected with "history: List should have at most 10 items
    // after validation, not 12" — a validation error naming a field the person cannot
    // see, in a conversation that had been working a moment before.
    for (let count = 1; count <= 12; count += 1) {
      expect(recentTurns(exchanges(count)).length).toBeLessThanOrEqual(MAX_HISTORY);
    }
  });

  it("keeps the MOST RECENT turns, because a follow-up refers to them", () => {
    const kept = recentTurns(exchanges(9));
    expect(kept[kept.length - 1]).toEqual(turn("assistant", 8));
    expect(kept).not.toContainEqual(turn("user", 0));
  });

  it("never opens on an answer whose question was dropped", () => {
    // A plain slice of an ODD-length history starts on an assistant turn. A model handed
    // an answer with no question ahead of it reads that answer as its own earlier
    // assertion, and starts defending a claim nobody made. Costs one turn of context.
    for (let count = 1; count <= 14; count += 1) {
      const window = recentTurns([turn("assistant", -1), ...exchanges(count)]);
      if (window.length > 0) expect(window[0].role).toBe("user");
    }
  });

  it("passes a short conversation through untouched", () => {
    const short = exchanges(2);
    expect(recentTurns(short)).toEqual(short);
    expect(recentTurns([])).toEqual([]);
  });

  it("agrees with the server constant it is retyped from", () => {
    // The number lives in Python and the generated client does not surface `maxItems` as
    // a value, so this side retypes it. This is what stops the copy drifting: raising
    // MAX_HISTORY on the server without raising it here would silently keep sending the
    // old, smaller window; lowering it there would bring the 422 straight back.
    const schemas = readFileSync(join(REPO_ROOT, "apps/api/copilot/schemas.py"), "utf8");
    const declared = /^MAX_HISTORY = (\d+)$/m.exec(schemas);
    expect(declared, "MAX_HISTORY is no longer declared in copilot/schemas.py").not.toBeNull();
    expect(Number(declared?.[1])).toBe(MAX_HISTORY);
  });

  it("agrees with the PUBLISHED ceiling, which is the one the request is judged against", () => {
    // The second half, and it is not the same assertion. `schemas.py` is what the server
    // means; `openapi.json` is what has actually been published to this console, and the
    // two part company whenever somebody edits the constant without regenerating. Nothing
    // else catches that: `openapi-typescript` emits `CopilotTurn[]` because `maxItems` is
    // a validation keyword with no TypeScript to emit, and `check_openapi_fresh` ignores
    // `maxItems` among the keys it compares. A test is the only instrument left.
    const openapi = JSON.parse(
      readFileSync(join(__dirname, "..", "src/lib/api/openapi.json"), "utf8"),
    ) as {
      components: {
        schemas: { CopilotAskIn: { properties: { history: { maxItems?: number } } } };
      };
    };
    expect(openapi.components.schemas.CopilotAskIn.properties.history.maxItems).toBe(
      MAX_HISTORY,
    );
  });
});

describe("the answer the model actually sends", () => {
  it("renders a bulleted list as a list rather than as asterisks", () => {
    // THE REPORTED BUG, verbatim in shape: `prompt.py` asks for plain sentences, and
    // "list every action you can perform" is the question that makes a model ignore it.
    render(
      <AnswerText
        text={
          "I can help you with the following actions:\n\n" +
          "**Features:**\n" +
          "*   **Set Fields:** Update values in the form on your current screen.\n" +
          "*   **Leads Search:** Find leads by status."
        }
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Set Fields:");
    expect(items[0].textContent).toContain("Update values in the form on your current screen.");
    // The asterisks are GONE from what the person reads — the whole point of the fix.
    expect(screen.queryByText(/\*\*/)).toBeNull();
    expect(screen.getByText("Features:").tagName).toBe("P");
  });

  it("renders numbered steps as an ordered list", () => {
    const { container } = render(<AnswerText text={"1. Open the campaign.\n2. Press launch."} />);
    expect(container.querySelector("ol")).not.toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("emphasises inline bold and inline code without losing the surrounding words", () => {
    render(<AnswerText text="Set **status** to `qualified` before launching." />);
    expect(screen.getByText("status").tagName).toBe("STRONG");
    expect(screen.getByText("qualified").tagName).toBe("CODE");
    expect(document.body.textContent).toContain("Set status to qualified before launching.");
  });

  it("leaves a half-arrived construct literal instead of swallowing the answer", () => {
    // The streaming buffer goes through this same component on every chunk, so it is
    // called constantly with text that ends mid-token. An unterminated `**` that started
    // emphasis would make the rest of the answer flicker bold as tokens land.
    render(<AnswerText text="Your account has **outbound block" />);
    expect(document.body.textContent).toContain("Your account has **outbound block");
    expect(document.querySelector("strong")).toBeNull();
  });

  it("renders plain prose as plain paragraphs, which is the ordinary case", () => {
    render(<AnswerText text={"You have 4 leads waiting.\n\nTwo came in today."} />);
    expect(screen.getByText("You have 4 leads waiting.")).toBeTruthy();
    expect(screen.getByText("Two came in today.")).toBeTruthy();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("never turns model text into markup", () => {
    // There is no `dangerouslySetInnerHTML` on this path and no HTML parsing, so anything
    // a model emits is a text node. Asserted rather than assumed: this is the property
    // that makes rendering an untrusted string safe, and it is one refactor away from
    // being lost.
    const hostile = '<img src=x onerror="alert(1)"> and [a link](javascript:alert(2))';
    const { container } = render(<AnswerText text={hostile} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("onerror=");
  });
});

/**
 * THE COST OF A LONG ANSWER, AND WHY IT IS ASSERTED RATHER THAN ASSUMED.
 *
 * `blocks()` rescans the WHOLE answer every time it is called and `inline()` allocates
 * fresh elements for every block of it. The panel re-renders on every streamed token, so
 * without memoisation each token re-parsed every settled turn as well as the one arriving:
 * a twenty-turn conversation paid twenty parses per token, hundreds of times per answer,
 * on the mid-range Android CPU this console is actually used from.
 *
 * `React.memo` alone is not a testable claim — a memo that was silently dropped in a
 * refactor looks exactly like one that is working. Counting the parser's calls is, which
 * is what `lib/copilot/answerBlocks.ts` exists as a separate module for.
 */
describe("the cost of re-rendering a transcript", () => {
  it("DOES NOT RE-PARSE A SETTLED ANSWER when something else on the panel changes", () => {
    parses.length = 0;
    const settled = ["First answer.", "Second answer.", "Third answer."];

    function Transcript({ streaming }: { streaming: string }) {
      return (
        <div>
          {settled.map((text) => (
            <AnswerText key={text} text={text} />
          ))}
          <AnswerText text={streaming} />
        </div>
      );
    }

    const view = render(<Transcript streaming="" />);
    expect(parses.filter((text) => settled.includes(text)).length).toBe(3);

    // Twenty deltas of the answer currently arriving — the panel re-renders for each.
    for (let i = 1; i <= 20; i += 1) {
      view.rerender(<Transcript streaming={"a".repeat(i)} />);
    }

    // The three settled answers were parsed ONCE each, on mount, and never again.
    // FAILS IF: `AnswerText` stops being memoised — this becomes 3 + 3 × 20 = 63.
    expect(parses.filter((text) => settled.includes(text)).length).toBe(3);
    // …while the answer that IS changing is re-parsed on every delta, as it must be.
    expect(parses.filter((text) => /^a+$/.test(text)).length).toBe(20);
  });

  it("re-parses a settled answer when its OWN text changes", () => {
    // The memo compares props, not identity: an answer whose text is edited (the streaming
    // buffer becoming a settled turn is exactly this) must still re-render.
    parses.length = 0;
    const view = render(<AnswerText text="Half an ans" />);
    view.rerender(<AnswerText text="Half an answer." />);
    expect(parses).toEqual(["Half an ans", "Half an answer."]);
  });
});
