"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, type ReactNode } from "react";

import { useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import type { Session } from "@/lib/api/client";
import { useCancelCampaignDraft, useClearCampaignProposal, useKeepCampaignDraftLive } from "@/lib/api/campaignWorkspace";
import { useCancelLineDraft, useClearLineProposal, useKeepLineDraftLive } from "@/lib/api/inboundLines";
import { useNow } from "@/lib/copilot/useNow";
import { isTerminalPhase, useScriptDraftStream, type DraftPhase, type ScriptDraftHolder } from "@/lib/scriptDraft/stream";

import { ScriptDraftView, type DraftOutcome } from "./ScriptDraftView";

const KEPT = "Kept. The new script is live.";
const DISCARDED = "Draft discarded. Your script is as it was.";

export interface ScriptDraftLiveProps {
  session: Session;
  holder: ScriptDraftHolder;
  /** The draft, when the caller knows it; the diff names it too. */
  proposalId: string;
  /** Why this person cannot keep or discard it, or null when they can. */
  refusal?: string | null;
  /** Told each phase, and whether the draft is now settled (kept, discarded or ended). */
  onPhase?: (phase: DraftPhase, settled: boolean) => void;
  /** Drawn instead when the draft stream cannot be read (the page's own review). */
  fallback?: ReactNode;
  /** More ways to decide beside Keep and Discard. */
  extra?: ReactNode;
  /**
   * Confirm Keep and Discard in a toast too: on a page the draft view goes as soon as the
   * holder reloads without a draft, taking its own "Kept" line with it.
   */
  toastOutcome?: boolean;
}

/**
 * The live script draft for one holder, with the real stream and the real Keep (keep and
 * put live), Discard and Stop writing. A campaign and an Inbound line keep their drafts
 * behind different routes, so each has its own small wrapper and both draw `DraftBody`.
 */
export function ScriptDraftLive(props: ScriptDraftLiveProps) {
  return props.holder.kind === "campaign" ? <CampaignDraft {...props} /> : <LineDraft {...props} />;
}

function CampaignDraft(props: ScriptDraftLiveProps) {
  const { session, holder } = props;
  const keepLive = useKeepCampaignDraftLive(session, holder.id);
  const keepFeedback = useActionFeedback(keepLive, {
    errorTitle: "Could not keep the script",
    successToast: props.toastOutcome ? KEPT : undefined,
  });
  const discard = useClearCampaignProposal(session, holder.id);
  const discardFeedback = useActionFeedback(discard, {
    errorTitle: "Could not discard the draft",
    successToast: props.toastOutcome ? DISCARDED : undefined,
  });
  const cancel = useCancelCampaignDraft(session, holder.id);
  const cancelFeedback = useActionFeedback(cancel, { errorTitle: "Could not stop writing" });
  return (
    <DraftBody
      {...props}
      keep={keepFeedback}
      discard={discardFeedback}
      cancel={cancelFeedback}
      outcome={keepLive.isSuccess ? "kept" : discard.isSuccess ? "discarded" : null}
    />
  );
}

function LineDraft(props: ScriptDraftLiveProps) {
  const { session, holder } = props;
  const keepLive = useKeepLineDraftLive(session, holder.id);
  const keepFeedback = useActionFeedback(keepLive, {
    errorTitle: "Could not keep the script",
    successToast: props.toastOutcome ? KEPT : undefined,
  });
  const discard = useClearLineProposal(session, holder.id);
  const discardFeedback = useActionFeedback(discard, {
    errorTitle: "Could not discard the draft",
    successToast: props.toastOutcome ? DISCARDED : undefined,
  });
  const cancel = useCancelLineDraft(session, holder.id);
  const cancelFeedback = useActionFeedback(cancel, { errorTitle: "Could not stop writing" });
  return (
    <DraftBody
      {...props}
      keep={keepFeedback}
      discard={discardFeedback}
      cancel={cancelFeedback}
      outcome={keepLive.isSuccess ? "kept" : discard.isSuccess ? "discarded" : null}
    />
  );
}

type Control = { status: FeedbackStatus; run: (proposalId: string) => void };

function DraftBody({
  session,
  holder,
  proposalId,
  refusal = null,
  onPhase,
  fallback = null,
  extra,
  keep,
  discard,
  cancel,
  outcome,
}: ScriptDraftLiveProps & { keep: Control; discard: Control; cancel: Control; outcome: DraftOutcome }) {
  const state = useScriptDraftStream(session, holder, outcome === null);
  const reduced = useReducedMotion() === true;
  const now = useNow(!isTerminalPhase(state.phase));
  // The diff names the draft it is about; it wins over what the caller was told.
  const draft = state.diff?.proposal_id ?? proposalId;
  const settled = outcome !== null || state.phase === "failed" || state.phase === "cancelled";

  useEffect(() => {
    if (state.phase !== null) onPhase?.(state.phase, settled);
  }, [state.phase, settled, onPhase]);

  if (state.unavailable) return <>{fallback}</>;
  return (
    <ScriptDraftView
      state={state}
      now={now}
      reduced={reduced}
      outcome={outcome}
      waitingFor={refusal}
      keep={{ status: keep.status, run: () => keep.run(draft) }}
      discard={{ status: discard.status, run: () => discard.run(draft) }}
      cancel={{ status: cancel.status, run: () => cancel.run(draft) }}
      extra={extra}
    />
  );
}
