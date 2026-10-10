"use client";

import { Eye } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Section } from "@/components/console/section";
import { NoticeBox, ProblemNotice, RestrictionNote, ToggleSwitch } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";
import { activeTurnIdx, groupTurns, langAttr } from "@/lib/callReview";
import { lookup } from "@/lib/lookup";

import { SPEAKERS } from "./speakers";
import { RawTranscriptControl, type RawTranscriptAccess } from "./transcriptAccess";

type Turn = NonNullable<CallDetail["transcript"]>[number];

/**
 * THE CONVERSATION — the recording, and the transcript read as a script under it.
 *
 * The recording sits directly above the turns and stays on screen while they scroll, so
 * pressing a line and hearing it are one gesture. The turns are rows with a time gutter;
 * the speaker's word is printed only when the speaker changes, so a run of lines by one
 * person reads as one block (founder, REDESIGN-2: a plain script, no bubbles, no icons).
 * Indic text is set at 16px with open leading and carries its `lang`, which is also what
 * picks the Telugu or Devanagari face (`globals.css`). "Show English" puts the English of
 * each turn under it; the original stays the record (founder decision 5).
 *
 * Hard rule 5 lives here too: which transcript you are reading is said above the turns
 * in both states, and a raw read that FAILS leaves the redacted turns where they were.
 */
