"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check } from "lucide-react";

import { StatusPill } from "@/components/console/statusPill";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import type { Agent } from "@/lib/api/agents";
import { useEngineCatalogue } from "@/lib/api/engineCatalogue";
import { useClientSession } from "@/lib/api/session";
import { CLIENT_PREVIEW_PATH } from "@/lib/api/voicePreview";
import {
  GREETING_MAX_CHARS,
  QUESTIONS_WANTED,
  charCount,
  greetingFits,
  jobOf,
  type Piece,
  type PieceId,
  type PinnedAnswer,
} from "@/lib/firstAgent";
import { useBusinessSuggestions, useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * THE AGENT TAKING SHAPE (D-854): the card beside the chat, filling in as each piece lands.
 *
 * Every value on it is read from the server (the agent row, the pinned facts, the voice
 * list), so it shows what the agent IS, never what the chat said it would be. An empty piece
 * shows the business's own example, faint and marked as one, so a real-estate account sees
 * site visits and never somebody else's trade (D-827).
 *
 * A piece that turns done while the screen is open gets a short tick pop (`piece-done` in
 * globals.css, off under reduced motion) and one polite announcement; a piece that was done
 * when the screen opened is simply there.
 */
export function AgentTakingShape({
  agent,
  answers,
  pieces,
  loaded,
  footer,
}: {
  agent: Agent | null;
  answers: readonly PinnedAnswer[];
  pieces: readonly Piece[];
  /** False until the reads the pieces come from have answered, so nothing pops on arrival. */
  loaded: boolean;
  /** The finale: the call button, under the pieces. */
  footer: ReactNode;
}) {
  const fresh = useFreshlyDone(pieces, loaded);
  const done = (id: PieceId) => pieces.find((piece) => piece.id === id)?.done === true;
  const examples = useVerticalExamples();
  const suggestions = useBusinessSuggestions();
  const exampleQuestions =
    suggestions.exampleQuestions.length > 0 ? suggestions.exampleQuestions : [examples.factQuestion];

  return (
    <section
      aria-labelledby="first-agent-card"
      className="overflow-hidden rounded-card border border-line bg-surface shadow-card"
    >
      <header className="flex items-center gap-3 border-b border-line px-5 py-4">
        <Monogram name={agent?.name ?? null} />
        <div className="min-w-0 flex-1">
          <h2 id="first-agent-card" className="truncate text-heading text-ink">
            {agent?.name ?? <span className="text-ink-faint">Your agent</span>}
          </h2>
          <p className="truncate text-meta text-ink-muted">
            {agent ? jobOf(agent) : "Its job appears here first"}
          </p>
        </div>
        {agent && !agent.published ? <StatusPill>Draft</StatusPill> : null}
        {agent?.published ? <StatusPill tone="ok">Ready to try</StatusPill> : null}
      </header>

      <ol className="divide-y divide-line">
        <Row id="voice" title="Voice" done={done("voice")} fresh={fresh}>
          <VoiceLine agent={agent} />
        </Row>
        <Row id="greeting" title="How it greets callers" done={done("greeting")} fresh={fresh}>
          <GreetingLine line={agent?.script_opening_line ?? null} />
        </Row>
        <Row id="questions" title="What callers ask most" done={done("questions")} fresh={fresh}>
          {answers.length > 0 ? (
            <ul className="space-y-2">
              {answers.slice(0, QUESTIONS_WANTED).map((answer) => (
                <li key={answer.question} className="min-w-0">
                  <p className="break-words text-meta font-medium text-ink">{answer.question}</p>
                  <p className="break-words text-meta text-ink-muted">{answer.answer}</p>
                </li>
              ))}
              {answers.length < QUESTIONS_WANTED ? (
                <li className="text-meta text-ink-faint">
                  {QUESTIONS_WANTED - answers.length} more to go
                </li>
              ) : null}
            </ul>
          ) : (
            <Example>{exampleQuestions.slice(0, 2).join(" · ")}</Example>
          )}
        </Row>
        <Row id="notes" title="What it notes down" done={done("notes")} fresh={fresh}>
          {agent && agent.extraction_fields.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5">
              {agent.extraction_fields.map((field) => (
                <li
                  key={field.key}
                  className="max-w-full truncate rounded-full border border-line px-2.5 py-0.5 text-meta text-ink-muted"
                >
                  {field.label}
                </li>
              ))}
            </ul>
          ) : (
            <Example>{suggestions.callerDetails.slice(0, 3).join(", ") || examples.extractionLabel}</Example>
          )}
        </Row>
      </ol>

      <div className="border-t border-line bg-ink/[0.02] px-5 py-4">{footer}</div>

      <Announcer pieces={pieces} fresh={fresh} />
    </section>
  );
}

