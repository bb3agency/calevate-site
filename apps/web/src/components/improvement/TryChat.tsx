"use client";

import { useId, useState } from "react";

import { Section } from "@/components/console/section";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { useTryChat } from "@/lib/api/teach";

type Turn = { from: "you" | "agent"; text: string; lookedUp?: boolean };

/**
 * "TRY IT": a text chat with the LIVE agent, as a caller would talk to it. Nothing it says
 * can reach a real person, and nothing here changes the agent. For the agent page:
 * `<TryChat agentId={agent.id} />`.
 */
export function TryChat({ agentId, canWrite = true }: { agentId: string; canWrite?: boolean }) {
  const session = useClientSession();
  const send = useTryChat(session, agentId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chat, setChat] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const inputId = useId();

  const submit = () => {
    const text = message.trim();
    if (!text || send.isPending) return;
    setTurns((all) => [...all, { from: "you", text }]);
    setMessage("");
    send.mutate(
      { message: text, chatSession: chat },
      {
        onSuccess: (reply) => {
          setChat(reply.session);
          setNote(reply.cost_note);
          setTurns((all) => [
            ...all,
            {
              from: "agent",
              text: reply.reply + (reply.cut_short ? " …" : ""),
              lookedUp: reply.looked_up_knowledge,
            },
          ]);
        },
      },
    );
  };

  return (
    <Section
      title="Try it"
      info={<p>Type what a caller would say. Your live agent answers, exactly as it would on a call.</p>}
      action={
        turns.length ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => {
              setTurns([]);
              setChat(null);
              send.reset();
            }}
          >
            Start over
          </button>
        ) : undefined
      }
    >
      <div className="space-y-3">
        {turns.length ? (
          <ol className="space-y-2" aria-live="polite">
            {turns.map((turn, index) => (
              <li
                key={index}
                className={`max-w-[85%] rounded-md px-3 py-2 text-sm [overflow-wrap:anywhere] ${
                  turn.from === "you" ? "ml-auto bg-black/5 text-ink dark:bg-white/10" : "text-ink"
                }`}
              >
                <span className="sr-only">{turn.from === "you" ? "You: " : "Agent: "}</span>
                {turn.text}
                {turn.lookedUp ? (
                  <span className="block text-meta text-ink-faint">Looked it up in your knowledge</span>
                ) : null}
              </li>
            ))}
            {send.isPending ? (
              <li className="text-meta text-ink-muted" role="status">
                The agent is answering…
              </li>
            ) : null}
          </ol>
        ) : null}
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
            placeholder="Do you have red chilli powder?"
            className={`${FIELD} mt-0`}
          />
          <button
            type="submit"
            className={PRIMARY_BUTTON_SM}
            disabled={!canWrite || !message.trim() || send.isPending}
          >
            Send
          </button>
        </form>
        {note ? <p className="text-meta text-ink-faint">{note}</p> : null}
      </div>
    </Section>
  );
}