export function TranscriptCard({
  detail,
  turns,
  showingRaw,
  showRaw,
  rawError,
  rawPending,
  onRetryRaw,
  rawAccess,
  onToggleRaw,
  player,
  noRecording,
  audioLoaded,
  playhead,
  onSeek,
  className = "",
}: {
  detail: Pick<CallDetail, "status" | "summary_state" | "translation_state">;
  turns: Turn[];
  showingRaw: boolean;
  showRaw: boolean;
  rawError: unknown;
  rawPending: boolean;
  onRetryRaw: () => void;
  rawAccess: RawTranscriptAccess;
  onToggleRaw: () => void;
  /** The recording, or the line saying there is none. Kept in view while reading. */
  player: ReactNode;
  /** A finished call with no audio says so where the player would be. */
  noRecording: boolean;
  audioLoaded: boolean;
  playhead: number | null;
  onSeek: (ms: number) => void;
  className?: string;
}) {
  const [english, setEnglish] = useState(false);
  const hasEnglish = turns.some((turn) => Boolean(turn.text_en));
  const active = activeTurnIdx(turns, playhead === null ? null : playhead * 1000);
  const listRef = useFollowAlong(active);

  return (
    <Section
      className={className}
      title="Conversation"
      action={
        <RawTranscriptControl access={rawAccess} showRaw={showRaw} pending={rawPending} onToggle={onToggleRaw} />
      }
    >
      <div className="space-y-4">
        {player ? (
          <div className="sticky top-0 z-10 -mx-1 border-b border-line bg-surface px-1 pb-3 pt-1">{player}</div>
        ) : noRecording ? (
          <p className="text-meta text-ink-faint">There is no recording of this call.</p>
        ) : null}

        {/* WHY THE CONTROL ABOVE IS DEAD, on the screen and not only in a tooltip.
            `RestrictionNote` renders nothing while `/v1/me` is in flight, so the sentence
            never flashes and is never retracted. */}
        {!rawAccess.allowed && <RestrictionNote reason={rawAccess.reason} />}

        {/* Which transcript this is, said before it is read. Quiet in the default view,
            loud in the raw one, which is the view that is audited. */}
        {showingRaw ? (
          <NoticeBox tone="warn" icon={<Eye className="h-5 w-5" />} title="Full transcript">
            You are reading the full text, personal details included. This view was recorded
            in your account&apos;s audit log against your name.
          </NoticeBox>
        ) : (
          <p className="text-meta text-ink-faint">
            Personal details — phone numbers, account numbers, dates of birth — are hidden in
            this view.
          </p>
        )}

        {showRaw && rawError != null && <ProblemNotice error={rawError} onRetry={onRetryRaw} />}

        {turns.length > 0 && (
          <EnglishSwitch
            state={detail.translation_state}
            available={hasEnglish}
            on={english}
            onToggle={() => setEnglish((v) => !v)}
          />
        )}

        {turns.length ? (
          <ol ref={listRef} className="space-y-4">
            {groupTurns(turns).map((group) => {
              const speaker = lookup(SPEAKERS, group.speaker);
              const agent = group.speaker === "agent";
              const name = speaker?.label ?? group.speaker;
              return (
                <li key={group.turns[0].idx}>
                  <p className={`mb-0.5 pl-14 text-meta font-medium ${agent ? "text-brand-strong" : "text-ink-muted"}`}>
                    {name}
                  </p>
                  <div className="space-y-0.5">
                    {group.turns.map((turn) => (
                      <TurnRow
                        key={turn.idx}
                        turn={turn}
                        english={english}
                        seekable={audioLoaded && turn.start_ms != null}
                        active={active === turn.idx}
                        onSeek={onSeek}
                      />
                    ))}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <EmptyState {...emptyTranscript(detail)} />
        )}
      </div>
    </Section>
  );
}

function emptyTranscript(detail: Pick<CallDetail, "status" | "summary_state">): { message: string; hint?: string } {
  if (detail.status === "in_progress") return { message: "The call is still going", hint: "Its transcript appears here when it ends." };
  if (detail.status !== "completed") return { message: "Nobody spoke on this call" };
  if (detail.summary_state === "empty") return { message: "Nothing was said on this call" };
  return { message: "No transcript yet", hint: "Transcripts arrive a couple of minutes after the call ends." };
}

/**
 * One turn: the time in the gutter, the words, and their English under them when asked.
 * A turn is a button only when it can do something — the audio is loaded AND the turn
 * carries a time; otherwise it is text, never a control that silently does nothing.
 */
function TurnRow({
  turn,
  english,
  seekable,
  active,
  onSeek,
}: {
  turn: Turn;
  english: boolean;
  seekable: boolean;
  active: boolean;
  onSeek: (ms: number) => void;
}) {
  const at = turn.start_ms;
  const clock = at == null ? "" : formatClock(at / 1000);
  const body = (
    <>
      <span className="pt-0.5 text-meta tabular-nums text-ink-faint">
        {/* The button's name starts with where it goes; the gutter shows the same time. */}
        {seekable ? (
          <>
            <span className="sr-only">{`Play from ${clock},`}</span>
            <span aria-hidden>{clock}</span>
          </>
        ) : (
          clock
        )}
      </span>
      <span className="min-w-0">
        <span lang={langAttr(turn.lang)} className="block break-words text-transcript text-ink">
          {turn.text}
        </span>
        {english && turn.text_en && (
          <span lang="en" className="mt-0.5 block text-body text-ink-muted">
            {turn.text_en}
          </span>
        )}
      </span>
    </>
  );
  const shape = `grid w-full scroll-mt-48 grid-cols-[3rem_minmax(0,1fr)] gap-x-2 rounded-md px-2 py-1 text-left transition-colors duration-(--duration-fast) ease-out motion-reduce:transition-none ${
    active ? "bg-brand-soft/60" : ""
  }`;
  if (seekable && at != null) {
    return (
      <button
        type="button"
        data-turn={turn.idx}
        onClick={() => onSeek(at)}
        aria-current={active ? "true" : undefined}
        className={`${shape} hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand`}
      >
        {body}
      </button>
    );
  }
  return (
    <div data-turn={turn.idx} className={shape}>
      {body}
    </div>
  );
}

/**
 * "Show English" — one switch for the whole transcript, with the translation's state said
 * in words while it is not there yet.
 */
function EnglishSwitch({
  state,
  available,
  on,
  onToggle,
}: {
  state: CallDetail["translation_state"];
  available: boolean;
  on: boolean;
  onToggle: () => void;
}) {
  if (available) return <ToggleSwitch label="Show English" checked={on} onChange={onToggle} />;
  if (state === "pending") return <p className="text-meta text-ink-faint">The English of each line is still being written.</p>;
  if (state === "failed") return <p className="text-meta text-ink-faint">The English of each line could not be written for this call.</p>;
  return null;
}

/**
 * Keeps the line being played in view while the reader is following it. It only moves
 * the page when the previous line was on screen — a reader who has scrolled away to look
 * at something else is left where they are — and it jumps rather than glides when the
 * reader has asked for reduced motion.
 */
function useFollowAlong(active: number | null) {
  const listRef = useRef<HTMLOListElement>(null);
  const previous = useRef<number | null>(null);
  useEffect(() => {
    const list = listRef.current;
    const before = previous.current;
    previous.current = active;
    if (!list || active === null || active === before) return;
    const find = (idx: number) => list.querySelector<HTMLElement>(`[data-turn="${idx}"]`);
    const next = find(active);
    if (!next || typeof next.scrollIntoView !== "function") return;
    const inView = (el: HTMLElement) => {
      const box = el.getBoundingClientRect();
      return box.bottom > 0 && box.top < window.innerHeight;
    };
    const prior = before === null ? null : find(before);
    if (prior && !inView(prior)) return;
    if (inView(next)) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    next.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }, [active]);
  return listRef;
}
