/**
 * How much of the free trial is left, as a ring that empties: the mark beside the trial in
 * the top bar (D-771). It replaces a gift glyph, which said "present" about an account that
 * was running out.
 *
 * The ring is the SMALLER of the two allowances (days and free minutes), because the trial
 * stops at whichever runs out first. An ended trial is an empty ring drawn dashed in the warn
 * chart tone, so it reads as "nothing left" and not as a full one.
 *
 * It is decorative: the label beside it states the same figures in words, so it is
 * `aria-hidden` and carries no text. Colours are token presentation attributes, like
 * `disconnectedCall.tsx`, so a palette change moves it too.
 */

import type { SVGProps } from "react";

const R = 6;
const C = 2 * Math.PI * R;

export function TrialMeter({
  left,
  className,
  ...props
}: {
  /** 0..1 of the trial still available; 0 draws the ended ring. */
  left: number;
} & SVGProps<SVGSVGElement>) {
  const share = Math.min(1, Math.max(0, Number.isFinite(left) ? left : 0));
  const ended = share === 0;
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden focusable="false" className={className} {...props}>
      <circle
        cx={8}
        cy={8}
        r={R}
        stroke={ended ? "var(--chart-warn)" : "var(--line)"}
        strokeWidth={2}
        strokeDasharray={ended ? "2.2 2.2" : undefined}
      />
      {!ended && (
        <circle
          cx={8}
          cy={8}
          r={R}
          stroke="var(--brand)"
          strokeWidth={2}
          strokeLinecap="round"
          // Starts at twelve o'clock and runs clockwise, like a clock face that has been used up.
          transform="rotate(-90 8 8)"
          strokeDasharray={`${(share * C).toFixed(2)} ${C.toFixed(2)}`}
        />
      )}
    </svg>
  );
}

/** The share of a running trial still available: the smaller of days and free minutes. */
export function trialShareLeft(trial: {
  days: number;
  days_remaining?: number | null;
  free_minutes?: number | null;
  minutes_left?: number | null;
}): number {
  const shares: number[] = [];
  if (trial.days > 0 && trial.days_remaining !== null && trial.days_remaining !== undefined) {
    shares.push(trial.days_remaining / trial.days);
  }
  if (
    trial.free_minutes !== null &&
    trial.free_minutes !== undefined &&
    trial.free_minutes > 0 &&
    trial.minutes_left !== null &&
    trial.minutes_left !== undefined
  ) {
    shares.push(trial.minutes_left / trial.free_minutes);
  }
  // A running trial with nothing to measure still has something left: draw it full.
  return shares.length === 0 ? 1 : Math.min(...shares);
}
