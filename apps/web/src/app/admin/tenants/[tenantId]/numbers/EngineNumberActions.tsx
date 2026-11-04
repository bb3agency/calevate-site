"use client";

/**
 * What an operator can do with a number recorded for a client (D-693), in three plain acts:
 *
 * - "Hand it to the client" (a number still in Calevate's account): moves it into the client's
 *   own workspace with the same digits, instead of releasing it and buying again. A number on
 *   a call moves once the call ends.
 * - "Take it back": the client stops paying and the number returns to Calevate's account
 *   with the same digits (moved back first when the client's workspace holds it), free to
 *   give to another client or to ring free-trial test calls again. Also clears our record of
 *   a number the platform no longer holds.
 * - "Give it up for good": releases it at ThinnestAI; anybody may take it next.
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
import { resetIfSettled } from "@/app/admin/resetIfSettled";

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
  /** Still in Calevate's account, so it can be handed to the client. */
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
  const number = formatPhone(e164);

  if (release.data?.released) return <p className="text-meta text-ink-muted">Given up for good. The client is no longer charged for it.</p>;
  if (forget.data?.released) return <p className="text-meta text-ink-muted">Taken back. It is Calevate&apos;s number again and the client is no longer charged.</p>;

  if (move.data?.status === "moved") return <p className="text-meta text-ink-muted">Handed to the client. Same digits, now in their account.</p>;
  if (move.data?.status === "queued") return <p className="text-meta text-ink-muted">The number is on a call. It moves once the call ends; nothing else to do.</p>;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
      {platformHeld && (
        <button
          type="button"
          className={TEXT_ACTION}
          disabled={!canWrite}
          onClick={() => {
            resetIfSettled(move);
            setConfirming("move");
          }}
        >
          Hand it to the client
        </button>
      )}
      <button
        type="button"
        className={TEXT_ACTION}
        disabled={!canWrite}
        onClick={() => {
          resetIfSettled(forget);
          setConfirming("forget");
        }}
      >
        Take it back
      </button>
      <button
        type="button"
        className={TEXT_ACTION_DANGER}
        disabled={!canWrite}
        onClick={() => {
          resetIfSettled(release);
          setConfirming("release");
        }}
      >
        Give it up for good
      </button>
      {confirming === "move" && (
        <ConfirmDialog
          title={`Hand ${number} to this client`}
          confirmLabel="Hand it over"
          pendingLabel="Moving…"
          status={moveFeedback.status}
          error={move.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => move.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            The number keeps its digits and moves into this client&apos;s own account, where their
            agents answer and call from it. They pay for it from next month. An Indian number needs
            the client&apos;s business details approved first.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "forget" && (
        <ConfirmDialog
          title={`Take ${number} back`}
          confirmLabel="Take it back"
          pendingLabel="Taking it back…"
          status={forgetFeedback.status}
          error={forget.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => forget.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            This client stops using and paying for it. The number comes back to Calevate&apos;s
            account with the same digits, free to give to another client or to use for free-trial
            test calls again.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "release" && (
        <ConfirmDialog
          title={`Give up ${number} for good`}
          confirmLabel="Give it up for good"
          pendingLabel="Giving it up…"
          status={releaseFeedback.status}
          error={release.error}
          onCancel={() => setConfirming(null)}
          onConfirm={() => release.mutate(numberId, { onSuccess: () => setConfirming(null) })}
        >
          <p>
            The number goes back to ThinnestAI and anybody may take it next. It cannot be got back.
            This month is not refunded. The client is no longer charged for it.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
