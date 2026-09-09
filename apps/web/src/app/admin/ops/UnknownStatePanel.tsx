"use client";

import { CircleHelp } from "lucide-react";

import { NoticeBox } from "@/components/ui";

/**
 * THE STATE WE COULD NOT READ, said as itself.
 *
 * This panel is the whole point of the `boolean | null` above. The screen it replaces
 * rendered the halt form over a `?? false`, so the most dangerous render this console can
 * produce — "outbound is running" when we have no idea — was also its default one. There
 * is no control here on purpose: an operator who needs the switch during an outage needs
 * the runbook's curl, not a button that posts a transition computed from nothing.
 */
export function UnknownStatePanel({ reason }: { reason: string | null }) {
  return (
    <NoticeBox
      tone="warn"
      icon={<CircleHelp aria-hidden className="h-5 w-5" />}
      title="We do not know whether outbound calling is halted"
    >
      <p className="mt-1">
        The platform state could not be read, so this screen will not tell you it is
        running and it will not tell you it is stopped. Treat the switch as unknown until
        this loads — the error above says what stopped it.
      </p>
      {/* The load-shed mode lives on the same row and failed with it. Its control is
          absent for the same reason the halt's is: a mode selected against a current mode
          nobody read is a change whose direction is a guess. */}
      <p className="mt-2">
        The load-shed mode is on that same row, so it is unknown too, and neither switch
        is offered here while that is true.
      </p>
      {reason && <p className="mt-2">{reason}</p>}
      <p className="mt-2 text-xs">
        If calls have stopped and you need the switch now, the “calls stopped” runbook
        walks through sending it by hand.
      </p>
    </NoticeBox>
  );
}
