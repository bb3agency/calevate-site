"use client";

/**
 * CALL THE UNANSWERED AGAIN (D-992 item 8): a new draft of the people the campaign never
 * reached, already set with what it learned: the best hours when they are measured, retries
 * at other times of day, and the stronger opening when the test named one
 * (`campaigns/controls.duplicate_campaign`). A stopped campaign gives only the people whose
 * tries ran out; the rest are still its own and are called when it is started again.
 */

import { useRouter } from "next/navigation";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { useDuplicateCampaign } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, MoveError } from "./ImproveCard";

/** Why "Make a draft for the unanswered" is held, or undefined when it may be pressed. */
export function callAgainHeld(status: string | null | undefined): string | undefined {
  if (status == null || ["completed", "cancelled", "paused"].includes(status)) return undefined;
  if (status === "running") return "It is still calling. Stop it, or let it finish, first.";
  return "This opens once the campaign has run.";
}

/** What the draft takes from a campaign in this status. */
export function callAgainTakes(status: string | null | undefined): string {
  return status === "paused"
    ? "The people whose tries ran out. The rest stay here and are called when you start it again."
    : "Everyone it never reached.";
}

export function CallAgainCard({
  slug,
  campaignId,
  canWrite,
  refusal,
  status,
}: {
  slug: string;
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
  status?: string | null;
}) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const duplicate = useDuplicateCampaign(session, campaignId);
  useActionFeedback(duplicate, { errorDisplay: "inline" });
  const held = callAgainHeld(status);
  return (
    <ImproveCard
      title="Call the unanswered again"
      hint={callAgainTakes(status)}
      info="The new draft starts with the best hours once they are known, retries at other times of day, and the stronger opening if the test found one. You start it when you are ready."
    >
      <ActionButton
        variant="primary-sm"
        status={duplicate.isPending ? "pending" : "idle"}
        pendingLabel="Making it…"
        disabled={!canWrite || held !== undefined}
        title={refusal}
        onClick={() =>
          duplicate.mutate(
            { with_unreached: true },
            { onSuccess: (made) => router.push(href(`/c/${slug}/campaigns/${made.id}`)) },
          )
        }
      >
        Make a draft for the unanswered
      </ActionButton>
      {held && canWrite && <p className="mt-2 text-meta text-ink-muted">{held}</p>}
      <MoveError error={duplicate.error} fallback="The draft was not made" />
    </ImproveCard>
  );
}
