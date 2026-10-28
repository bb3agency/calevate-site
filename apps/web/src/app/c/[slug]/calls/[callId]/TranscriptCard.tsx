"use client";

import { Languages } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { NoticeBox, ProblemNotice, RestrictionNote, SECONDARY_BUTTON } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import { spokenClock } from "@/lib/callMoments";
import { activeTurnIdx, groupTurns, isEnglishCall, langAttr, languageName } from "@/lib/callReview";
import { lookup } from "@/lib/lookup";

import type { CallView } from "./callEnglish";
import { SPEAKERS } from "./speakers";
import { RawTranscriptControl, type RawTranscriptAccess } from "./transcriptAccess";

type Turn = NonNullable<CallDetail["transcript"]>[number];

/**
 * THE CONVERSATION — the recording, and the call read back as a chat under it.
 *
 * The agent speaks from the left beside its initial, the caller from the right, each line
 * in a quiet bubble with its time under the words (founder, 11 Oct 2026; REDESIGN-2's
 * "plain script, no bubbles" is superseded for this panel). The recording above stays on
 * screen while the lines scroll: pressing a line plays from it, the line being played is
 * outlined, and the list follows the audio while the reader is following it.
 *
 * ONE language switch serves the whole page: it sits here, above the lines, and the
 * summary at the top of the page follows it. It is always shown for a call that was not in
 * English, whatever state its English is in, and each state is said in words: being
 * prepared, could not be prepared (with "Try again"), or from before English was added.
 *
 * Hard rule 5 lives here too: which transcript you are reading is said above the lines in
 * both states, and a raw read that FAILS leaves the redacted lines where they were.
 */
