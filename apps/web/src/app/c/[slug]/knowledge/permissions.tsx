"use client";

import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
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
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2">
        <div className="text-sm">
          <span className="font-medium">Let staff add knowledge</span>
          <span className="block text-ink-muted">
            {on
              ? "Team members with the staff role can add knowledge for review. They still cannot approve it."
              : "Only owners can add knowledge on this account. Everything added is reviewed before it goes live either way."}
          </span>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={on}
            disabled={!write.allowed || setCuration.isPending}
            onChange={(e) => setCuration.mutate(e.target.checked)}
          />
          <span>{on ? "On" : "Off"}</span>
        </label>
      </div>
      <RestrictionNote reason={write.reason} />
      {setCuration.error && <ProblemNotice error={setCuration.error} />}
    </div>
  );
}

/**
 * WHAT HAPPENS TO WHAT *YOU* ADD — the difference between an owner and a colleague, said
 * before they spend twenty minutes writing something.
 *
 * The rule is the founder's and it is `uploads.may_self_approve`: an OWNER's own
 * submission does not wait for us, and a staff member's goes for review however the
 * curation switch is set (the switch grants submission, explicitly not approval —
 * `apps/api/kb/curation.py`). Neither half is guessable from the screen, and both are
 * surprising in the direction that wastes somebody's afternoon: a staff member watching
 * for their change to go live, or an owner waiting for a review that will never happen.
 *
 * ONE EXCEPTION IS STATED HERE RATHER THAN DISCOVERED: a photograph is never approved
 * automatically, whoever sent it, because a model read it and a person has to agree
 * (`apps/workers/document_ocr.py`).
 *
 * A SENTENCE AND NEVER A CONTROL, so an unanswered `/v1/me` renders nothing at all rather
 * than a claim about this account's permissions.
 */
export function SubmissionConsequence() {
  const session = useClientSession();
  const me = useMe(session);
  if (!me.data?.role) return null;
  const owner = me.data.role === "owner";
  return (
    <p className="rounded-lg border border-line bg-surface px-3 py-2 text-xs text-ink-muted">
      <span>
        {owner
          ? "What you add goes to your agent as soon as we have finished reading it — you do not wait for us. Anything a colleague adds is reviewed first, and so is anything read off a photo, including yours."
          : "What you add is reviewed before your agent starts using it, so it will not go live the moment you send it. Your account owner and your account manager can see it in the meantime."}
      </span>
    </p>
  );
}
