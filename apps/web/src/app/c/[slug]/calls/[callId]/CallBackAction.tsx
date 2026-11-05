"use client";

import Link from "next/link";
import { PhoneForwarded } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { ActionButton, type FeedbackStatus } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useCallBack, useCallbackEligibility, useWriteAccess } from "@/lib/api/hooks";

/** The eligibility rule for "a call back booked on this call is still to come". */
const ALREADY_BOOKED = "callback_already_booked";

/**
 * THE ONE THING THIS SCREEN OFFERS TO DO, and why it cannot when it cannot.
 *
 * Three answers share this slot: the server's eligibility verdict, the write gate, and the
 * compliance gate's 200-with-a-reason. Each reaches the person beside the action rather
 * than in a toast. The label is the consequence ("Have the agent call back now"), the
 * button is the screen's one filled control, and the lead link beside it is a text action.
 *
 * A refusal by eligibility is a SENTENCE, not a dead button: "a call back is already
 * booked for 10 Oct at 18:03" is the answer, and a greyed control under it would only
 * repeat it. A refusal by permission keeps the disabled button with the reason on screen
 * (UX-DOCTRINE §4), because the action exists and someone else in the account can take it.
 */
export function CallBackAction({
  eligibility,
  callback,
  status,
  onCallBack,
  write,
  leadHref,
  leadLabel,
  bookedShown = false,
}: {
  eligibility: ReturnType<typeof useCallbackEligibility>;
  callback: ReturnType<typeof useCallBack>;
  /** The press's state, from the screen's `useActionFeedback`. */
  status: FeedbackStatus;
  onCallBack: () => void;
  write: ReturnType<typeof useWriteAccess>;
  leadHref: string | null;
  leadLabel: string;
  /** The call's booked call back is on screen beside this action. */
  bookedShown?: boolean;
}) {
  const lead = leadHref ? (
    <Link href={leadHref} className={TEXT_ACTION}>
      {leadLabel}
    </Link>
  ) : null;

  if (eligibility.isLoading) {
    return (
      <div className="max-w-xs">
        <Skeleton rows={1} label="Checking whether this call can be called back" />
      </div>
    );
  }
  if (eligibility.error != null) {
    return (
      <div className="space-y-3">
        <ProblemNotice error={eligibility.error} onRetry={() => void eligibility.refetch()} />
        <p className="text-meta text-ink-muted">
          Can&apos;t call back until this loads.
        </p>
        {lead}
      </div>
    );
  }
  if (!eligibility.data) return lead;

  if (callback.data?.status === "queued") {
    return (
      <div className="space-y-3">
        <NoticeBox tone="ok">
          Calling back now (call-back #{callback.data.follow_up_number}).
        </NoticeBox>
        {lead}
      </div>
    );
  }
  if (callback.data?.status === "blocked") {
    // The compliance gate answers 200 with a reason. The server has recorded it against
    // this call, so the reason replaces the button rather than inviting a second press.
    return (
      <div className="space-y-3">
        <NoticeBox tone="warn">
          {callback.data.blocked_reason ?? "This call-back was not allowed."}
        </NoticeBox>
        {lead}
      </div>
    );
  }

  if (!eligibility.data.eligible) {
    // The booked call back is already its own line above, with its time; the refusal saying
    // the same thing again in other words read as a second booking.
    const repeats = bookedShown && eligibility.data.rule === ALREADY_BOOKED;
    return (
      <div className="space-y-3">
        {eligibility.data.reason && !repeats && (
          // The icon ties the sentence to calling back: alone, the calling-hours rule read
          // as something that happened on this call (4 Nov 2026 call review).
          <p className="flex items-start gap-2 text-body text-ink-muted [text-wrap:pretty]">
            <PhoneForwarded aria-hidden className="mt-1 h-4 w-4 shrink-0" />
            {eligibility.data.reason}
          </p>
        )}
        {lead}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <ActionButton
          status={status}
          pendingLabel="Calling…"
          successLabel="Calling"
          disabled={!write.allowed}
          title={write.allowed ? undefined : (write.reason ?? undefined)}
          onClick={onCallBack}
        >
          <PhoneForwarded aria-hidden className="h-4 w-4" />
          Call back now
        </ActionButton>
        {lead}
      </div>
      {write.allowed ? (
        <p className="text-meta text-ink-muted">
          Your agent picks up where this call stopped.
        </p>
      ) : (
        <RestrictionNote reason={write.reason} />
      )}
      {callback.error != null && <ProblemNotice error={callback.error} />}
    </div>
  );
}
