"use client";

import { Section } from "@/components/console/section";
import type { CallDetail } from "@/lib/api/client";
import {
  CATEGORY_DOT,
  CATEGORY_LABEL,
  momentClock,
  momentSeekMs,
} from "@/lib/callMoments";

/**
 * "Key moments": the places in the call worth hearing, so nobody has to play it all. The
 * same moments are markers on the recording's track and on their transcript lines; this
 * list is their readable, clickable form. Hidden when empty (the screen decides).
 *
 * Each row: the time, the moment in plain words, and underneath its group (details and
 * bookings, needs attention, buying signal) plus "Suggested" when the model chose it.
 * Model moments are suggestions because their quality is unscored (D-36); a derived one
 * was found by matching what the caller said.
 *
 * A time with "~" is the voice platform's rough position for that line, not a point in the
 * audio. Pressing a row plays from a couple of seconds earlier so the moment is not missed,
 * and opens the recording first when it is not open yet (opening it is audited, so it only
 * happens on a press).
 */
export function KeyMomentsCard({
  moments,
  playhead,
  onPlay,
  canPlay,
}: {
  moments: CallDetail["moments"];
  playhead: number | null;
  /** Play from this many milliseconds, opening the recording if needed. */
  onPlay: (ms: number) => void;
  /** False when the call has no recording: the rows are then a plain list. */
  canPlay: boolean;
}) {
  const approximate = moments.some((moment) => moment.precision === "approximate");
  return (
    <Section title="Key moments">
      <ol className="-mx-2 mt-1 space-y-0.5">
        {moments.map((moment, i) => {
          const start = momentSeekMs(moment);
          const next = moments[i + 1];
          const active =
            playhead !== null &&
            playhead * 1000 >= start &&
            (next === undefined || playhead * 1000 < momentSeekMs(next));
          const clock = momentClock(moment);
          const body = (
            <>
              <span className="w-12 shrink-0 pt-px text-meta tabular-nums text-ink-muted">
                {clock}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-body text-ink">{moment.label}</span>
                <span className="mt-0.5 flex items-center gap-1.5 text-meta text-ink-faint">
                  <span
                    aria-hidden="true"
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${CATEGORY_DOT[moment.category]}`}
                  />
                  {CATEGORY_LABEL[moment.category]}
                  {moment.source === "model" && <span>· Suggested</span>}
                </span>
              </span>
            </>
          );
          const row = `flex w-full items-start gap-3 rounded-md px-2 py-2 text-left ${
            active ? "bg-brand-soft/60" : ""
          }`;
          return (
            <li key={`${moment.at_ms}-${moment.kind}-${i}`}>
              {canPlay ? (
                <button
                  type="button"
                  onClick={() => onPlay(start)}
                  aria-label={`Play from ${clock}: ${moment.label}${
                    moment.source === "model" ? " (suggested)" : ""
                  }`}
                  aria-current={active ? "true" : undefined}
                  className={`${row} touch-manipulation transition-colors duration-(--duration-fast) ease-out select-none hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand active:bg-ink/[0.05] motion-reduce:transition-none`}
                >
                  {body}
                </button>
              ) : (
                <div className={row}>{body}</div>
              )}
            </li>
          );
        })}
      </ol>
      {approximate && (
        <p className="mt-2 text-meta text-ink-faint">
          Times marked ~ are approximate, so playback starts a couple of seconds early.
        </p>
      )}
    </Section>
  );
}
