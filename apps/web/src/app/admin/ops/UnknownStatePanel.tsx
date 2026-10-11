"use client";


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
      title="We do not know whether outbound calling is halted"
    >
      <p>Treat the switch as unknown until this loads. The error above says why.</p>
      {/* The load-shed mode lives on the same row and failed with it. Its control is
          absent for the same reason the halt's is: a mode selected against a current mode
          nobody read is a change whose direction is a guess. */}
      <p>The load-shed mode is on that same row, so it is unknown too. Neither switch is offered.</p>
      {reason && <p className="mt-2">{reason}</p>}
      <p className="text-meta">Need the switch now? The “calls stopped” runbook sends it by hand.</p>
    </NoticeBox>
  );
}
