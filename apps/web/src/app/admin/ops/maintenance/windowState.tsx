import type { ReactNode } from "react";

import { InfoTip } from "@/components/console/infoTip";
import type { MaintenanceWindow } from "@/lib/api/maintenance";

/** The "Current window" heading both board states share, with how a window works behind ⓘ. */
export function CurrentWindowHeading({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1">
        <h2 id="maintenance-current" className="text-[17px] font-semibold text-ink">
          Current window
        </h2>
        <InfoTip label="How a window works">
          <p>
            A planned window closes the client portals and answers inbound callers with a
            message instead of doing business. It opens by DRAINING — no new calls, no new
            campaign dials — and only becomes active once nothing is left in flight.
          </p>
        </InfoTip>
      </div>
      {children}
    </div>
  );
}

export type StateTone = "neutral" | "warn" | "stop" | "done" | "quiet";

/**
 * Pill colours from the status tokens. Not `StatusBadge`, which looks its value up in the
 * lead/call vocabulary and would paint all five maintenance states the same grey.
 */
const TONE_CLASS: Record<StateTone, string> = {
  neutral: "bg-ink/[0.06] text-ink",
  warn: "border border-warn-line bg-warn-soft text-warn",
  stop: "border border-danger-line bg-danger-soft text-danger",
  done: "bg-brand-soft text-brand-strong",
  quiet: "bg-ink/[0.06] text-ink-muted",
};

export function StatePill({ tone, children }: { tone: StateTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

/** Where each state sits in the two-state model, in the operator's words. */
export const STATE_COPY: Record<
  MaintenanceWindow["state"],
  { label: string; tone: StateTone; what: string }
> = {
  scheduled: {
    label: "Scheduled",
    tone: "neutral",
    what: "Nothing has changed yet. Clients see a banner; calls and campaigns run normally.",
  },
  draining: {
    label: "Draining",
    tone: "warn",
    what:
      "The platform has stopped starting new work and is waiting for what is already " +
      "running. Client portals are still OPEN. Inbound callers hear the maintenance " +
      "message; campaigns are paused.",
  },
  active: {
    label: "Active",
    tone: "stop",
    what:
      "Client portals are closed. Inbound calls are still answered, with the maintenance " +
      "message. Nothing has been deleted.",
  },
  completed: { label: "Finished", tone: "done", what: "Everything is back." },
  cancelled: { label: "Called off", tone: "quiet", what: "The window never opened." },
};
