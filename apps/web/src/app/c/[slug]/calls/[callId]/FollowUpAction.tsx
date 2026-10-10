"use client";

import Link from "next/link";
import { PhoneForwarded } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, PRIMARY_BUTTON, ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useCallBack, useCallbackEligibility, useWriteAccess } from "@/lib/api/hooks";

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
export function FollowUpAction({
  eligibility,
  callback,
  write,
  leadHref,
  leadLabel,
}: {
  eligibility: ReturnType<typeof useCallbackEligibility>;
  callback: ReturnType<typeof useCallBack>;
  write: ReturnType<typeof useWriteAccess>;
  leadHref: string | null;
  leadLabel: string;
}) {
  const lead = leadHref ? (
    <Link href={leadHref} className={TEXT_ACTION}>
      {leadLabel}
    </Link>
  ) : null;

  if (eligibility.isLoading) {
    return (
      <div className="max-w-xs">
        <Skeleton rows={1} label="Checking whether this call can be followed up" />
      </div>
    );
  }
  if (eligibility.error != null) {
    return (
      <div className="space-y-3">
        <ProblemNotice error={eligibility.error} onRetry={() => void eligibility.refetch()} />
        <p className="text-meta text-ink-muted">
          We could not check whether this call can be followed up, so the button stays closed.
        </p>
        {lead}
      </div>
    );
  }
  if (!eligibility.data) return lead;

  if (callback.data?.status === "queued") {
    return (
      <div className="space-y-3">
        <NoticeBox tone="ok" icon={<PhoneForwarded className="h-5 w-5" />}>
          Calling back now — follow-up #{callback.data.follow_up_number}. It will appear in your
          call log in a moment.
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
          {callback.data.blocked_reason ?? "This follow-up call was not allowed."}
        </NoticeBox>
        {lead}
      </div>
    );
  }

  if (!eligibility.data.eligible) {
    return (
      <div className="space-y-3">
        {eligibility.data.reason && <p className="text-body text-ink-muted">{eligibility.data.reason}</p>}
        {lead}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={!write.allowed || callback.isPending}
          title={write.allowed ? undefined : (write.reason ?? undefined)}
          onClick={() => callback.mutate()}
        >
          <PhoneForwarded aria-hidden className="h-4 w-4" />
          {callback.isPending ? "Calling…" : "Have the agent call back now"}
        </button>
        {lead}
      </div>
      {write.allowed ? (
        <p className="text-meta text-ink-muted">
          The agent rings this number and picks up where this conversation stopped.
        </p>
      ) : (
        <RestrictionNote reason={write.reason} />
      )}
      {callback.error != null && <ProblemNotice error={callback.error} />}
    </div>
  );
}
