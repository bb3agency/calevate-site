"use client";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useCampaignWorkspace, useRequestCampaignScript } from "@/lib/api/campaignWorkspace";
import { useInboundLine, useRequestLineScript } from "@/lib/api/inboundLines";
import {
  fixLinesAsk,
  showFinding,
  useScriptChecks,
  type ScriptFinding,
  type ScriptHolder,
} from "@/lib/api/scriptChecks";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/** The one line a non-technical owner reads when the checks hold the script back. */
export const SCRIPT_NEEDS_FIX_TEXT = "A line in the script needs fixing before calls can start.";

/**
 * A refusal of Put it live, Start or a put-live after a save (`script_needs_fix`): one short
 * line and the two things to do about it. The lines themselves are shown where they are
 * edited, each under its own line, and "Show me" goes to the first.
 */
export function ScriptNeedsFix({ holder, canWrite, refusal }: { holder: ScriptHolder; canWrite: boolean; refusal?: string }) {
  return (
    <div role="group" aria-label="The script needs fixing" className="space-y-2 border-l-2 border-danger pl-3">
      <p className="text-body text-ink">{SCRIPT_NEEDS_FIX_TEXT}</p>
      <ScriptFixActions holder={holder} canWrite={canWrite} refusal={refusal} />
    </div>
  );
}

/** "Let Pip fix it" and "Show me", for the holder's saved script. */
export function ScriptFixActions({ holder, canWrite, refusal }: { holder: ScriptHolder; canWrite: boolean; refusal?: string }) {
  return holder.kind === "campaign" ? (
    <CampaignFix id={holder.id} canWrite={canWrite} refusal={refusal} />
  ) : (
    <LineFix id={holder.id} canWrite={canWrite} refusal={refusal} />
  );
}

function CampaignFix({ id, canWrite, refusal }: { id: string; canWrite: boolean; refusal?: string }) {
  const { session } = useClientRealm();
  const script = useCampaignWorkspace(session, id).data?.script ?? null;
  const ask = useRequestCampaignScript(session, id);
  const feedback = useActionFeedback(ask, FEEDBACK);
  return (
    <FixButtons
      holder={{ kind: "campaign", id }}
      script={script}
      status={feedback.status}
      error={ask.error}
      onAsk={(instruction) => feedback.run({ instruction })}
      canWrite={canWrite}
      refusal={refusal}
    />
  );
}

function LineFix({ id, canWrite, refusal }: { id: string; canWrite: boolean; refusal?: string }) {
  const { session } = useClientRealm();
  const script = useInboundLine(session, id).data?.script ?? null;
  const ask = useRequestLineScript(session, id);
  const feedback = useActionFeedback(ask, FEEDBACK);
  return (
    <FixButtons
      holder={{ kind: "line", id }}
      script={script}
      status={feedback.status}
      error={ask.error}
      onAsk={(instruction) => feedback.run({ instruction })}
      canWrite={canWrite}
      refusal={refusal}
    />
  );
}

const FEEDBACK = {
  errorDisplay: "inline",
  successToast: `${ASSISTANT_NAME} is fixing those lines. Review them in Script.`,
} as const;

function FixButtons({
  holder,
  script,
  status,
  error,
  onAsk,
  canWrite,
  refusal,
}: {
  holder: ScriptHolder;
  script: unknown;
  status: FeedbackStatus;
  error: unknown;
  onAsk: (instruction: string) => void;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const checks = useScriptChecks(session, holder, script);
  if (checks.isError) return <ProblemNotice error={checks.error} onRetry={() => checks.refetch()} />;
  const blocking: ScriptFinding[] = checks.isSuccess ? checks.data.findings.filter((f) => f.severity === "block") : [];
  const first = blocking[0];
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          variant="primary-sm"
          status={status}
          pendingLabel={`Asking ${ASSISTANT_NAME}…`}
          successLabel="Asked"
          disabled={!canWrite || blocking.length === 0}
          title={refusal}
          onClick={() => onAsk(fixLinesAsk(blocking))}
        >
          Let {ASSISTANT_NAME} fix it
        </ActionButton>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!first}
          onClick={() => showFinding(first?.stage_id ?? null)}
        >
          Show me
        </button>
      </div>
      {error != null && <ProblemNotice error={error} />}
    </div>
  );
}

/** The checks on the saved script did not answer: said, with a retry, never read as "none". */
export function ChecksUnread({ onRetry }: { onRetry: () => void }) {
  return (
    <p className="mb-2 text-meta text-ink-muted">
      Could not check the script&apos;s lines.{" "}
      <button type="button" className="font-medium text-brand-strong hover:underline" onClick={onRetry}>
        Try again
      </button>
    </p>
  );
}
