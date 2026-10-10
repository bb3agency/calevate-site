"use client";

/**
 * Release a recorded ThinnestAI number, or release only OUR record of it (D-693).
 *
 * The two are different acts and both are offered: "Release" gives the number back to the
 * pool at ThinnestAI for good; "Release our record" stops our record and the client's
 * monthly charge without touching ThinnestAI — for a number it no longer holds, or a
 * platform-held test number being taken back. The server refuses the second for a number
 * the client's own workspace still holds (`engine_number_still_held`).
 */

import { formatPhone } from "@/components/ui";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { useWorkspaceForget, useWorkspaceRelease } from "@/lib/api/engineWorkspaces";

export function EngineNumberActions({
  tenantId,
  numberId,
  e164,
  canWrite,
}: {
  tenantId: string;
  numberId: string;
  e164: string;
  canWrite: boolean;
}) {
  const release = useWorkspaceRelease(tenantId);
  const forget = useWorkspaceForget(tenantId);
  const [confirming, setConfirming] = useState<"release" | "forget" | null>(null);

  if (release.data?.released) return <p className="text-meta text-ink-muted">Released. The monthly charge has stopped.</p>;
  if (forget.data?.released) return <p className="text-meta text-ink-muted">Our record is released. The monthly charge has stopped.</p>;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1">
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
          pending={release.isPending}
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
      {confirming === "forget" && (
        <ConfirmDialog
          title={`Release our record of ${formatPhone(e164)}`}
          confirmLabel="Release our record"
          pendingLabel="Releasing…"
          pending={forget.isPending}
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
