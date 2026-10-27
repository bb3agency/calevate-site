"use client";

/**
 * One practice test's conversation, try by try: a row of try buttons (each saying whether
 * that try was right) over the chat it was. The failing try opens first, because that is the
 * one the owner came to read.
 *
 * Test turns carry the words as said and no English rendering: the test-chat read model
 * (`TestTurnOut`: said, reply, actions) has none, unlike a call, whose English comes from
 * the call-translation worker. So each bubble names its language and nothing more.
 */

import { useState } from "react";

import type { TestTry, TestTurn } from "@/lib/api/script";
import { lookup } from "@/lib/lookup";

import { ACTION_LABEL, languageOf } from "./testCopy";

const TRY_WORD: Record<TestTry["verdict"], { said: string; dot: string }> = {
  passed: { said: "right", dot: "bg-brand-strong" },
  needs_fix: { said: "not right", dot: "bg-danger" },
  failed: { said: "not right", dot: "bg-danger" },
  unjudged: { said: "not judged", dot: "bg-ink-faint" },
};

export function TriesAndConversation({ tries }: { tries: TestTry[] }) {
  const firstFailing = Math.max(
    0,
    tries.findIndex((t) => t.verdict === "failed" || t.verdict === "needs_fix"),
  );
  const [shown, setShown] = useState(firstFailing);
  const current = tries[Math.min(shown, tries.length - 1)];
  if (!current) return null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <p className="text-meta font-medium text-ink-muted">The conversation</p>
        {/* The tries as one segmented strip (the console's segmented look), each with a
            dot for its verdict, said in words to a screen reader. */}
        {tries.length > 1 && (
          <div
            role="group"
            aria-label="Tries"
            className="inline-flex rounded-[10px] bg-ink/[0.05] p-[3px] shadow-[inset_0_0_0_1px_var(--line)]"
          >
            {tries.map((t, index) => {
              const word = lookup(TRY_WORD, t.verdict) ?? TRY_WORD.unjudged;
              const selected = index === shown;
              return (
                <button
                  key={index}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setShown(index)}
                  className={`press inline-flex min-h-8 touch:min-h-11 items-center gap-1.5 rounded-[7px] px-3 text-meta focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                    selected ? "bg-surface font-medium text-ink shadow-card ring-1 ring-ink/[0.06]" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  <span aria-hidden className={`size-1.5 rounded-full ${word.dot}`} />
                  <span>
                    Try {index + 1}
                    <span className="sr-only">, {word.said}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
      {/* The first failing try's reason already heads the test; another try says its own. */}
      {shown !== firstFailing && current.reason && (
        <p className="text-meta text-ink-muted">
          Try {Math.min(shown, tries.length - 1) + 1}: {current.reason}
        </p>
      )}
      <Conversation turns={current.turns} />
    </div>
  );
}

/** One try as the chat it was: the caller on the right, the agent on the left. */
function Conversation({ turns }: { turns: TestTurn[] }) {
  if (turns.length === 0) return <p className="text-meta text-ink-muted">Nothing was said on this try.</p>;
  return (
    <ol className="space-y-2 rounded-card bg-ink/[0.025] p-3" aria-label="The conversation">
      {turns.map((turn, index) => (
        <li key={index} className="space-y-2">
          <Bubble who="Caller" text={turn.said} side="right" />
          <Bubble who="Your agent" text={turn.reply} side="left" actions={turn.actions ?? []} />
        </li>
      ))}
    </ol>
  );
}

function Bubble({
  who,
  text,
  side,
  actions = [],
}: {
  who: "Caller" | "Your agent";
  text: string;
  side: "left" | "right";
  actions?: NonNullable<TestTurn["actions"]>;
}) {
  const language = text ? languageOf(text) : null;
  const right = side === "right";
  return (
    <div className={`flex ${right ? "justify-end" : "justify-start"}`}>
      <div className={`flex min-w-0 max-w-[88%] flex-col gap-1 sm:max-w-[75%] ${right ? "items-end" : "items-start"}`}>
        <p className="px-1 text-meta text-ink-muted">
          <span className="font-medium">{who}</span>
          {language && <span>, {language}</span>}
        </p>
        <p
          className={`whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-body text-ink ${
            right ? "rounded-br-md bg-ink/[0.06]" : "rounded-bl-md border border-line bg-surface"
          }`}
        >
          {text || <span className="text-ink-muted">(said nothing)</span>}
        </p>
        {actions.length > 0 && (
          <p className="px-1 text-meta text-ink-muted">
            {actions.map((a) => lookup(ACTION_LABEL, a) ?? ACTION_LABEL.other).join(", ")}
          </p>
        )}
      </div>
    </div>
  );
}
