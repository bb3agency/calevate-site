"use client";

/**
 * Release a recorded ThinnestAI number, or release only OUR record of it (D-693).
 *
 * The two are different acts and both are offered: "Release" gives the number back to the
 * pool at ThinnestAI for good; "Release our record" stops our record and the client's
 * monthly charge without touching ThinnestAI — for a number it no longer holds, or a
 * platform-held test number being taken back. The server refuses the second for a number
 * the client's own workspace still holds (`engine_number_still_held`).
 *
 * A number held in the platform account also offers "Move to client workspace": it moves into
 * the client's own workspace with the same digits, instead of being released and bought again.
 * A number on a call is moved once the call ends.
 */

import { formatPhone } from "@/components/ui";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import {
  useWorkspaceForget,
  useWorkspaceMove,
  useWorkspaceRelease,
} from "@/lib/api/engineWorkspaces";

export function EngineNumberActions({
  tenantId,
  numberId,
  e164,
  platformHeld = false,
  canWrite,
}: {
  tenantId: string;
  numberId: string;
  e164: string;
  /** Held in the platform account, so it can be moved into the client's workspace. */
  platformHeld?: boolean;
  canWrite: boolean;
}) {
  const release = useWorkspaceRelease(tenantId);
  const forget = useWorkspaceForget(tenantId);
  const move = useWorkspaceMove(tenantId);
  // Inline: each dialog shows its refusal inside, where the decision is being made.
  const releaseFeedback = useActionFeedback(release, { errorDisplay: "inline" });
  const forgetFeedback = useActionFeedback(forget, { errorDisplay: "inline" });
  const moveFeedback = useActionFeedback(move, { errorDisplay: "inline" });
  const [confirming, setConfirming] = useState<"release" | "forget" | "move" | null>(null);

  if (release.data?.released) return <p className="text-meta text-ink-muted">Released. The monthly charge has stopped.</p>;
  if (forget.data?.released) return <p className="text-meta text-ink-muted">Our record is released. The monthly charge has stopped.</p>;

  if (move.data?.status === "moved") return <p className="text-meta text-ink-muted">Moved into the client&apos;s workspace with the same digits.</p>;
  if (move.data?.status === "queued") return <p className="text-meta text-ink-muted">The number is on a call. It moves once the call ends; nothing else to do.</p>;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {platformHeld && (
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={!canWrite}
          onClick={() => {
            move.reset();
            setConfirming("move");
          }}
        >
          Move to client workspace
        </button>
      )}
      <button
        type="button"
        className={TEXT_ACTION_DANGER}
        disabled={!canWrite}
        onClick={() => {
          release.reset();
          setConfirming("release");
        }}
      >
        Release
      </button>
      <button
        type="button"
        className={TEXT_ACTION}
        disabled={!canWrite}
        onClick={() => {
          forget.reset();
          setConfirming("forget");
        }}
      >
        Release our record
      </button>
      {confirming === "release" && (
        <ConfirmDialog
          title={`Release ${formatPhone(e164)}`}
          confirmLabel="Release for good"
          pendingLabel="Releasing…"
          status={releaseFeedback.status}
          error={release.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => release.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            Permanent: the number goes back to the pool and anybody may take it next. This month is
            not refunded, by ThinnestAI or to the client. The client&apos;s monthly charge stops.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "move" && (
        <ConfirmDialog
          title={`Move ${formatPhone(e164)} to the client's workspace`}
          confirmLabel="Move it"
          pendingLabel="Moving…"
          status={moveFeedback.status}
          error={move.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => move.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            The number keeps its digits and moves into this client&apos;s own workspace, then answers
            the client&apos;s agent there. From its next renewal the client pays its monthly charge.
            An Indian number needs the client&apos;s business details approved first.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "forget" && (
        <ConfirmDialog
          title={`Release our record of ${formatPhone(e164)}`}
          confirmLabel="Release our record"
          pendingLabel="Releasing…"
          status={forgetFeedback.status}
          error={forget.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => forget.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            Stops our record and the client&apos;s monthly charge without releasing anything at
            ThinnestAI. For a number ThinnestAI no longer holds, or a test number held in the
            platform account (it is detached from this client&apos;s agents and stays ours). A number
            the client&apos;s own workspace still holds is refused: release that one instead.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
