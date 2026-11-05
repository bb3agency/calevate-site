"use client";

/**
 * What Pip changed in an opening line to say the AI or recording notice (D-971), with the
 * way back. Founder, 5 Nov 2026: the rewrite goes live by itself, and the Script tab shows
 * what changed with an Undo. "Put mine back" puts the owner's line live again; it is not
 * rewritten after that, and the notice is then said as its own sentence beside it.
 */

import { NoticeBox, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { useWriteAccess } from "@/lib/api/hooks";
import type { Session } from "@/lib/api/client";
import {
  rewrittenOpening,
  usePutBackOpeningLine,
  type CallScript,
  type OpeningWhen,
} from "@/lib/api/script";

export function OpeningRewritten({
  session,
  agentId,
  script,
  both,
}: {
  session: Session;
  agentId: string;
  script: CallScript;
  both: boolean;
}) {
  const putBack = usePutBackOpeningLine(session, agentId);
  const feedback = useActionFeedback(putBack, {
    successToast: "Your line is back and live.",
    errorTitle: "Your line could not be put back",
  });
  const write = useWriteAccess(session, "org:manage", "change the opening line");
  const whens: OpeningWhen[] = both ? ["answers", "calls"] : ["answers"];
  const rows = whens.flatMap((when) => {
    const change = rewrittenOpening(script, when);
    return change ? [{ when, ...change }] : [];
  });
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <NoticeBox
          key={row.when}
          tone="info"
          role="status"
          title={
            <span className="flex items-center gap-1">
              {both && row.when === "calls"
                ? "Pip added the notices to your calling line"
                : "Pip added the notices to your opening line"}
              <InfoTip label="why Pip changed it">
                With a notice switched on, Pip says it in your opening line in a few words, so
                callers do not hear a separate sentence. Putting yours back keeps the notice as
                its own sentence.
              </InfoTip>
            </span>
          }
          action={
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!write.allowed || feedback.status === "pending"}
              title={write.reason ?? undefined}
              onClick={() => feedback.run(row.when)}
            >
              {feedback.status === "pending" ? "Putting it back…" : "Put mine back"}
            </button>
          }
        >
          <dl className="mt-1 space-y-1 text-body">
            <div>
              <dt className="text-meta text-ink-muted">Before</dt>
              <dd className="break-words text-ink-muted line-through decoration-ink-muted/50">
                {row.before}
              </dd>
            </div>
            <div>
              <dt className="text-meta text-ink-muted">Now</dt>
              <dd className="break-words text-ink">{row.after}</dd>
            </div>
          </dl>
        </NoticeBox>
      ))}
    </div>
  );
}
