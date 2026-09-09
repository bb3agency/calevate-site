"use client";

import { Eye, ShieldCheck, User } from "lucide-react";

import { EmptyState, NoticeBox, ProblemNotice, Card } from "@/components/ui";
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
}: {
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
    <Card
      className="lg:col-span-2"
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
        {/* The state of the transcript in front of you, said before you read it.
            Hard rule 5 is invisible otherwise: a client sees an odd-looking number in
            a line and assumes the agent misheard it. */}
        {showingRaw ? (
          <NoticeBox tone="warn" icon={<Eye className="h-5 w-5" />} title="Full transcript">
            You are reading the full text, personal details included. This view was recorded
            in your account&apos;s audit log against your name.
          </NoticeBox>
        ) : (
          <NoticeBox tone="neutral" icon={<ShieldCheck className="h-5 w-5" />}>
            Personal details — phone numbers, account numbers, dates of birth — are hidden in
            this view.
          </NoticeBox>
        )}

        {/* The raw request failing must not take the redacted transcript with it. The
            refusal is stated and the turns below stay exactly as they were. */}
        {showRaw && rawError != null && (
          <ProblemNotice error={rawError} onRetry={onRetryRaw} />
        )}

        {turns.length ? (
          <ol className="space-y-3">
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
              const body = (
                <>
                  <span
                    className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                      speaker?.medallion ?? "bg-black/5 text-ink-muted dark:bg-white/10"
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-baseline gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                      {speaker?.label ?? turn.speaker}
                      {at !== null && at !== undefined && (
                        <span className="font-normal normal-case tabular-nums">
                          {formatClock(at / 1000)}
                        </span>
                      )}
                    </p>
                    <p className="text-sm text-ink">{turn.text}</p>
                  </div>
                </>
              );
              const highlight = active
                ? "bg-brand-strong/10 dark:bg-brand-bright/10"
                : "bg-transparent";
              return (
                <li key={turn.idx}>
                  {seekable ? (
                    <button
                      type="button"
                      onClick={() => onSeek(at)}
                      aria-label={`Play from ${formatClock(at / 1000)}, ${speaker?.label ?? turn.speaker}`}
                      aria-current={active ? "true" : undefined}
                      className={`flex w-full gap-3 rounded-md p-1.5 text-left transition hover:bg-black/5 dark:hover:bg-white/5 ${highlight}`}
                    >
                      {body}
                    </button>
                  ) : (
                    <div className={`flex gap-3 rounded-md p-1.5 ${highlight}`}>{body}</div>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <EmptyState
            title="No transcript yet"
            hint="Transcripts arrive a couple of minutes after the call ends."
          />
        )}
      </div>
    </Card>
  );
}
