"use client";

import { Section } from "@/components/console/section";
import { formatClock } from "@/components/callAudioPlayer";
import type { CallDetail } from "@/lib/api/client";

/**
 * "Key moments" — the reason somebody does not have to play the call again. The same
 * moments are ticks on the recording's seek bar; this list is their readable, clickable form.
 *
 * The panel is HIDDEN when there is nothing in it. An always-present "Key points"
 * heading over an empty box on every forty-second appointment booking is a heading
 * people learn to skip, and then miss on the call that has six.
 *
 * ## Two provenances, shown differently, because they deserve different trust
 *
 * A `derived` marker is arithmetic: the server found the extracted value inside a turn
 * and took that turn's own `start_ms`. It cannot be at the wrong second. A `model` one
 * is a sentence an unmeasured model wrote about the call (D-36 records that Sarvam's
 * Telugu extraction quality has never been scored), and it is labelled as a suggestion.
 * Presenting them identically would force a reader to distrust both — the cheapest way
 * to waste the half that is exact.
 *
 * ## Clicking seeks, and only when seeking is possible
 *
 * The rows are buttons only once the audio is loaded, for the same reason a transcript
 * turn is: a control that silently does nothing is worse than no control. Before that
 * they are a readable list of what happened and when, which is worth something on its
 * own — an owner scanning for "did they ask about price" does not always want to listen.
 */
export function KeyMomentsCard({
  moments,
  audioLoaded,
  playhead,
  onSeek,
}: {
  moments: CallDetail["moments"];
  audioLoaded: boolean;
  playhead: number | null;
  onSeek: (ms: number) => void;
}) {
  return (
    <Section title="Key moments">
      <ol className="space-y-1">
        {moments.map((moment, i) => {
          const next = moments[i + 1]?.at_ms;
          const active =
            playhead !== null &&
            playhead * 1000 >= moment.at_ms &&
            (next === undefined || playhead * 1000 < next);
          const suggested = moment.source === "model";
          const body = (
            <>
              <span className="w-12 shrink-0 text-meta tabular-nums text-ink-faint">
                {formatClock(moment.at_ms / 1000)}
              </span>
              <span className="min-w-0 flex-1 text-body text-ink">{moment.label}</span>
              {suggested && (
                <span
                  className="shrink-0 text-meta text-ink-faint"
                  title="Suggested from the transcript. The time may be a few seconds out."
                >
                  Suggested
                </span>
              )}
            </>
          );
          const tone = active ? "bg-brand-soft/60" : "";
          return (
            <li key={`${moment.at_ms}-${moment.kind}-${i}`}>
              {audioLoaded ? (
                <button
                  type="button"
                  onClick={() => onSeek(moment.at_ms)}
                  aria-label={`Play from ${formatClock(moment.at_ms / 1000)} — ${moment.label}`}
                  aria-current={active ? "true" : undefined}
                  className={`flex w-full items-baseline gap-3 rounded-md px-2 py-1.5 text-left transition-colors duration-(--duration-fast) ease-out hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand motion-reduce:transition-none ${tone}`}
                >
                  {body}
                </button>
              ) : (
                <div className={`flex items-baseline gap-3 rounded-md px-2 py-1.5 ${tone}`}>
                  {body}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {!audioLoaded && (
        <p className="mt-2 text-meta text-ink-faint">
          Open the recording to jump to any of these.
        </p>
      )}
    </Section>
  );
}
