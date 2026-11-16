"use client";

/**
 * START CAMPAIGN, at the top and the bottom of the set-up and on Progress (founder, 15-16 Nov
 * 2026). A campaign starts and stops any time: Start resumes a stopped (paused) one, and
 * launches a draft or a campaign stopped before Stop became a pause, through the same gate.
 *
 * Ready (the launch check passes and someone is on the list): one press launches, the same
 * call the compliance card's "Call N people" makes; the server's compliance gate runs again
 * on that launch whatever this shows (hard rule 5). Not ready: the press goes to the
 * compliance card and says what is left, rather than a greyed button that explains nothing.
 */

import { PhoneOutgoing } from "lucide-react";
import { useState } from "react";

import { ActionButton, type ActionFeedback } from "@/components/arc/feedback";
import { PRIMARY_BUTTON_SM } from "@/components/ui";
import type { useCampaignProgress, useLaunchCheck } from "@/lib/api/campaigns";

/** A pause whose cause must be cleared first; the notice above the page says how. */
const HELD_PAUSES = ["complaint_spike", "out_of_credit", "spend_cap"];

/** The compliance card's element id, so Start can take the owner to what is left. */
export function complianceCardId(campaignId: string): string {
  return `compliance-${campaignId}`;
}

export function StartCampaign({
  campaignId,
  status,
  check,
  progress,
  launch,
  resume,
  canWrite,
  refusal,
}: {
  campaignId: string;
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  progress: ReturnType<typeof useCampaignProgress>;
  launch: ActionFeedback<void>;
  /** Resumes a stopped (paused) campaign. */
  resume: ActionFeedback<"pause" | "resume">;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const [told, setTold] = useState(false);
  if (status === "running") {
    const why = "It is calling now. Use Stop campaign to stop it.";
    return (
      <button type="button" className={PRIMARY_BUTTON_SM} disabled title={why} aria-label={`Start campaign: ${why}`}>
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </button>
    );
  }
  if (status === "paused") {
    const data = progress.data;
    const held =
      data?.complaint_review_required === true
        ? "Review the opt-outs first."
        : HELD_PAUSES.includes(data?.pause_reason ?? "")
          ? "Fix the reason shown above first."
          : undefined;
    return (
      <ActionButton
        variant="primary-sm"
        title={held ?? refusal}
        disabled={!canWrite || Boolean(held)}
        status={resume.status}
        pendingLabel="Starting"
        successLabel="Started"
        onClick={() => resume.run("resume")}
      >
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </ActionButton>
    );
  }
  const total = progress.data?.total ?? 0;
  const ready = check.data?.ready === true && total > 0;

  if (ready) {
    return (
      <ActionButton
        variant="primary-sm"
        title={refusal}
        disabled={!canWrite || check.isRefetching}
        status={launch.status}
        pendingLabel="Starting"
        successLabel="Started"
        onClick={() => launch.run()}
      >
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </ActionButton>
    );
  }

  const left = total === 0 ? "Add the people to call and answer the compliance checks first." : "Answer the compliance checks first.";
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      <button
        type="button"
        className={PRIMARY_BUTTON_SM}
        title={refusal}
        disabled={!canWrite}
        onClick={() => {
          setTold(true);
          document
            .getElementById(complianceCardId(campaignId))
            ?.scrollIntoView?.({ block: "start", behavior: "smooth" });
        }}
      >
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </button>
      {told && (
        <span role="status" className="text-meta text-warn">
          {left}
        </span>
      )}
    </span>
  );
}
