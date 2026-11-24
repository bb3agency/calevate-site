"use client";

/**
 * One press that asks Pip for a draft of the script with a fix named (founder, 24 Nov 2026:
 * what Pip can derive is one press, not a report). The draft waits on the script for the
 * owner to keep or discard; nothing reaches a call before that.
 */

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { useAskPipToRewrite, type Holder } from "@/lib/api/improve";
import { useClientRealm } from "@/lib/api/session";

/** The line page's Script section, where a line's draft is reviewed. */
const LINE_SCRIPT_ANCHOR = "#line-script";

export function AskPipFix({
  holder,
  instruction,
  label,
  canWrite,
  refusal,
}: {
  holder: Holder;
  instruction: string;
  label: string;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const ask = useAskPipToRewrite(session, holder);
  const feedback = useActionFeedback(ask, { errorDisplay: "inline" });
  return (
    <div>
      <ActionButton
        variant="primary-sm"
        status={feedback.status}
        pendingLabel="Asking Pip…"
        successLabel="Asked"
        disabled={!canWrite}
        title={refusal}
        onClick={() => feedback.run({ instruction })}
      >
        {label}
      </ActionButton>
      {ask.isSuccess && (
        <p role="status" className="mt-2 text-meta text-ink">
          Pip is writing it.{" "}
          {holder.kind === "inbound_line" ? (
            <a href={LINE_SCRIPT_ANCHOR} className={TEXT_ACTION_SM}>
              Review it in Script
            </a>
          ) : (
            "Review it in Set up, under Script."
          )}
        </p>
      )}
      {ask.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {problemToast(ask.error, "Pip could not start").description}
        </p>
      )}
    </div>
  );
}
