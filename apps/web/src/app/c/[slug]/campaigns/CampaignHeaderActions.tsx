"use client";

import Link from "next/link";
import { useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";

import { RowMenu, type RowMenuItem } from "@/components/console/rowMenu";
import {
  DANGER_BUTTON,
  NOTICE_BAR,
  NOTICE_BASE,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  formatCount,
} from "@/components/ui";
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
 * The controls this state allows, and nothing the server would refuse.
 *
 * In view: the one move the state is about (Edit a draft, Pause a running campaign,
 * Resume a paused one, Call the unreached again once it is over) and Stop for good while
 * it can still call, because a control that stops calls stays visible however seldom it
 * is used (UX-DOCTRINE §3). Behind ⋯: Duplicate always, Delete on a draft. Stop and
 * Delete restate what they do before they act.
 *
 * Resume is the filled button when pressing it is the whole fix (a pause the owner made).
 * A pause with a cause still outstanding keeps Resume quiet and disabled, and the notice
 * under the header carries the fix as its own action.
 */
export function CampaignHeaderActions({
  slug,
  campaignId,
  progress,
  setStatus,
  canWrite,
  refusal,
  onGone,
  onCopied,
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
  setStatus: ReturnType<typeof usePauseCampaign>;
  canWrite: boolean;
  refusal: string | undefined;
  onGone: () => void;
  onCopied: (id: string) => void;
}) {
  const { session, href } = useClientRealm();
  const stop = useStopCampaign(session, campaignId);
  const remove = useDeleteCampaign(session, campaignId);
  const duplicate = useDuplicateCampaign(session, campaignId);
  const [confirming, setConfirming] = useState<Confirming>(null);
  const status = progress.status;
  const finished = status === "completed" || status === "cancelled";
  const reviewOwed = progress.complaint_review_required;
  const held = HELD_PAUSES.includes(progress.pause_reason ?? "");
  const remaining = (progress.contacts.pending ?? 0) + (progress.contacts.dialing ?? 0);

  const more: RowMenuItem[] = [
    {
      id: "duplicate",
      label: duplicate.isPending ? "Duplicating…" : "Duplicate",
      disabled: !canWrite || duplicate.isPending,
      hint: canWrite ? undefined : "Owner only",
      onSelect: () => duplicate.mutate({ with_unreached: false }, { onSuccess: (copy) => onCopied(copy.id) }),
    },
    ...(status === "draft"
      ? [
          {
            id: "delete",
            label: "Delete…",
            tone: "danger" as const,
            disabled: !canWrite,
            onSelect: () => setConfirming("delete"),
          },
        ]
      : []),
  ];

  return (
    <div className="flex w-full flex-col gap-3 sm:w-auto sm:items-end">
      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {status === "draft" && (
          <Link href={href(`/c/${slug}/campaigns/${campaignId}/edit`)} className={SECONDARY_BUTTON}>
            Edit
          </Link>
        )}
        {status === "running" && (
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || setStatus.isPending}
            onClick={() => setStatus.mutate("pause")}
            className={SECONDARY_BUTTON}
          >
            <Pause aria-hidden className="h-3.5 w-3.5" />
            Pause
          </button>
        )}
        {status === "paused" && (
          <button
            type="button"
            title={reviewOwed ? "Confirm you have reviewed the opt-outs first." : refusal}
            disabled={!canWrite || setStatus.isPending || reviewOwed}
            onClick={() => setStatus.mutate("resume")}
            className={held ? SECONDARY_BUTTON : PRIMARY_BUTTON}
          >
            <Play aria-hidden className="h-3.5 w-3.5" />
            Resume
          </button>
        )}
        {finished && (
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || duplicate.isPending}
            onClick={() => duplicate.mutate({ with_unreached: true }, { onSuccess: (copy) => onCopied(copy.id) })}
            className={SECONDARY_BUTTON}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            Call the unreached again
          </button>
        )}
        {(status === "running" || status === "paused" || status === "scheduled") && (
          <button
            type="button"
            title={refusal}
            disabled={!canWrite}
            onClick={() => setConfirming("stop")}
            className={SECONDARY_BUTTON}
          >
            Stop for good…
          </button>
        )}
        <RowMenu label={progress.name} items={more} className="border border-line" />
      </div>
      {duplicate.error ? <ProblemNotice error={duplicate.error} /> : null}
      {confirming && (
        <div role="group" aria-label={confirming === "stop" ? "Stop this campaign" : "Delete this draft"} className={`${NOTICE_BASE} ${NOTICE_BAR.warn} max-w-md text-left`}>
          <p className="font-semibold">
            {confirming === "stop" ? "Stop this campaign for good?" : "Delete this draft?"}
          </p>
          <p className="text-ink-muted">
            {confirming === "stop"
              ? `Nobody else on the list is called${remaining ? ` (${formatCount(remaining)} still waiting)` : ""}. A call already ringing finishes. It can't be restarted; Duplicate makes a new draft from it.`
              : "The draft and its list are removed. If calls or records already name it, it is kept as stopped instead."}
          </p>
          {(stop.error || remove.error) && <ProblemNotice error={stop.error ?? remove.error} />}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              disabled={stop.isPending || remove.isPending}
              onClick={() =>
                confirming === "stop"
                  ? stop.mutate(undefined, { onSuccess: () => setConfirming(null) })
                  : remove.mutate(undefined, { onSuccess: onGone })
              }
              className={DANGER_BUTTON}
            >
              {confirming === "stop" ? "Stop for good" : "Delete draft"}
            </button>
            <button type="button" onClick={() => setConfirming(null)} className={SECONDARY_BUTTON}>
              Keep it
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
