"use client";

/**
 * HISTORY — every time the script was put live, newest first, by date and the owner's
 * note. No version numbers: an owner remembers "the one from Tuesday with the discount",
 * not "v7". Restore copies an entry into the draft; callers keep the live script until the
 * owner puts the draft live, which the confirmation says before it happens.
 */

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useRestoreVersion, useScriptVersions, type CallScript, type ScriptVersion } from "@/lib/api/script";

export function ScriptHistory({
  agentId,
  onRestored,
}: {
  agentId: string;
  onRestored: (draft: { script: CallScript; saved_at: string }) => void;
}) {
  const session = useClientSession();
  const versions = useScriptVersions(session, agentId);
  const restore = useRestoreVersion(session, agentId);
  const write = useWriteAccess(session, "org:manage", "restore an earlier script");
  const [asking, setAsking] = useState<ScriptVersion | null>(null);

  if (versions.error) return <ProblemNotice error={versions.error} onRetry={() => void versions.refetch()} />;
  if (!versions.data) return <Skeleton rows={4} label="Loading the history" />;
  const rows = versions.data;
  if (rows.length === 0) {
    return <p className="text-body text-ink-muted">Nothing has been put live yet. Each time you do, it is listed here.</p>;
  }
  return (
    <>
      <ul className="divide-y divide-line border-y border-line">
        {rows.map((row) => (
          <li key={row.version} className="flex items-start justify-between gap-3 py-3">
            <div className="min-w-0">
              <p className="text-body text-ink">{row.summary?.trim() || "No note"}</p>
              <p className="mt-0.5 text-meta text-ink-muted">
                {formatIST(row.created_at)}
                {row.is_live ? " · Callers hear this now" : ""}
              </p>
            </div>
            <button
              type="button"
              className={`${TEXT_ACTION} shrink-0`}
              disabled={!write.allowed}
              title={write.reason ?? undefined}
              onClick={() => setAsking(row)}
            >
              Restore
            </button>
          </li>
        ))}
      </ul>
      {asking && (
        <ConfirmDialog
          title="Copy this script into your draft?"
          confirmLabel="Restore to draft"
          pendingLabel="Restoring…"
          cancelLabel="Keep my draft"
          pending={restore.isPending}
          error={restore.error}
          onCancel={() => setAsking(null)}
          onConfirm={() =>
            restore.mutate(asking.version, {
              onSuccess: (draft) => {
                setAsking(null);
                onRestored(draft);
              },
            })
          }
        >
          <p>
            Your current draft is replaced by the script from {formatIST(asking.created_at)}.
            Callers keep hearing the live script until you put the draft live.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
