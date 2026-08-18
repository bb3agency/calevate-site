"use client";

/**
 * Seconds remaining until a deadline — ONE interval, cleared on every exit (D-174).
 *
 * §5.7 defect 4 is a countdown built the other way, and it is worth reading as a list of
 * what this hook must not do. `startOtpCountdown` created a `setInterval` cleared only
 * when it reached zero; pressing "resend" called it AGAIN while the first was still
 * running, so two intervals decremented the same state and the displayed time ticked down
 * at double speed; and neither was cleared on unmount, so both kept calling `setState` on
 * a component that no longer existed.
 *
 * The fix is not a bigger cleanup — it is not owning a timer by hand at all. One
 * `useEffect` keyed on the DEADLINE, with a cleanup, has all three properties by
 * construction: a new deadline tears the old interval down before starting one, an
 * unmount tears it down, and there is exactly one because React runs the effect once per
 * key change.
 *
 * ## Why the state is a deadline and not a counter
 *
 * A counter decremented once a second drifts: `setInterval` is throttled to once a minute
 * in a background tab and does not fire at all while a phone is asleep, so a counter comes
 * back reading whatever it reached before the tab was hidden. Recomputing from an absolute
 * deadline on every tick means a tab that slept through the whole countdown returns
 * showing zero, which is the truth. The interval then only decides how often the truth is
 * re-read, and being late costs a stale second rather than a wrong number.
 */

import { useEffect, useState } from "react";

const secondsUntil = (deadline: number): number =>
  Math.max(0, Math.ceil((deadline - Date.now()) / 1000));

/**
 * @param deadline - epoch milliseconds, or `null` for "no countdown running".
 * @returns whole seconds remaining; `0` once the deadline has passed or there is none.
 */
export function useCountdown(deadline: number | null): number {
  const [remaining, setRemaining] = useState(() => (deadline === null ? 0 : secondsUntil(deadline)));

  useEffect(() => {
    if (deadline === null) {
      setRemaining(0);
      return;
    }
    // Set immediately as well as on the tick: without this the first second of every
    // countdown displays the PREVIOUS deadline's value, which after a resend is the most
    // visible moment there is.
    setRemaining(secondsUntil(deadline));
    if (deadline <= Date.now()) return;

    const interval = setInterval(() => {
      const left = secondsUntil(deadline);
      setRemaining(left);
      if (left <= 0) clearInterval(interval);
    }, 1000);
    return () => clearInterval(interval);
  }, [deadline]);

  return remaining;
}
