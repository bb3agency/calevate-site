"use client";

import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { useMe, type WriteAccess } from "@/lib/api/hooks";
import { useSetStaffCuration, useStaffCuration } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";


/**
 * WHO ON THIS TEAM MAY ADD KNOWLEDGE — the owner's switch.
 *
 * Rendered where the capability it governs lives rather than buried in account settings,
 * so the person reading "only owners can add knowledge here" is one control away from
 * changing it. Shown to everyone (`org:read`) and writable only by an owner
 * (`org:manage`), which also means a D-22 view-as operator sees it read-only: flipping a
 * permission switch is itself a mutation.
 *
 * **ITS OWN COMPONENT SO THE UNREAD STATES CAN BE THEIR OWN RETURNS.** Written inline it
 * read `curation.data?.staff_may_curate_knowledge ?? false`, and `surfaceStatesGuard`
 * failed it for the right reason: that fallback renders "Off" — a definite claim about
 * this account's permissions — while the request is still in flight or after it has
 * failed. "Off" and "we could not find out" are different answers, and only one of them
 * was earned. After the two early returns TypeScript narrows `data`, so the fallback is
 * gone rather than hidden.
 */
export function StaffCurationSwitch({ write }: { write: WriteAccess }) {
  const session = useClientSession();
  const curation = useStaffCuration(session);
  const setCuration = useSetStaffCuration(session);

  if (curation.isPending) return <Skeleton rows={1} label="Checking who may add knowledge…" />;
  if (curation.isError) {
    return <ProblemNotice error={curation.error} onRetry={() => curation.refetch()} />;
  }

  const on = curation.data.staff_may_curate_knowledge;
  return (
    <div className="space-y-2">
      <ToggleSwitch
        label="Let staff add knowledge"
        hint={
          on
            ? "Team members with the staff role can add knowledge. What they add goes to your agent without review, the same as yours."
            : "Only owners can add knowledge on this account."
        }
        checked={on}
        disabled={!write.allowed || setCuration.isPending}
        onChange={(next) => setCuration.mutate(next)}
      />
      <RestrictionNote reason={write.reason} />
      {setCuration.error && <ProblemNotice error={setCuration.error} />}
    </div>
  );
}

/**
 * WHAT HAPPENS TO WHAT *YOU* ADD — the difference between an owner and a colleague, said
 * before they spend twenty minutes writing something.
 *
 * The rule is the founder's (D-658, `kb/curation.goes_live_without_review`): whatever the
 * account's own people add — owner, or staff the owner let in — goes to the agent once it
 * has been read, with nobody approving it, photographs included. Said before somebody
 * spends twenty minutes writing, so nobody waits for a review that will never happen.
 *
 * A SENTENCE AND NEVER A CONTROL, so an unanswered `/v1/me` renders nothing at all rather
 * than a claim about this account's permissions.
 */
export function SubmissionConsequence() {
  const session = useClientSession();
  const me = useMe(session);
  if (!me.data?.role) return null;
  return (
    <p className="text-xs text-ink-muted">
      <span>
        What you add goes to your agent as soon as we have finished reading it — nobody
        approves it first, and you do not wait for us.
      </span>
    </p>
  );
}
