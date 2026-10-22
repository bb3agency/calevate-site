"use client";

import { useId, useState } from "react";

import { Section } from "@/components/console/section";
import { FIELD, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useTestConversations } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";
import { useTryChat } from "@/lib/api/teach";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

type Turn = { from: "you" | "agent"; text: string; lookedUp?: boolean };

/**
 * "TRY IT": a text chat with the LIVE agent, as a caller would talk to it. Nothing it says
 * can reach a real person, and nothing here changes the agent. The engine's test chat runs the
 * agent as published and has no draft of its own, and a chat reply runs at the model's default
 * thinking level rather than the call's minimal one (ThinnestAI, email of 19 Oct 2026,
 * VENDOR-STATED; snapshots/2026-10-19/pages/api-reference/agents/test-chat.md:7), so the info
 * line promises the live script and knowledge, not a reply identical to a call's. For the agent page:
 * `<TryChat agentId={agent.id} />`.
 */
export function TryChat({
  agentId,
  canWrite = true,
  headingLevel = 2,
}: {
  agentId: string;
  canWrite?: boolean;
  headingLevel?: 2 | 3;
}) {
  const session = useClientSession();
  const eg = useVerticalExamples();
  const send = useTryChat(session, agentId);
  /* The same readiness the saved tests read: the chat talks to the agent the engine holds,
     so until it has been published there is nothing to talk to, and the server says why. */
  const readiness = useTestConversations(session, agentId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chat, setChat] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const inputId = useId();

  const submit = () => {
    const text = message.trim();
    if (!text || send.isPending) return;
    setTurns((all) => [...all, { from: "you", text }]);
    send.mutate(
      { message: text, chatSession: chat },
      {
        onSuccess: (reply) => {
          // Cleared only once the agent answered: a refused send keeps what was typed.
          setMessage((current) => (current.trim() === text ? "" : current));
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
        // The line never reached the agent, so it leaves the conversation; it stays in the box.
        onError: () => setTurns((all) => all.slice(0, -1)),
      },
    );
  };

  if (readiness.isPending) {
    return (
      <Section headingLevel={headingLevel} title="Try it in a chat">
        <Skeleton rows={2} label="Checking whether this agent can chat yet" />
      </Section>
    );
  }
  if (readiness.isError) {
    return (
      <Section headingLevel={headingLevel} title="Try it in a chat">
        <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} />
      </Section>
    );
  }
  if (!readiness.data.available) {
    return (
      <Section headingLevel={headingLevel} title="Try it in a chat">
        <p className="text-body text-ink-muted">{readiness.data.unavailable_reason}</p>
      </Section>
    );
  }

  return (
    <Section
      headingLevel={headingLevel}
      title="Try it in a chat"
      info={
        <p>
          Type what a caller would say. The agent answers from the script and knowledge it has been put live with. A
          change you have not put live is not in this chat yet.
        </p>
      }
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
            placeholder={eg.factQuestion}
            className={`${FIELD} mt-0`}
          />
          <button
            type="submit"
            className={SECONDARY_BUTTON_SM}
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
