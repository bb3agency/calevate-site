"use client";

import { useReducedMotion } from "motion/react";
import { useEffect, type ReactNode } from "react";

import { useActionFeedback, type ActionFeedback } from "@/components/arc/feedback";
import type { Session } from "@/lib/api/client";
import {
  useCancelCampaignDraft,
  useClearCampaignProposal,
  useKeepCampaignDraftLive,
  useRequestCampaignScript,
  type ScriptAsk,
} from "@/lib/api/campaignWorkspace";
import { useCancelLineDraft, useClearLineProposal, useKeepLineDraftLive, useRequestLineScript } from "@/lib/api/inboundLines";
import { isPromptTooLong } from "@/lib/api/scriptChecks";
import { useNow } from "@/lib/copilot/useNow";
import { isTerminalPhase, useScriptDraftStream, type DraftPhase, type ScriptDraftHolder } from "@/lib/scriptDraft/stream";

import { ScriptDraftView, type DraftOutcome, type DraftTooLong } from "./ScriptDraftView";

const KEPT = "Kept. The new script is live.";
const DISCARDED = "Draft discarded. Your script is as it was.";

/**
 * What "Ask Pip for a shorter one" sends: a new request for the whole script, which replaces
 * the ready draft (`request_proposal`), with the reason. Pip reads the instruction; the owner
 * never sees it.
 */
export const SHORTER_ASK: ScriptAsk = {
  tone: "brief",
  instruction:
    "The last draft was too long to put live on calls. Write a shorter script: keep every step " +
    "and every detail it must collect, but say each thing in fewer words and drop anything said twice.",
};

/** The too-long block for a refused Keep, or null when the refusal is anything else. */
export function tooLongOf(error: unknown, shorter: DraftTooLong["shorter"]): DraftTooLong | null {
  return isPromptTooLong(error) ? { detail: error.message, shorter } : null;
}

/** A draft too long to keep has its own block on the draft (`TooLongDraft`); the rest toast. */
const keepErrorDisplay = (error: unknown) => (isPromptTooLong(error) ? "inline" : "toast");

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
 * put live), Discard, Stop writing, and a shorter draft when Keep is refused as too long. A
 * campaign and an Inbound line keep their drafts behind different routes, so each has its
 * own small wrapper and both draw `DraftBody`.
 */
export function ScriptDraftLive(props: ScriptDraftLiveProps) {
  return props.holder.kind === "campaign" ? <CampaignDraft {...props} /> : <LineDraft {...props} />;
}

function CampaignDraft(props: ScriptDraftLiveProps) {
  const { session, holder } = props;
  const keepLive = useKeepCampaignDraftLive(session, holder.id);
  const keepFeedback = useActionFeedback(keepLive, {
    errorTitle: "Could not keep the script",
    errorDisplay: keepErrorDisplay,
    successToast: props.toastOutcome ? KEPT : undefined,
  });
  const discard = useClearCampaignProposal(session, holder.id);
  const discardFeedback = useActionFeedback(discard, {
    errorTitle: "Could not discard the draft",
    successToast: props.toastOutcome ? DISCARDED : undefined,
  });
  const cancel = useCancelCampaignDraft(session, holder.id);
  const cancelFeedback = useActionFeedback(cancel, { errorTitle: "Could not stop writing" });
  const ask = useRequestCampaignScript(session, holder.id);
  const askFeedback = useActionFeedback(ask, { errorTitle: "Could not ask Pip" });
  return (
    <DraftBody
      {...props}
      keep={keepFeedback}
      keptDraft={keepLive.variables}
      discard={discardFeedback}
      cancel={cancelFeedback}
      shorter={askFeedback}
      outcome={keepLive.isSuccess ? "kept" : discard.isSuccess ? "discarded" : null}
    />
  );
}

function LineDraft(props: ScriptDraftLiveProps) {
  const { session, holder } = props;
  const keepLive = useKeepLineDraftLive(session, holder.id);
  const keepFeedback = useActionFeedback(keepLive, {
    errorTitle: "Could not keep the script",
    errorDisplay: keepErrorDisplay,
    successToast: props.toastOutcome ? KEPT : undefined,
  });
  const discard = useClearLineProposal(session, holder.id);
  const discardFeedback = useActionFeedback(discard, {
    errorTitle: "Could not discard the draft",
    successToast: props.toastOutcome ? DISCARDED : undefined,
  });
  const cancel = useCancelLineDraft(session, holder.id);
  const cancelFeedback = useActionFeedback(cancel, { errorTitle: "Could not stop writing" });
  const ask = useRequestLineScript(session, holder.id);
  const askFeedback = useActionFeedback(ask, { errorTitle: "Could not ask Pip" });
  return (
    <DraftBody
      {...props}
      keep={keepFeedback}
      keptDraft={keepLive.variables}
      discard={discardFeedback}
      cancel={cancelFeedback}
      shorter={askFeedback}
      outcome={keepLive.isSuccess ? "kept" : discard.isSuccess ? "discarded" : null}
    />
  );
}

type Control = ActionFeedback<string>;

function DraftBody({
  session,
  holder,
  proposalId,
  refusal = null,
  onPhase,
  fallback = null,
  extra,
  keep,
  keptDraft,
  discard,
  cancel,
  shorter,
  outcome,
}: ScriptDraftLiveProps & {
  keep: Control;
  /** The draft the last Keep was for: its refusal belongs to that draft, never the next one. */
  keptDraft: string | undefined;
  discard: Control;
  cancel: Control;
  shorter: ActionFeedback<ScriptAsk | undefined>;
  outcome: DraftOutcome;
}) {
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
  const refused = keep.status === "error" && keptDraft === draft ? keep.error : null;
  return (
    <ScriptDraftView
      state={state}
      now={now}
      reduced={reduced}
      outcome={outcome}
      waitingFor={refusal}
      keep={{ status: keep.status, retryable: keep.retryable, run: () => keep.run(draft) }}
      discard={{ status: discard.status, retryable: discard.retryable, run: () => discard.run(draft) }}
      cancel={{ status: cancel.status, retryable: cancel.retryable, run: () => cancel.run(draft) }}
      tooLong={tooLongOf(refused, {
        status: shorter.status,
        retryable: shorter.retryable,
        run: () => shorter.run(SHORTER_ASK),
      })}
      extra={extra}
    />
  );
}
