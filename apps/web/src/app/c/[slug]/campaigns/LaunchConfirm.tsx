"use client";

import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { formatCount, formatPhone } from "@/components/ui";

/**
 * Launching a campaign: one press, with what it does said beside the button (founder,
 * 4 Nov 2026: no further confirmation, because a running campaign can be paused or
 * cancelled). The compliance gate is the server's and runs on every launch whatever this
 * screen does (hard rule 5).
 *
 * `contacts` is `ProgressOut.total`, the server's count of rows on the campaign; while it
 * is `undefined` there is no launch to offer, because "This calls 0 people" would be the
 * one number nobody questioned. The calling window and the number are stated as the server
 * reports them: `callingHours` null means the platform's 9am–9pm IST window alone, and
 * `numberE164` null means the agent's own line.
 */
export function LaunchConfirm({
  contacts,
  concurrency,
  callingHours,
  numberE164,
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
  /** `ProgressOut.effective_concurrency`: the slider under the plan ceiling and line pool. */
  concurrency: number | undefined;
  /** `ProgressOut.calling_hours` — the campaign's own narrowing, null when it has none. */
  callingHours: { start: string; end: string } | null | undefined;
  /** `ProgressOut.number_e164` — null when this campaign dials from no number of its own. */
  numberE164: string | null | undefined;
  canWrite: boolean;
  /** `undefined` when nothing refuses — the page's own `refusal`, unchanged. */
  writeReason: string | undefined;
  /** The launch's `useActionFeedback` status: pending, then its tick or failure on the button. */
  status: FeedbackStatus;
  onLaunch: () => void;
}) {
  if (contacts === undefined) {
    return (
      <p className="text-sm text-ink-muted">
        We can&rsquo;t count this list yet, so launch is off.
      </p>
    );
  }

  const people = contacts === 1 ? "person" : "people";
  const hours = callingHours ? `${callingHours.start}–${callingHours.end} IST` : "9am–9pm IST";
  const from = numberE164 ? `from ${formatPhone(numberE164)}` : "from your agent's number";
  const atOnce = concurrency !== undefined ? `, up to ${formatCount(concurrency)} at once` : "";

  return (
    <div className="space-y-2">
      <ActionButton
        variant="primary"
        title={writeReason}
        disabled={!canWrite || contacts === 0}
        waitingFor={canWrite ? waiting : null}
        status={status}
        pendingLabel="Launching"
        successLabel="Launched"
        onClick={onLaunch}
        className="w-full sm:w-auto"
      >
        {`Call ${formatCount(contacts)} ${people}`}
      </ActionButton>
      <p className="text-meta text-ink-muted">
        {`Calls ${hours}, ${from}${atOnce}. Do-not-call numbers are skipped. Pause any time.`}
      </p>
    </div>
  );
}
