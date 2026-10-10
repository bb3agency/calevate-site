"use client";

import { useState } from "react";

import {
  NoticeBox,
  PRIMARY_BUTTON,
  RestrictionNote,
  formatINR,
} from "@/components/ui";
import { AcceptChargeDialog, extraUnavailableSentence } from "@/components/aiExtraDialog";
import { useBuyAiExtra, type AiQuota } from "@/lib/api/aiQuota";
import { useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";

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
      <NoticeBox tone="warn" title="AI help is paused right now">
        <p className="mt-1">
          We have paused AI help across Calevate while we check unusually high usage.
          Your calls, campaigns and leads are unaffected, and nothing has been charged.
          It comes back on its own — ask us if you need it sooner.
        </p>
      </NoticeBox>
    );
  }

  if (quota.state === "exhausted") {
    return (
      <NoticeBox tone="stop" title="This month's AI help is finished">
        <p className="mt-1">
          You have used the AI help included with your plan and the extra you added. It
          starts again at the beginning of next month. Talk to us if
          you need more before then.
        </p>
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
  // `POST /v1/billing/ai-quota/extra` requires `org:manage` — a MUTATING permission, so
  // `staff` does not hold it and an impersonating operator is refused it (D-22).
  // Disabled with the reason beside it, rather than a 403 after the click.
  const write = useWriteAccess(session, "org:manage", "add more AI help");

  return (
    <>
      <NoticeBox tone="warn" title="You have used this month's included AI help">
        <p className="mt-1">
          AI help in the console has stopped for this month. Everything else — your
          calls, campaigns and leads — carries on exactly as before.
        </p>
        {quota.extra_available ? (
          <>
            <div className="mt-3">
              <RestrictionNote reason={write.reason} />
            </div>
            <button
              type="button"
              className={`${PRIMARY_BUTTON} mt-3`}
              disabled={!write.allowed}
              onClick={() => setAsking(true)}
            >
              See what more AI help costs
            </button>
          </>
        ) : (
          <p className="mt-3">{extraUnavailableSentence(quota)}</p>
        )}
      </NoticeBox>

      {asking && (
        <AcceptChargeDialog
          quota={quota}
          pending={buy.isPending}
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
          <NoticeBox tone="ok" title="Added">
            <p className="mt-1">
              {formatINR(buy.data.extra_block_inr)} was taken from your calling credit and
              AI help is available again for the rest of {buy.data.month}.
            </p>
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
