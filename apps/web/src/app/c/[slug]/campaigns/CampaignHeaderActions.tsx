"use client";

import { useState } from "react";
import { ArchiveRestore, Pencil } from "lucide-react";

import { ButtonGroup, type GroupAction } from "@/components/arc/button-group";
import { useActionFeedback, type ActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import {
  useArchiveCampaign,
  useDeleteCampaign,
  useDuplicateCampaign,
  type CampaignProgress,
  type usePauseCampaign,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

type Confirming = "delete" | null;

/**
 * The campaign's buttons, as one `ButtonGroup`, in the copy `show` names: Edit on a draft,
 * Stop campaign (a pause, which Start undoes any time; founder, 16 Nov 2026), Duplicate,
 * and Delete on a draft, which restates what it does in a `ConfirmDialog` first. Start is
 * its own button (`StartCampaign`); Restore is the only move an archived campaign offers.
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
  show = "controls",
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
  /** Which buttons this copy carries (founder, 16 Nov 2026): the controls beside Collapse
   * all, Duplicate beside the campaign's name, Call the unreached again in Where it stands.
   * Archive is the campaigns list's own button. */
  show?: "controls" | "duplicate";
}) {
  const { session, href } = useClientRealm();
  const remove = useDeleteCampaign(session, campaignId);
  const duplicate = useDuplicateCampaign(session, campaignId);
  const shelve = useArchiveCampaign(session, campaignId);
  const shelveFeedback = useActionFeedback(shelve, {
    errorDisplay: "inline",
    successToast: (_out, action) => (action === "archive" ? "Campaign archived" : "Campaign restored"),
  });
  const archived = progress.archived_at != null;
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
  const ownerOnly = canWrite ? undefined : (refusal ?? "Only the account owner can do this.");

  const statusFor = (action: "pause" | "resume") =>
    setStatus.variables === action ? setStatusFeedback.status : "idle";
  const duplicateStatus = (withUnreached: boolean) =>
    Boolean(duplicate.variables?.with_unreached) === withUnreached ? duplicateFeedback.status : "idle";
  // Either copy in flight holds the other (two presses would make two drafts), and a made
  // copy holds both while the page moves to it (not once this screen shows the copy itself).
  // The pressed one keeps its own busy face.
  const copyHeld = (withUnreached: boolean) =>
    (duplicate.isSuccess && duplicate.data.id !== campaignId) ||
    (duplicate.isPending && duplicateStatus(withUnreached) !== "pending");
  const copy = (withUnreached: boolean) =>
    duplicate.mutate({ with_unreached: withUnreached }, { onSuccess: (made) => onCopied(made.id) });

  const actions: GroupAction[] = [];
  if (archived) {
    // F-10: an archived campaign offers only Restore (it comes back paused or as a draft,
    // never running) and a copy.
    actions.push({
      id: "restore",
      label: "Restore",
      icon: <ArchiveRestore className="h-3.5 w-3.5" />,
      status: shelve.variables === "restore" ? shelveFeedback.status : "idle",
      successLabel: "Restored",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => shelveFeedback.run("restore"),
    });
  }
  if (status === "draft" && !archived) {
    actions.push({
      id: "edit",
      label: "Edit",
      icon: <Pencil className="h-3.5 w-3.5" />,
      href: href(`/c/${slug}/campaigns/${campaignId}/edit`),
    });
  }
  // Stop campaign is shown in every state beside Start (founder, 16 Nov 2026), switched off
  // where there is nothing to stop.
  // Stop pauses: it can always be started again, and picks up where it stopped (founder,
  // 16 Nov 2026: "the campaign can be stopped and started anytime").
  const stoppable = !archived && status === "running";
  actions.push({
    id: "stop",
    label: "Stop campaign",
    status: statusFor("pause"),
    successLabel: "Stopped",
    disabled: !canWrite || !stoppable,
    hint: stoppable
      ? ownerOnly
      : status === "scheduled"
        ? "Cancel its start time below."
        : status === "draft"
          ? "It has not started."
          : "It is stopped.",
    onSelect: () => setStatusFeedback.run("pause"),
  });
  actions.push({
    id: "duplicate",
    label: "Duplicate",
    status: duplicateStatus(false),
    successLabel: "Copied",
    disabled: !canWrite || copyHeld(false),
    hint: ownerOnly,
    onSelect: () => copy(false),
  });
  // Delete only a draft that never started: one that ran has calls and charges to keep, so
  // it is archived instead (the server refuses with `campaign_has_history` either way).
  if (status === "draft" && !archived && progress.launched_at == null) {
    actions.push({
      id: "delete",
      label: "Delete draft…",
      tone: "danger",
      disabled: !canWrite,
      hint: ownerOnly,
      onSelect: () => setConfirming("delete"),
    });
  }

  const shown = actions.filter((action) =>
    show === "duplicate" ? action.id === "duplicate" : action.id !== "duplicate",
  );
  if (shown.length === 0) return null;

  return (
    <>
      <ButtonGroup
        label={show === "controls" ? "Campaign actions" : "Copy this campaign"}
        moreLabel={`More actions for ${progress.name}`}
        actions={shown}
        primaryFirst={show !== "duplicate"}
        phoneVisible={1}
        desktopVisible={2}
        className="flex-wrap sm:justify-end"
      />
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
          <span className="block">A campaign that already called anyone is archived instead.</span>
        </ConfirmDialog>
      )}
    </>
  );
}
