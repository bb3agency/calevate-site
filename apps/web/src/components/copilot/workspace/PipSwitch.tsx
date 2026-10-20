"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { Section } from "@/components/console/section";
import { ProblemNotice, SECONDARY_BUTTON, Skeleton, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { usePipConsent, useTurnPipOff } from "@/lib/copilot/conversation";

import { PipConsentGate } from "../PipConsent";

/**
 * Pip's settings: whether it is on for the account, and the owner's switch (D-839). Turning
 * it off is the owner's alone, signed in as themselves; anyone else reads who can. While it is
 * off the owner turns it on again here, through the same disclosure the panel shows.
 */
export function PipSwitch({ session }: { session: Session }) {
  const consent = usePipConsent(session);
  const turnOff = useTurnPipOff(session);
  const [confirming, setConfirming] = useState(false);

  return (
    <Section title={`${ASSISTANT_NAME} for this account`}>
      {consent.error != null ? (
        <ProblemNotice error={consent.error} onRetry={() => void consent.refetch()} />
      ) : !consent.data ? (
        <Skeleton rows={2} label={`Reading whether ${ASSISTANT_NAME} is on`} />
      ) : consent.data.status === "accepted" ? (
        <div className="space-y-3 px-4 py-4">
          <p className="text-body text-ink">
            {ASSISTANT_NAME} is on for everyone on this account
            {consent.data.accepted_at ? `, since ${formatIST(consent.data.accepted_at)}` : ""}.
          </p>
          {consent.data.can_withdraw ? (
            <>
              <p className="text-body text-ink-muted">
                Turning it off stops {ASSISTANT_NAME} answering anyone on the account. Tasks and
                routines that have not started yet will not run. Nothing already done is undone.
              </p>
              <button type="button" className={SECONDARY_BUTTON} onClick={() => setConfirming(true)}>
                Turn {ASSISTANT_NAME} off
              </button>
            </>
          ) : (
            <p className="text-body text-ink-muted">Only the account owner can turn it off.</p>
          )}
        </div>
      ) : (
        <div>
          {consent.data.status === "withdrawn" && consent.data.withdrawn_at && (
            <p className="px-4 pt-4 text-body text-ink-muted">
              Turned off on {formatIST(consent.data.withdrawn_at)}.
            </p>
          )}
          <PipConsentGate session={session} consent={consent.data} />
        </div>
      )}

      {confirming && (
        <ConfirmDialog
          title={`Turn ${ASSISTANT_NAME} off for everyone?`}
          confirmLabel={`Turn ${ASSISTANT_NAME} off`}
          pendingLabel="Turning off…"
          pending={turnOff.isPending}
          error={turnOff.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => turnOff.mutate(undefined, { onSuccess: () => setConfirming(false) })}
        >
          <p>
            No one on this account can ask {ASSISTANT_NAME} anything until you turn it on again, and
            tasks and routines that have not started will not run. You can turn it on again here.
          </p>
        </ConfirmDialog>
      )}
    </Section>
  );
}