export function TranscriptCard({
  detail,
  turns,
  view,
  onViewChange,
  english,
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
  marker,
  className = "",
}: {
  detail: Pick<CallDetail, "status" | "summary_state" | "translation_state" | "language" | "agent_name" | "lead_name">;
  turns: Turn[];
  view: CallView;
  onViewChange: (view: CallView) => void;
  /** Asking for the English again, and who may. */
  english: EnglishRetry;
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
  /** Drawn under a line: the key moments that belong to it. */
  marker?: (turn: Turn) => ReactNode;
  className?: string;
}) {
  const active = activeTurnIdx(turns, playhead === null ? null : playhead * 1000);
  const listRef = useFollowAlong(active);
  const englishCall = isEnglishCall(detail.language);
  const showEnglish = view === "english" && !englishCall;
  const missing = showEnglish ? englishMissing(detail.translation_state, turns) : null;

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
          // Flush under the shell header: the negative offset cancels <main>'s top padding
          // (`SHELL_MAIN_CLASS`), so no strip of transcript scrolls above the player.
          <div className="sticky -top-4 z-sticky -mx-1 border-b border-line bg-surface px-1 pb-3 pt-3 lg:-top-8">{player}</div>
        ) : noRecording ? (
          <p className="text-meta text-ink-faint">There is no recording of this call.</p>
        ) : null}

        {/* WHY THE CONTROL ABOVE IS DEAD, on the screen and not only in a tooltip.
            `RestrictionNote` renders nothing while `/v1/me` is in flight, so the sentence
            never flashes and is never retracted. */}
        {!rawAccess.allowed && <RestrictionNote reason={rawAccess.reason} />}

        {/* Which transcript this is, said before it is read. Quiet in the default view,
            louder in the raw one, which carries personal details. */}
        {showingRaw ? (
          <NoticeBox tone="warn" title="Full transcript">
            Personal details included.
          </NoticeBox>
        ) : (
          <p className="text-meta text-ink-faint">
            Personal details are hidden here.
          </p>
        )}

        {showRaw && rawError != null && <ProblemNotice error={rawError} onRetry={onRetryRaw} />}

        {turns.length > 0 && (
          <LanguageSwitch language={detail.language} englishCall={englishCall} view={view} onChange={onViewChange} />
        )}

        {turns.length === 0 ? (
          <EmptyState {...emptyTranscript(detail)} />
        ) : missing === "pending" ? (
          <EnglishPreparing />
        ) : missing ? (
          <EnglishUnavailable state={missing} language={detail.language} retry={english} />
        ) : (
          <ol ref={listRef} className="space-y-5" aria-label="The conversation, line by line">
            {groupTurns(turns).map((group) => {
              const agent = group.speaker === "agent";
              return (
                <li key={group.turns[0].idx} className={agent ? "flex items-start gap-2.5" : "flex justify-end"}>
                  {agent && <AgentMark name={detail.agent_name} />}
                  <div className={`flex min-w-0 max-w-[85%] flex-col gap-1.5 sm:max-w-[75%] ${agent ? "items-start" : "items-end"}`}>
                    <p className="px-1 text-meta font-medium text-ink-muted">{speakerName(group.speaker, detail)}</p>
                    {group.turns.map((turn, i) => (
                      <Bubble
                        key={turn.idx}
                        turn={turn}
                        agent={agent}
                        first={i === 0}
                        english={showEnglish}
                        seekable={audioLoaded && turn.start_ms != null}
                        active={active === turn.idx}
                        onSeek={onSeek}
                        marker={marker?.(turn)}
                      />
                    ))}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </Section>
  );
}

/** "Try again" for the English: the request, and whether this person may make it. */
export interface EnglishRetry {
  access: WriteAccess;
  onRetry: () => void;
  pending: boolean;
  error: unknown;
}

function emptyTranscript(detail: Pick<CallDetail, "status" | "summary_state">): { message: string; hint?: string } {
  if (detail.status === "in_progress") return { message: "The call is still going", hint: "It shows here when the call ends." };
  if (detail.status !== "completed") return { message: "Nobody spoke on this call" };
  if (detail.summary_state === "empty") return { message: "Nothing was said on this call" };
  return { message: "No transcript yet", hint: "It arrives a few minutes after the call." };
}

function speakerName(speaker: string, detail: Pick<CallDetail, "agent_name" | "lead_name">): string {
  if (speaker === "agent") return detail.agent_name?.trim() || "Agent";
  if (speaker === "caller") return detail.lead_name?.trim() || "Caller";
  // A speaker this build has never heard of keeps its own name rather than vanishing.
  return lookup(SPEAKERS, speaker)?.label ?? speaker;
}

/**
 * Why the English view cannot show English yet, or null when it can. A call whose lines
 * already carry English shows them whatever the state says; a line with no English of its
 * own (one spoken in English) shows as it was said.
 */
function englishMissing(
  state: CallDetail["translation_state"],
  turns: readonly Turn[],
): "pending" | "failed" | "unavailable" | null {
  if (turns.some((turn) => Boolean(turn.text_en))) return null;
  if (state === "pending" || state === "failed" || state === "unavailable") return state;
  return null;
}

/** The one language control on the page. An English call needs none, and says so. */
function LanguageSwitch({
  language,
  englishCall,
  view,
  onChange,
}: {
  language: string;
  englishCall: boolean;
  view: CallView;
  onChange: (view: CallView) => void;
}) {
  if (englishCall) {
    return <p className="text-meta text-ink-faint">This call was in English.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <SegmentedControl
        label="Language of the conversation"
        value={view}
        onValueChange={(next) => onChange(next === "english" ? "english" : "original")}
        options={[
          { value: "original", label: languageName(language) ?? "As spoken" },
          { value: "english", label: "English" },
        ]}
      />
    </div>
  );
}

/** The English is on its way: said, and drawn as the shape it will take. */
function EnglishPreparing() {
  const bar = "animate-pulse rounded-2xl bg-ink/[0.06] motion-reduce:animate-none";
  return (
    <div role="status" aria-live="polite" className="space-y-4">
      <p className="text-body text-ink-muted">English is being prepared. Usually under a minute.</p>
      <div aria-hidden className="space-y-3">
        <div className="flex items-start gap-2.5">
          <div className="h-7 w-7 shrink-0 rounded-full bg-ink/[0.06]" />
          <div className={`${bar} h-12 w-3/5`} />
        </div>
        <div className="flex justify-end">
          <div className={`${bar} h-10 w-1/2`} />
        </div>
        <div className="flex items-start gap-2.5">
          <div className="h-7 w-7 shrink-0 rounded-full bg-ink/[0.06]" />
          <div className={`${bar} h-16 w-2/3`} />
        </div>
      </div>
    </div>
  );
}

/** No English, and why, with the one action that fixes it. */
function EnglishUnavailable({
  state,
  language,
  retry,
}: {
  state: "failed" | "unavailable";
  language: string;
  retry: EnglishRetry;
}) {
  const spoken = languageName(language) ?? "the language it was spoken in";
  return (
    <div className="space-y-3 rounded-md border border-line px-4 py-4">
      <p className="text-body text-ink">
        {state === "failed"
          ? "Couldn't prepare the English."
          : "This call is older than English reviews."}
      </p>
      <p className="text-meta text-ink-muted">
        Complete in {spoken}. English uses a little AI help.
      </p>
      {retry.error != null && <ProblemNotice error={retry.error} />}
      <RestrictionNote reason={retry.access.allowed ? null : retry.access.reason} />
      <button
        type="button"
        className={SECONDARY_BUTTON}
        disabled={!retry.access.allowed || retry.pending}
        onClick={retry.onRetry}
      >
        <Languages aria-hidden className="h-4 w-4" />
        {retry.pending ? "Asking…" : state === "failed" ? "Try again" : "Prepare the English"}
      </button>
    </div>
  );
}

/** The agent's initial in a small circle, once per run of its lines. */
function AgentMark({ name }: { name: string | null | undefined }) {
  const initial = (name?.trim() || "A").charAt(0).toUpperCase();
  return (
    <span
      aria-hidden
      className="mt-6 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[13px] font-semibold text-brand-strong dark:bg-brand/20 dark:text-brand-bright"
    >
      {initial}
    </span>
  );
}

/** `~0:21` when the platform's time for the line is approximate, `0:21` when exact. */
function lineClock(turn: Turn): string {
  if (turn.start_ms == null) return "";
  return `${turn.start_approximate ? "~" : ""}${formatClock(turn.start_ms / 1000)}`;
}

/**
 * One line. A bubble is a button only when it can do something — the audio is loaded AND
 * the line carries a time; otherwise it is text, never a control that silently does nothing.
 */
function Bubble({
  turn,
  agent,
  first,
  english,
  seekable,
  active,
  onSeek,
  marker,
}: {
  turn: Turn;
  agent: boolean;
  first: boolean;
  english: boolean;
  seekable: boolean;
  active: boolean;
  onSeek: (ms: number) => void;
  marker?: ReactNode;
}) {
  const clock = lineClock(turn);
  const wordsId = useId();
  const translated = english && Boolean(turn.text_en);
  const words = translated ? turn.text_en : turn.text;
  const lang = translated ? "en" : langAttr(turn.lang);
  const shape = [
    "block w-fit max-w-full rounded-2xl px-3.5 py-2 text-left",
    "transition-[background-color,box-shadow] duration-(--duration-fast) ease-out motion-reduce:transition-none",
    agent ? "bg-ink/[0.045] dark:bg-white/[0.07]" : "bg-brand-soft dark:bg-brand/20",
    first ? (agent ? "rounded-tl-md" : "rounded-tr-md") : "",
    active ? "ring-2 ring-brand" : "",
  ].join(" ");
  const body = (
    <>
      <span id={wordsId} lang={lang} className="block whitespace-pre-wrap break-words text-transcript text-ink">
        {words}
      </span>
      {clock && (
        <span className={`mt-0.5 block text-[12px] leading-4 tabular-nums text-ink-faint ${agent ? "" : "text-right"}`}>
          {clock}
        </span>
      )}
    </>
  );
  return (
    <div className={`flex max-w-full flex-col gap-1 ${agent ? "items-start" : "items-end"}`}>
      {seekable && turn.start_ms != null ? (
        <button
          type="button"
          data-turn={turn.idx}
          onClick={() => onSeek(turn.start_ms ?? 0)}
          aria-label={`Play from ${spokenClock(turn.start_ms, turn.start_approximate)}`}
          aria-describedby={wordsId}
          aria-current={active ? "true" : undefined}
          className={`${shape} scroll-mt-48 ${agent ? "hover:bg-ink/[0.07] dark:hover:bg-white/[0.1]" : "hover:bg-brand-soft/70 dark:hover:bg-brand/30"} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2`}
        >
          {body}
        </button>
      ) : (
        <div data-turn={turn.idx} className={`${shape} scroll-mt-48`}>
          {body}
        </div>
      )}
      {agent && turn.likely_cut_off && (
        <p className="max-w-full text-meta text-ink-faint">
          Caller spoke over this part.
        </p>
      )}
      {marker}
    </div>
  );
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
