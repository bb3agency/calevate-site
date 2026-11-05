"use client";

import Link from "next/link";
import { PhoneForwarded } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { PRIMARY_BUTTON, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useCallbackEligibility, useWriteAccess } from "@/lib/api/hooks";

/** The eligibility rule for "a call back booked on this call is still to come". */
const ALREADY_BOOKED = "callback_already_booked";

/**
 * THE ONE THING THIS SCREEN OFFERS TO DO, and why it cannot when it cannot.
 *
 * "Call back now" opens Make a call, the one form for one call (founder, 5 Nov 2026), with
 * this call filled in: it places the follow-up through the same call-back door, and shows
 * the gate's answer and the live status there. What stays here is the eligibility verdict
 * and the write gate, so a call that cannot be followed up says why beside it.
 *
 * A refusal by eligibility is a SENTENCE, not a dead button. A refusal by permission keeps
 * the disabled control with the reason on screen (UX-DOCTRINE §4), because the action
 * exists and someone else in the account can take it.
 */
export function CallBackAction({
  eligibility,
  callHref,
  write,
  leadHref,
  leadLabel,
  bookedShown = false,
}: {
  eligibility: ReturnType<typeof useCallbackEligibility>;
  /** Make a call, pre-filled with this call. */
  callHref: string;
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
        <p className="text-meta text-ink-muted">Can&apos;t call back until this loads.</p>
        {lead}
      </div>
    );
  }
  if (!eligibility.data) return lead;

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
        {write.allowed ? (
          <Link href={callHref} className={PRIMARY_BUTTON}>
            <PhoneForwarded aria-hidden className="h-4 w-4" />
            Call back now
          </Link>
        ) : (
          <button type="button" disabled title={write.reason ?? undefined} className={PRIMARY_BUTTON}>
            <PhoneForwarded aria-hidden className="h-4 w-4" />
            Call back now
          </button>
        )}
        {lead}
      </div>
      {write.allowed ? (
        <p className="text-meta text-ink-muted">Your agent picks up where this call stopped.</p>
      ) : (
        <RestrictionNote reason={write.reason} />
      )}
    </div>
  );
}
