"use client";

/**
 * Time left until an instant, as words: "2 h 14 min", "45 s", then the caller's "done"
 * sentence. For a wait a person is watching: the next calling window opening, a trial
 * ending today, a campaign starting.
 *
 * Adapted from uiarc's `countdown` (MIT, see ./LICENSE) as presentation over the app's one
 * ticking engine, `lib/authn/useCountdown` (an interval keyed on an absolute deadline);
 * Arc's digit wheels and pulse ring are not carried over. The device clock can be wrong,
 * so a screen that has the server's "now" passes it (`serverNow`): the offset between the
 * two is measured once and the deadline shifted by it, so the count is right on a laptop
 * whose clock is ten minutes out. Long waits are not ticked to the second — past an hour
 * the seconds are dropped, and past two days the target is better shown as an IST date
 * (`formatIST`) than as a countdown.
 */

import { useState } from "react";

import { useCountdown } from "@/lib/authn/useCountdown";
import { formatIST } from "@/components/ui";

export type CountdownProps = {
  /** The instant, ISO 8601 with its offset (as the API sends it). */
  target: string;
  /** The server's "now" from the same response, to correct a wrong device clock. */
  serverNow?: string;
  /** Before the count: "Calling opens in". */
  label?: string;
  /** Shown once the target has passed: "Calling is open". */
  doneText?: string;
  /** Unit words, overridable for another language. */
  units?: { day: string; hour: string; minute: string; second: string };
  /** Show the IST target after the count: "(25 Oct, 09:00 am)". */
  showTarget?: boolean;
  className?: string;
};

const UNITS = { day: "d", hour: "h", minute: "min", second: "s" };

export function formatRemaining(seconds: number, units = UNITS): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (d > 0) return `${d} ${units.day} ${h} ${units.hour}`;
  if (h > 0) return `${h} ${units.hour} ${m} ${units.minute}`;
  if (m > 0) return `${m} ${units.minute} ${s} ${units.second}`;
  return `${s} ${units.second}`;
}

export function Countdown({
  target,
  serverNow,
  label,
  doneText = "Now",
  units = UNITS,
  showTarget = false,
  className = "",
}: CountdownProps) {
  // Measured once, at mount: how far the device clock is from the server's.
  const [offsetMs] = useState(() => {
    const server = serverNow ? Date.parse(serverNow) : NaN;
    return Number.isNaN(server) ? 0 : server - Date.now();
  });
  const at = Date.parse(target);
  const valid = !Number.isNaN(at);
  const remaining = useCountdown(valid ? at - offsetMs : null);
  if (!valid) {
    return <span className={`text-meta text-ink-faint ${className}`}>—</span>;
  }
  const done = remaining <= 0;
  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-1.5 ${className}`}>
      {label && !done ? <span className="text-ink-muted">{label}</span> : null}
      {/* `role="timer"` is not live by default, so the per-second change is not read out
          every second; a reader hears it when they reach it. */}
      <span role="timer" aria-atomic="true" className="font-medium tabular-nums text-ink">
        {done ? doneText : formatRemaining(remaining, units)}
      </span>
      {showTarget && !done ? <span className="text-meta text-ink-faint">({formatIST(target)})</span> : null}
    </span>
  );
}
