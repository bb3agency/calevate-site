import type { ReactNode } from "react";

import { StatusPill } from "@/components/admin/kit";
import { InfoTip } from "@/components/console/infoTip";
import type { NoticeTone } from "@/components/ui";
import type { MaintenanceWindow } from "@/lib/api/maintenance";

/** The "Current window" heading both board states share, with how a window works behind ⓘ. */
export function CurrentWindowHeading({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1">
        <h2 id="maintenance-current" className="text-heading text-ink">
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
/** A window's five states on the admin console's one pill (`components/admin/kit`). */
const PILL_TONE: Record<StateTone, NoticeTone> = {
  neutral: "neutral",
  warn: "warn",
  stop: "stop",
  done: "ok",
  quiet: "neutral",
};

export function StatePill({ tone, children }: { tone: StateTone; children: ReactNode }) {
  return <StatusPill tone={PILL_TONE[tone]}>{children}</StatusPill>;
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
