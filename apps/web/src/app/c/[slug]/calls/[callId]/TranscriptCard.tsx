"use client";

import { Section } from "@/components/console/section";
import { Eye, ShieldCheck, User } from "lucide-react";

import { NoticeBox, ProblemNotice, RestrictionNote } from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import { SPEAKERS } from "./speakers";
import { RawTranscriptControl, type RawTranscriptAccess } from "./transcriptAccess";

/**
 * The transcript, and the notice that says WHICH transcript you are reading.
 *
 * Its own file because the notice is a hard-rule-5 surface and the turns are the most
 * sensitive markup in the product: the redacted/raw sentence renders ABOVE the turns, in
 * both states, and a raw read that FAILS must leave the redacted turns exactly where they
 * were. Those three properties are the file.
 */
export function TranscriptCard({
  turns,
  showingRaw,
  showRaw,
  rawError,
  rawPending,
  onRetryRaw,
  rawAccess,
  onToggleRaw,
  audioLoaded,
  playhead,
  onSeek,
  className = "",
}: {
  className?: string;
  turns: NonNullable<CallDetail["transcript"]>;
  showingRaw: boolean;
  showRaw: boolean;
  rawError: unknown;
  rawPending: boolean;
  onRetryRaw: () => void;
  rawAccess: RawTranscriptAccess;
  onToggleRaw: () => void;
  audioLoaded: boolean;
  playhead: number | null;
  onSeek: (ms: number) => void;
}) {
  return (
    <Section
      className={className}
      title="Transcript"
      action={
        <RawTranscriptControl
          access={rawAccess}
          showRaw={showRaw}
          pending={rawPending}
          onToggle={onToggleRaw}
        />
      }
    >
      <div className="space-y-4">
        {/* WHY THE CONTROL ABOVE IS DEAD, on the SCREEN and not only in a tooltip.
            `RestrictionNote` renders nothing while `/v1/me` is in flight, so the sentence
            never flashes and is never retracted; a refusal we have not received is not a
            refusal (§52). Above the notices rather than below the turns, because a reader
            deciding whether they are seeing everything asks this before they read. */}
        {!rawAccess.allowed && <RestrictionNote reason={rawAccess.reason} />}

        {/* The state of the transcript in front of you, said before you read it.
            Hard rule 5 is invisible otherwise: a client sees an odd-looking number in
            a line and assumes the agent misheard it. */}
        {showingRaw ? (
          <NoticeBox tone="warn" icon={<Eye className="h-5 w-5" />} title="Full transcript">
            You are reading the full text, personal details included. This view was recorded
            in your account&apos;s audit log against your name.
          </NoticeBox>
        ) : (
          <p className="flex items-start gap-2 rounded-md bg-ink/[0.03] px-3 py-2 text-meta text-ink-muted">
            <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-strong" />
            <span>
              Personal details — phone numbers, account numbers, dates of birth — are hidden in
              this view.
            </span>
          </p>
        )}

        {/* The raw request failing must not take the redacted transcript with it. The
            refusal is stated and the turns below stay exactly as they were. */}
        {showRaw && rawError != null && (
          <ProblemNotice error={rawError} onRetry={onRetryRaw} />
        )}

        {turns.length ? (
          // A PLAIN SCRIPT, not chat bubbles (founder, REDESIGN-2): who spoke, small and
          // muted, then what they said, with space between turns. The turn the recording is
          // playing gets a quiet brand rule on its left.
          <ol className="space-y-5">
            {turns.map((turn, i) => {
              const speaker = lookup(SPEAKERS, turn.speaker);
              const Icon = speaker?.icon ?? User;
              // A turn is seekable only once the audio is actually loaded AND this
              // turn carries a timestamp. Both halves matter: `start_ms` is nullable
              // (an engine that gives us no per-turn offsets is a supported engine),
              // and offering to seek audio that is not playing yet is a control that
              // does nothing. Where either is missing the turn renders as plain text
              // rather than as a dead button.
              const at = turn.start_ms;
              const seekable = audioLoaded && at !== null && at !== undefined;
              // "Being spoken now" = this turn has started and the next has not. The
              // NEXT turn's start is the right boundary rather than this turn's
              // `end_ms`, which is nullable independently and would leave gaps
              // un-highlighted between two turns that are actually adjacent.
              const nextAt = turns[i + 1]?.start_ms;
              const active =
                playhead !== null &&
                at !== null &&
                at !== undefined &&
                playhead * 1000 >= at &&
                (nextAt === null || nextAt === undefined || playhead * 1000 < nextAt);
              const agent = turn.speaker === "agent";
              const name = speaker?.label ?? turn.speaker;
              // Caller on the left, agent on the right: the convention a chat reader
              // already has, and the same sides the live speaking indicator uses.
              const body = (
                <span
                  className={`block w-full border-l-2 pl-3 text-left ${active ? "border-brand" : "border-transparent"}`}
                >
                  <span
                    className={`flex items-baseline gap-2 text-meta ${agent ? "text-brand-strong" : "text-ink-muted"}`}
                  >
                    <Icon aria-hidden className="h-3 w-3 self-center" />
                    {name}
                    {at !== null && at !== undefined && (
                      <span className="tabular-nums text-ink-faint">{formatClock(at / 1000)}</span>
                    )}
                  </span>
                  <span className="mt-1 block max-w-prose text-body leading-relaxed text-ink">{turn.text}</span>
                </span>
              );
              return (
                <li key={turn.idx}>
                  {seekable ? (
                    <button
                      type="button"
                      onClick={() => onSeek(at)}
                      aria-label={`Play from ${formatClock(at / 1000)}, ${name}`}
                      aria-current={active ? "true" : undefined}
                      className="flex w-full rounded-sm text-left hover:bg-ink/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                    >
                      {body}
                    </button>
                  ) : (
                    body
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <EmptyState
            message="No transcript yet"
            hint="Transcripts arrive a couple of minutes after the call ends."
          />
        )}
      </div>
    </Section>
  );
}
