"use client";

import { PhoneOutgoing } from "lucide-react";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { formatCount } from "@/components/ui";

/**
 * Launching a campaign: one press (founder, 4 Nov 2026: no further confirmation, because a
 * running campaign can be paused or cancelled). The compliance gate is the server's and
 * runs on every launch whatever this screen does (hard rule 5).
 *
 * The button names the count it dials, so the press is its own review; the when, from
 * where and how many at once sit in the launch summary beside it (`LaunchSummary`).
 *
 * `contacts` is `ProgressOut.total`, the server's count of rows on the campaign; while it
 * is `undefined` there is no launch to offer, because "Call 0 people" would be the one
 * number nobody questioned.
 */
export function LaunchConfirm({
  contacts,
  canWrite,
  writeReason,
  status,
  onLaunch,
  waiting = null,
}: {
  /**
   * Why launch must wait for a read still on its way (the launch check re-running after
   * people were added), or null. Launch is greyed with this line until the read lands.
   */
  waiting?: string | null;
  /** `ProgressOut.total` — `undefined` while it is unknown, and then there is no launch. */
  contacts: number | undefined;
  canWrite: boolean;
  /** `undefined` when nothing refuses — the page's own `refusal`, unchanged. */
  writeReason: string | undefined;
  /** The launch's `useActionFeedback` status: pending, then its tick or failure on the button. */
  status: FeedbackStatus;
  onLaunch: () => void;
}) {
  if (contacts === undefined) {
    return <p className="text-body text-ink-muted">We can&rsquo;t count this list yet, so launch is off.</p>;
  }

  const people = contacts === 1 ? "person" : "people";
  return (
    <div className="space-y-2">
      <ActionButton
        variant="primary-lg"
        title={writeReason}
        disabled={!canWrite || contacts === 0}
        waitingFor={canWrite ? waiting : null}
        status={status}
        pendingLabel="Launching"
        successLabel="Launched"
        onClick={onLaunch}
        className="w-full justify-center sm:w-auto"
      >
        <PhoneOutgoing aria-hidden className="h-4 w-4" />
        {`Call ${formatCount(contacts)} ${people}`}
      </ActionButton>
      <p className="text-meta text-ink-muted">Do-not-call numbers are skipped. Pause any time.</p>
    </div>
  );
}
