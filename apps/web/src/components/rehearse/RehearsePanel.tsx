"use client";

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { FIELD, NoticeBox, ProblemNotice } from "@/components/ui";
import { useRehearse } from "@/lib/api/rehearse";
import type { ScriptHolder } from "@/lib/api/scriptChecks";
import type { Session } from "@/lib/api/client";

import { fixInstruction, type RehearsalTurn } from "./rehearseModel";

export type Rehearsal = { turns: RehearsalTurn[]; chat: string | null; note: string | null; runs: "saved" | "live" | null };

export const EMPTY_REHEARSAL: Rehearsal = { turns: [], chat: null, note: null, runs: null };

/**
 * REHEARSE (W3.2): type what a caller would say and read how the holder's SAVED script
 * answers, with every tool the agent reached for said in plain words and marked "not run",
 * and each reply's checks as a quiet flag the owner can send to Pip as a fix. Nothing it
 * does reaches a person.
 *
 * The conversation lives in the parent (`rehearsal`), so closing the panel and opening it
 * again keeps it; Start over clears it and the next line starts a fresh chat on the server.
 */
export function RehearsePanel({
  session,
  holder,
  rehearsal,
  onChange,
  canWrite,
  refusal,
  onFix,
}: {
  session: Session;
  holder: ScriptHolder;
  rehearsal: Rehearsal;
  onChange: (next: Rehearsal | ((was: Rehearsal) => Rehearsal)) => void;
  canWrite: boolean;
  refusal?: string;
  /** Sends a request to the holder's Pip; absent where Pip cannot be asked now. */
  onFix?: (instruction: string) => void;
}) {
  const send = useRehearse(session, holder);
  // A refused line is said under the conversation, so it is not toasted.
  const sendFeedback = useActionFeedback(send, { errorDisplay: "inline" });
  const [message, setMessage] = useState("");
  const inputId = useId();
  const { turns } = rehearsal;

  const submit = () => {
    const text = message.trim();
    if (!text || sendFeedback.status === "pending") return;
    onChange((was) => ({ ...was, turns: [...was.turns, { from: "you", text }] }));
    send.mutate(
      { message: text, chatSession: rehearsal.chat },
      {
        onSuccess: (reply) => {
          setMessage((current) => (current.trim() === text ? "" : current));
          onChange((was) => ({
            chat: reply.session,
            note: reply.cost_note,
            runs: reply.runs,
            turns: [
              ...was.turns,
              {
                from: "agent",
                text: reply.reply + (reply.cut_short ? " …" : ""),
                actions: reply.actions,
                flags: reply.flags,
                said: text,
              },
            ],
          }));
        },
        // The line never reached the agent, so it leaves the conversation; it stays in the box.
        onError: () => onChange((was) => ({ ...was, turns: was.turns.slice(0, -1) })),
      },
    );
  };

  return (
    <div className="space-y-4">
      <p className="text-meta text-ink-muted">
        {rehearsal.runs === "live"
          ? "It answers with the script callers hear now."
          : "It answers with your saved script. Save a change first to try it here."}
      </p>
      {turns.length ? (
        <ol className="space-y-3" aria-live="polite">
          {turns.map((turn, index) => (
            <li
              key={index}
              className={
                turn.from === "you"
                  ? "ml-auto max-w-[85%] rounded-md bg-surface-muted px-3 py-2 text-sm text-ink [overflow-wrap:anywhere]"
                  : "max-w-[92%] space-y-1.5 text-sm text-ink [overflow-wrap:anywhere]"
              }
            >
              <span className="sr-only">{turn.from === "you" ? "You: " : "Agent: "}</span>
              <p>{turn.text}</p>
              {turn.from === "agent" && turn.actions.length > 0 && (
                <ul className="space-y-0.5" aria-label="What it did">
                  {turn.actions.map((action, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-meta text-ink-muted">
                      <span>{action.said}</span>
                      {!action.ran && (
                        <span className="rounded-sm border border-line px-1 text-[0.6875rem] uppercase tracking-wide text-ink-faint">
                          not run
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {turn.from === "agent" &&
                turn.flags.map((flag) => (
                  <NoticeBox
                    key={flag.kind}
                    tone="warn"
                    action={
                      flag.in_script && onFix ? (
                        <button
                          type="button"
                          className={TEXT_ACTION_SM}
                          disabled={!canWrite}
                          title={refusal}
                          onClick={() => onFix(fixInstruction(flag, turn.said, turn.text))}
                        >
                          Fix this in the script
                        </button>
                      ) : undefined
                    }
                  >
                    {flag.reason}
                  </NoticeBox>
                ))}
            </li>
          ))}
          {sendFeedback.status === "pending" ? (
            <li className="text-meta text-ink-muted" role="status">
              The agent is answering…
            </li>
          ) : null}
        </ol>
      ) : (
        <p className="text-body text-ink-muted">Type what a caller would say. No one is called.</p>
      )}
      {send.error ? <ProblemNotice error={send.error} /> : null}
      <form
        className="flex gap-2"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          What the caller says
        </label>
        <input
          id={inputId}
          value={message}
          maxLength={1000}
          onChange={(event) => setMessage(event.target.value)}
          disabled={!canWrite}
          title={refusal}
          placeholder="Hello, who is this?"
          className={`${FIELD} mt-0`}
        />
        <ActionButton
          type="submit"
          variant="secondary-sm"
          status={sendFeedback.status}
          successLabel="Sent"
          disabled={!canWrite || !message.trim()}
        >
          Send
        </ActionButton>
      </form>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {rehearsal.note ? <p className="text-meta text-ink-faint">{rehearsal.note}</p> : <span />}
        {turns.length > 0 && (
          <ActionButton
            variant="text"
            // Held, not pending: Send is the button that is working and carries the spinner.
            // The reply still on its way would land in the cleared chat, under the old session.
            disabled={sendFeedback.status === "pending"}
            onClick={() => {
              onChange(EMPTY_REHEARSAL);
              send.reset();
            }}
          >
            Start over
          </ActionButton>
        )}
      </div>
    </div>
  );
}
