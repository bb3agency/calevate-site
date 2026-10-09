"use client";

import { useState } from "react";
import { PhoneOutgoing } from "lucide-react";

import { WithheldPanel, forbiddenReason, isForbidden } from "@/app/admin/withheld";
import { WriteFailure } from "@/app/admin/writeFailure";
import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import { useOpsConfig, useSetConfig } from "@/lib/api/opsConfig";
import { TRIAL_NUMBER_KEY, useTrialNumber } from "@/lib/api/opsTrialNumber";

type Access = { allowed: boolean; reason: string | null };

/**
 * THE SHARED FREE-TRIAL NUMBER (D-697): every trial account's test calls ring from it.
 *
 * It must be a number our developer workspace holds and no client has recorded, so this
 * panel offers only those, read live from the voice platform; the save goes through the
 * ordinary config write, which checks the choice against the same list. Choosing it is
 * what records it as the platform's own. While trials use it nothing answers it: every
 * test call lends it to the calling agent with nothing set to answer.
 */
export function TrialNumberPanel({ access }: { access: Access }) {
  const numbers = useTrialNumber();
  const config = useOpsConfig();
  const save = useSetConfig();
  const [reason, setReason] = useState("");

  if (isForbidden(numbers.error)) {
    return (
      <WithheldPanel
        title="Shared trial number"
        reason={forbiddenReason(numbers.error) ?? "Your admin account cannot read the platform's numbers."}
        subject="the platform-held numbers that can be the shared trial number"
      />
    );
  }
  if (numbers.error) {
    return <ProblemNotice error={numbers.error} onRetry={() => void numbers.refetch()} />;
  }
  if (numbers.isLoading || numbers.data === undefined) {
    return <Skeleton rows={3} label="Loading the shared trial number" />;
  }
  const data = numbers.data;
  const field = config.data?.fields.find((row) => row.key === TRIAL_NUMBER_KEY);

  return (
    <Card title="Shared trial number" density="compact">
      <div className="space-y-3 p-4 text-sm">
        <p className="text-ink-muted">
          Every free-trial test call rings from this number. Only numbers held in our
          developer workspace and recorded against no client are offered. While trials use
          it, nothing answers it.
        </p>
        {data.current === null ? (
          <NoticeBox tone="warn" title="No shared trial number is set">
            Trial accounts are told test calls are not available yet.
          </NoticeBox>
        ) : data.current_held === false ? (
          <NoticeBox tone="stop" title="The shared trial number is no longer usable">
            {formatPhone(data.current)} is no longer held unrecorded in our developer
            workspace. Choose another below.
          </NoticeBox>
        ) : (
          <p>
            In use: <span className="font-mono font-semibold">{formatPhone(data.current)}</span>
          </p>
        )}
        {data.candidates.length === 0 ? (
          <p className="text-ink-muted">
            Our developer workspace holds no unrecorded number. Buy one in the voice
            platform&apos;s console, then reload.
          </p>
        ) : (
          <>
            <label className="block">
              <span className="block text-xs font-medium text-ink-muted">Reason (required)</span>
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                disabled={!access.allowed}
                className="mt-1 w-full max-w-md rounded-md border border-line bg-transparent px-2 py-1"
              />
            </label>
            <ul className="space-y-2">
              {data.candidates.map((candidate) => (
                <li key={candidate.e164} className="flex flex-wrap items-center gap-3">
                  <span className="font-mono">{formatPhone(candidate.e164)}</span>
                  <span className="text-xs text-ink-muted">
                    {candidate.rented ? "rented" : "brought"}
                    {candidate.answered ? " · an agent answers it now" : ""}
                  </span>
                  <button
                    type="button"
                    className={PRIMARY_BUTTON}
                    title={access.reason ?? undefined}
                    disabled={
                      !access.allowed ||
                      field === undefined ||
                      reason.trim().length < 3 ||
                      save.isPending ||
                      candidate.e164 === data.current
                    }
                    onClick={() => {
                      if (field === undefined) return;
                      save.mutate(
                        {
                          key: TRIAL_NUMBER_KEY,
                          value: candidate.e164,
                          reason: reason.trim(),
                          ifMatch: field.etag,
                        },
                        { onSuccess: () => void numbers.refetch() },
                      );
                    }}
                  >
                    <PhoneOutgoing aria-hidden className="h-4 w-4" />
                    {candidate.e164 === data.current ? "In use" : "Use for trial calls"}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        {save.error != null && <WriteFailure error={save.error} actionLabel="Set the trial number" />}
      </div>
    </Card>
  );
}