/** The first letter of the agent's name in a circle, or a dotted ring before it has one. */
function Monogram({ name }: { name: string | null }) {
  const initial = name ? Array.from(name.trim())[0]?.toUpperCase() : undefined;
  return (
    <span
      aria-hidden
      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-[17px] font-semibold ${
        initial ? "bg-brand-soft text-brand-strong" : "border-[1.5px] border-dashed border-ink/20"
      }`}
    >
      {initial ?? ""}
    </span>
  );
}

function Row({
  id,
  title,
  done,
  fresh,
  children,
}: {
  id: PieceId;
  title: string;
  done: boolean;
  fresh: ReadonlySet<PieceId>;
  children: ReactNode;
}) {
  return (
    <li className="flex gap-3 px-5 py-4">
      <Tick done={done} pop={fresh.has(id)} />
      <div className="min-w-0 flex-1">
        <h3 className="text-meta font-medium text-ink-muted">
          <span className="sr-only">{done ? "Done: " : "To do: "}</span>
          {title}
        </h3>
        <div className="mt-1">{children}</div>
      </div>
    </li>
  );
}

function Tick({ done, pop }: { done: boolean; pop: boolean }) {
  return (
    <span
      aria-hidden
      className={`relative mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
        done ? `bg-brand-strong text-white ${pop ? "piece-done" : ""}` : "border-[1.5px] border-ink/25"
      }`}
    >
      {done ? <Check className="relative h-3 w-3" strokeWidth={3} /> : null}
    </span>
  );
}

/** What an empty piece will look like, in this business's words, marked as an example. */
function Example({ children }: { children: ReactNode }) {
  return (
    <p className="break-words text-meta text-ink-faint">
      <span className="font-medium">For example: </span>
      {children}
    </p>
  );
}

function VoiceLine({ agent }: { agent: Agent | null }) {
  const session = useClientSession();
  const catalogue = useEngineCatalogue(session);
  const voiceId = agent?.engine_voice_id ?? null;
  if (voiceId === null) {
    return <p className="text-meta text-ink-faint">Pick one you like the sound of.</p>;
  }
  const voice = catalogue.data?.voices.find((entry) => entry.voice_id === voiceId);
  const label = voice?.label ?? "Chosen";
  return (
    <div className="flex min-w-0 items-center justify-between gap-3">
      <p className="min-w-0 truncate text-body text-ink">{label}</p>
      {voice?.preview_available ? (
        <VoicePreviewButton session={session} path={CLIENT_PREVIEW_PATH} voiceId={voiceId} label={label} />
      ) : null}
    </div>
  );
}

function GreetingLine({ line }: { line: string | null }) {
  const text = (line ?? "").trim();
  if (text === "") return <p className="text-meta text-ink-faint">It says this first, on every call.</p>;
  const count = charCount(text);
  const over = count > GREETING_MAX_CHARS;
  return (
    <div className="space-y-1">
      <blockquote className="break-words border-l-2 border-line pl-3 text-body text-ink">{text}</blockquote>
      <p className={`text-meta tabular-nums ${over ? "text-warn" : "text-ink-faint"}`}>
        {count} of {GREETING_MAX_CHARS} characters
        {over ? " · shorter is easier to listen to" : greetingFits(text) ? "" : " · end it with a question"}
      </p>
    </div>
  );
}

/**
 * The pieces that turned done since the reads first answered. The first answer is the
 * baseline, so a resumed screen does not celebrate pieces finished last week.
 */
function useFreshlyDone(pieces: readonly Piece[], loaded: boolean): ReadonlySet<PieceId> {
  const seen = useRef<ReadonlySet<PieceId> | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<PieceId>>(() => new Set());
  const doneKey = pieces
    .filter((piece) => piece.done)
    .map((piece) => piece.id)
    .join(",");
  useEffect(() => {
    if (!loaded) return;
    const now = new Set(doneKey.split(",").filter(Boolean) as PieceId[]);
    const before = seen.current;
    seen.current = now;
    if (before === null) return;
    const added = [...now].filter((id) => !before.has(id));
    if (added.length > 0) setFresh((previous) => new Set([...previous, ...added]));
  }, [doneKey, loaded]);
  return fresh;
}

/** One polite sentence per piece that lands, so a screen reader hears the progress too. */
function Announcer({ pieces, fresh }: { pieces: readonly Piece[]; fresh: ReadonlySet<PieceId> }) {
  const last = [...fresh].at(-1);
  const piece = pieces.find((entry) => entry.id === last);
  const done = pieces.filter((entry) => entry.done).length;
  return (
    <p aria-live="polite" className="sr-only">
      {piece ? `${piece.label} is done. ${done} of ${pieces.length}.` : ""}
    </p>
  );
}
