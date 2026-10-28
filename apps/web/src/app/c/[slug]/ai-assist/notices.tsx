"use client";

import { useState } from "react";

import {
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatINR,
} from "@/components/ui";
import { useActionFeedback } from "@/components/arc/feedback";
import { AcceptChargeDialog, extraUnavailableSentence } from "@/components/aiExtraDialog";
import { useBuyAiExtra, type AiQuota } from "@/lib/api/aiQuota";
import { useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";

import { AI_ASSIST_COPY as COPY, addedLine } from "./copy";

/**
 * What state this month is in, in the SERVER's own words.
 *
 * The four states are named by the API (`state`), not derived here from three numbers,
 * for the reason the module docstring gives: two implementations of "is this account at
 * its ceiling" is how a screen ends up offering a purchase the route will refuse.
 */
export function StateNotice({ quota, session }: { quota: AiQuota; session: Session }) {
  if (quota.state === "platform_paused") {
    return (
      <NoticeBox
        tone="warn"
        title={COPY.pausedTitle}
        info={COPY.pausedTip}
      >
        {COPY.pausedBody}
      </NoticeBox>
    );
  }

  if (quota.state === "exhausted") {
    return (
      <NoticeBox tone="stop" title={COPY.finishedTitle}>
        {COPY.finishedBody}
      </NoticeBox>
    );
  }

  if (quota.state === "ceiling_reached") {
    return <CeilingReached quota={quota} session={session} />;
  }

  return null;
}

/** The ceiling, and the only control in this console that debits a wallet. */
function CeilingReached({ quota, session }: { quota: AiQuota; session: Session }) {
  const [asking, setAsking] = useState(false);
  const buy = useBuyAiExtra(session);
  // The dialog shows a failure beside its button, and success closes it onto the "Added" notice.
  const buyFeedback = useActionFeedback(buy, { errorDisplay: "inline" });
  // `POST /v1/billing/ai-quota/extra` requires `org:manage` — a MUTATING permission, so
  // `staff` does not hold it and an impersonating operator is refused it (D-22).
  // Disabled with the reason beside it, rather than a 403 after the click.
  const write = useWriteAccess(session, "org:manage", "add more AI help");

  return (
    <>
      <NoticeBox tone="warn" title={COPY.ceilingTitle}>
        <p>{COPY.ceilingOff}</p>
        <p>{COPY.ceilingCarryOn}</p>
        {quota.extra_available ? (
          <>
            <div className="mt-3">
              <RestrictionNote reason={write.reason} />
            </div>
            <button
              type="button"
              className={`${PRIMARY_BUTTON} mt-3 max-sm:w-full max-sm:justify-center`}
              disabled={!write.allowed}
              onClick={() => setAsking(true)}
            >
              {COPY.seePrice}
            </button>
          </>
        ) : (
          <p className="mt-3">{extraUnavailableSentence(quota)}</p>
        )}
      </NoticeBox>

      {asking && (
        <AcceptChargeDialog
          quota={quota}
          pending={buyFeedback.status === "pending"}
          error={buy.error}
          onCancel={() => {
            buy.reset();
            setAsking(false);
          }}
          onAccept={() =>
            // The SERVER's figure, echoed back untouched. Nothing here computes an
            // amount, and a mismatch is refused rather than clamped.
            buy.mutate(quota.extra_block_inr, { onSuccess: () => setAsking(false) })
          }
        />
      )}

      {buy.data && !asking && (
        <div role="status">
          <NoticeBox tone="ok" title={COPY.addedTitle}>
            <p className="mt-1">{addedLine(formatINR(buy.data.extra_block_inr))}</p>
          </NoticeBox>
        </div>
      )}
    </>
  );
}

export function Row({
  label,
  value,
  emphasis,
  muted,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
  /** A COMPONENT of the row above, not a charge of its own — rendered a step in and a
   *  shade back so nobody adds it to the total it is already inside (D-608). */
  muted?: boolean;
}) {
  return (
    <div className={`flex justify-between gap-4${muted ? " pl-3" : ""}`}>
      <dt className={muted ? "text-ink-faint" : "text-ink-muted"}>{label}</dt>
      <dd
        className={
          emphasis
            ? "shrink-0 font-semibold tabular-nums text-ink"
            : muted
              ? "shrink-0 tabular-nums text-ink-faint"
              : "shrink-0 tabular-nums text-ink-muted"
        }
      >
        {value}
      </dd>
    </div>
  );
}
