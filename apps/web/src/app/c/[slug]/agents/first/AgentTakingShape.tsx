"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

import { StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION } from "@/components/console/section";
import { VoicePreviewButton } from "@/components/voicePreviewButton";
import type { Agent } from "@/lib/api/agents";
import { useEngineCatalogue } from "@/lib/api/engineCatalogue";
import type { FirstRunJob } from "@/lib/api/firstRun";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { CLIENT_PREVIEW_PATH } from "@/lib/api/voicePreview";
import {
  GREETING_MAX_CHARS,
  charCount,
  greetingFits,
  jobCard,
  jobOf,
  languageLabel,
  type Piece,
  type PieceId,
} from "@/lib/firstAgent";
import { useBusinessSuggestions, useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * THE AGENT TAKING SHAPE (D-854, D-855): the card that fills in as each piece lands.
 *
 * Every value on it is read from the server (the first run, the agent row, the voice list),
 * so it shows what the agent IS, never what a screen said it would be. An empty piece shows
 * the business's own example, faint and marked as one, so a real-estate account sees site
 * visits and never somebody else's trade (D-827).
 *
 * Two shapes. Beside the steps on a wide screen it is the whole card. On a phone it is one
 * line (initial, name, job) that opens into the card, so the step stays the first thing
 * under the thumb. Neither shape counts pieces: the step rail is the one counter on the
 * screen, and the card's progress is its rows ticking as they fill in.
 */
export function AgentTakingShape({
  agent,
  job,
  language,
  brief,
  pieces,
  loaded,
  compact = false,
  voiceNote = null,
}: {
  agent: Agent | null;
  job: FirstRunJob | null;
  language: string | null;
  brief: string | null;
  pieces: readonly Piece[];
  /** False until the reads the pieces come from have answered, so nothing pops on arrival. */
  loaded: boolean;
  compact?: boolean;
  /** Why the build chose this voice when it is not a woman's Studio voice (`voicePickNote`). */
  voiceNote?: string | null;
}) {
  const fresh = useFreshlyDone(pieces, loaded);
  const title = agent?.name ?? null;
  const subtitle = jobCard(job)?.title ?? (agent ? jobOf(agent) : null);

  const header = (
    <div className="flex min-w-0 items-center gap-3">
      <Monogram name={title} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-heading text-ink">{title ?? <span className="text-ink-faint">Your agent</span>}</p>
        <p className="truncate text-meta text-ink-muted">
          {subtitle ?? "Its job appears here first"}
          {language ? ` · ${languageLabel(language)}` : ""}
        </p>
      </div>
    </div>
  );

  const body = (
    <>
      <ol className="divide-y divide-line">
        <Row id="voice" title="Voice" pieces={pieces} fresh={fresh}>
          <VoiceLine agent={agent} note={voiceNote} />
        </Row>
        <Row id="greeting" title="How it greets" pieces={pieces} fresh={fresh}>
          <GreetingLine line={agent?.script_opening_line ?? null} />
        </Row>
        <Row id="about" title="What it knows about you" pieces={pieces} fresh={fresh}>
          <BriefLine brief={brief} />
        </Row>
        <Row id="notes" title="What it notes down" pieces={pieces} fresh={fresh}>
          <NotesLine agent={agent} />
        </Row>
      </ol>
      <Announcer pieces={pieces} fresh={fresh} />
    </>
  );

  if (compact) {
    return (
      <details className="group rounded-card border border-line bg-surface shadow-card">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
          <div className="min-w-0 flex-1">{header}</div>
          <ChevronDown
            aria-hidden
            className="h-4 w-4 shrink-0 text-ink-muted transition-transform duration-(--duration-fast) group-open:rotate-180 motion-reduce:transition-none"
          />
          <span className="sr-only">Show your agent so far</span>
        </summary>
        <div className="border-t border-line">{body}</div>
      </details>
    );
  }

  return (
    <section aria-labelledby="first-agent-card" className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <header className="flex items-center gap-3 border-b border-line px-5 py-4">
        <h2 id="first-agent-card" className="sr-only">
          Your agent so far
        </h2>
        <div className="min-w-0 flex-1">{header}</div>
        {agent && !agent.published ? <StatusPill>Draft</StatusPill> : null}
        {agent?.published ? <StatusPill tone="ok">Ready to try</StatusPill> : null}
      </header>
      {body}
    </section>
  );
}

/** The first letter of the agent's name in a circle, or a dotted ring before it has one. */
function Monogram({ name }: { name: string | null }) {
  const initial = name ? Array.from(name.trim())[0]?.toUpperCase() : undefined;
  return (
    <span
      aria-hidden
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[16px] font-semibold ${
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
  pieces,
  fresh,
  children,
}: {
  id: PieceId;
  title: string;
  pieces: readonly Piece[];
  fresh: ReadonlySet<PieceId>;
  children: ReactNode;
}) {
  const done = pieces.find((piece) => piece.id === id)?.done === true;
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

function VoiceLine({ agent, note }: { agent: Agent | null; note: string | null }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const catalogue = useEngineCatalogue(session);
  const voiceId = agent?.engine_voice_id ?? null;
  if (agent === null) return <p className="text-meta text-ink-faint">Chosen for its language when it is built.</p>;
  const change = (
    <Link href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=voice`)} className={TEXT_ACTION}>
      {voiceId ? "Change" : "Choose one"}
    </Link>
  );
  if (voiceId === null) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-meta text-ink-muted">No voice yet. It needs one before it can ring you.</p>
        {change}
      </div>
    );
  }
  const voice = catalogue.data?.voices.find((entry) => entry.voice_id === voiceId);
  const label = voice?.label ?? "Chosen";
  return (
    <div className="space-y-1">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 truncate text-body text-ink">
          {label}
          {voice ? <span className="text-ink-muted"> · {voice.rung === "studio" ? "Studio" : "Clear"}</span> : null}
        </p>
        <span className="flex items-center gap-3">
          {voice?.preview_available ? (
            <VoicePreviewButton session={session} path={CLIENT_PREVIEW_PATH} voiceId={voiceId} label={label} />
          ) : null}
          {change}
        </span>
      </div>
      {note ? <p className="text-meta text-ink-muted">{note}</p> : null}
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

/** How much of the brief the card shows: enough to recognise it, not to reread it. */
const BRIEF_PREVIEW_CHARS = 160;

function BriefLine({ brief }: { brief: string | null }) {
  const examples = useVerticalExamples();
  const text = (brief ?? "").trim();
  if (text === "") return <Example>{examples.scriptBrief}</Example>;
  const chars = Array.from(text);
  const shown = chars.length > BRIEF_PREVIEW_CHARS ? `${chars.slice(0, BRIEF_PREVIEW_CHARS).join("").trimEnd()}…` : text;
  return <p className="break-words text-meta text-ink">{shown}</p>;
}

function NotesLine({ agent }: { agent: Agent | null }) {
  const examples = useVerticalExamples();
  const suggestions = useBusinessSuggestions();
  if (agent && agent.extraction_fields.length > 0) {
    return (
      <ul className="flex flex-wrap gap-1.5">
        {agent.extraction_fields.map((field) => (
          <li key={field.key} className="max-w-full truncate rounded-full border border-line px-2.5 py-0.5 text-meta text-ink-muted">
            {field.label}
          </li>
        ))}
      </ul>
    );
  }
  return <Example>{suggestions.callerDetails.slice(0, 3).join(", ") || examples.extractionLabel}</Example>;
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
  return (
    <p aria-live="polite" className="sr-only">
      {piece ? `${piece.label} is done.` : ""}
    </p>
  );
}
