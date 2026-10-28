"use client";

import { useState } from "react";
import { Pause, Pencil, Play, RotateCcw } from "lucide-react";

import { ButtonGroup, type GroupAction } from "@/components/arc/button-group";
import { useActionFeedback, type ActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { formatCount } from "@/components/ui";
import {
  useDeleteCampaign,
  useDuplicateCampaign,
  useStopCampaign,
  type CampaignProgress,
  type usePauseCampaign,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

type Confirming = "stop" | "delete" | null;

/** A pause whose cause must be cleared before Resume works: the notice above says how. */
const HELD_PAUSES = ["complaint_spike", "out_of_credit", "spend_cap"];

/**
 * The controls this state allows, and nothing the server would refuse, as one
 * `ButtonGroup`: the one move the state is about first (Edit a draft, Pause a running
 * campaign, Resume a paused one, Call the unreached again once it is over), then Stop for
 * good while it can still call, because a control that stops calls stays reachable however
 * seldom it is used (UX-DOCTRINE §3). Duplicate always, Delete on a draft. Stop and Delete
 * restate what they do in a `ConfirmDialog` before they act.
 *
 * A pause with a cause still outstanding keeps Resume disabled behind the review, and the
 * notice under the header carries the fix as its own action.
 */
export function CampaignHeaderActions({
  slug,
  campaignId,
  progress,
  setStatus,
  setStatusFeedback,
  canWrite,
  refusal,
  onGone,
  onCopied,
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
  setStatus: ReturnType<typeof usePauseCampaign>;
  setStatusFeedback: ActionFeedback<"pause" | "resume">;
  canWrite: boolean;
  refusal: string | undefined;
  onGone: () => void;
  onCopied: (id: string) => void;
}) {
  const { session, href } = useClientRealm();
  const stop = useStopCampaign(session, campaignId);
  const remove = useDeleteCampaign(session, campaignId);
  const duplicate = useDuplicateCampaign(session, campaignId);
  const stopFeedback = useActionFeedback(stop, {
    errorDisplay: "inline",
    successToast: "Campaign stopped",
    successDescription: "Nobody else on the list will be called.",
  });
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: "Draft deleted",
  });
  const duplicateFeedback = useActionFeedback(duplicate, {
    errorTitle: "Could not copy this campaign",
    successToast: (_copy, vars) =>
      vars.with_unreached ? "New draft made with the people not reached" : "Copy made as a new draft",
  });
  const [confirming, setConfirming] = useState<Confirming>(null);
  const status = progress.status;
  const finished = status === "completed" || status === "cancelled";
  const reviewOwed = progress.complaint_review_required;
  const held = HELD_PAUSES.includes(progress.pause_reason ?? "");
  const remaining = (progress.contacts.pending ?? 0) + (progress.contacts.dialing ?? 0);
  const ownerOnly = canWrite ? undefined : (refusal ?? "Only the account owner can do this.");

  const statusFor = (action: "pause" | "resume") =>
    setStatus.variables === action ? setStatusFeedback.status : "idle";
  const duplicateStatus = (withUnreached: boolean) =>
    Boolean(duplicate.variables?.with_unreached) === withUnreached ? duplicateFeedback.status : "idle";
  const copy = (withUnreached: boolean) =>
    duplicate.mutate({ with_unreached: withUnreached }, { onSuccess: (made) => onCopied(made.id) });

  const actions: GroupAction[] = [];
  if (status === "draft") {
    actions.push({
      id: "edit",
      label: "Edit",
      icon: <Pencil className="h-3.5 w-3.5" />,
      href: href(`/c/${slug}/campaigns/${campaignId}/edit`),
    });
  }
  if (status === "running") {
    actions.push({
      id: "pause",
      label: "Pause",
      icon: <Pause className="h-3.5 w-3.5" />,
      status: statusFor("pause"),
      successLabel: "Paused",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => setStatusFeedback.run("pause"),
    });
  }
  if (status === "paused") {
    actions.push({
      id: "resume",
      label: "Resume",
      icon: <Play className="h-3.5 w-3.5" />,
      status: statusFor("resume"),
      successLabel: "Resumed",
      disabled: !canWrite || reviewOwed,
      hint: reviewOwed
        ? "Review the opt-outs first."
        : held
          ? "Fix the reason above first."
          : ownerOnly,
      onSelect: () => setStatusFeedback.run("resume"),
    });
  }
  if (finished) {
    actions.push({
      id: "again",
      label: "Call the unreached again",
      icon: <RotateCcw className="h-3.5 w-3.5" />,
      status: duplicateStatus(true),
      successLabel: "Copied",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => copy(true),
    });
  }
  if (status === "running" || status === "paused" || status === "scheduled") {
    actions.push({
      id: "stop",
      label: "Stop for good…",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => setConfirming("stop"),
    });
  }
  actions.push({
    id: "duplicate",
    label: "Duplicate",
    status: duplicateStatus(false),
    successLabel: "Copied",
    disabled: !canWrite,
    hint: ownerOnly,
    onSelect: () => copy(false),
  });
  if (status === "draft") {
    actions.push({
      id: "delete",
      label: "Delete draft…",
      tone: "danger",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => setConfirming("delete"),
    });
  }

  return (
    <>
      <ButtonGroup
        label="Campaign actions"
        moreLabel={`More actions for ${progress.name}`}
        actions={actions}
        phoneVisible={1}
        desktopVisible={2}
        className="flex-wrap sm:justify-end"
      />
      {confirming === "stop" && (
        <ConfirmDialog
          title="Stop this campaign for good?"
          confirmLabel="Stop for good"
          pendingLabel="Stopping"
          cancelLabel="Keep it"
          status={stopFeedback.status}
          error={stopFeedback.error ?? null}
          onCancel={() => {
            stopFeedback.reset();
            setConfirming(null);
          }}
          onConfirm={() => stop.mutate(undefined, { onSuccess: () => setConfirming(null) })}
        >
          <span className="block">
            Nobody else is called{remaining ? ` (${formatCount(remaining)} waiting)` : ""}.
          </span>
          <span className="block">Calls ringing now finish. It can&rsquo;t restart.</span>
        </ConfirmDialog>
      )}
      {confirming === "delete" && (
        <ConfirmDialog
          title="Delete this draft?"
          confirmLabel="Delete draft"
          pendingLabel="Deleting"
          cancelLabel="Keep it"
          status={removeFeedback.status}
          error={removeFeedback.error ?? null}
          onCancel={() => {
            removeFeedback.reset();
            setConfirming(null);
          }}
          onConfirm={() => remove.mutate(undefined, { onSuccess: onGone })}
        >
          <span className="block">The draft and its list are removed.</span>
          <span className="block">If calls already used it, it is kept as stopped.</span>
        </ConfirmDialog>
      )}
    </>
  );
}
