"use client";

import { ArrowRight } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, formatCount } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { useMoveFollowUp, type FollowUpOut } from "@/lib/api/followUps";

import { isFollowUpConflict, useConflictToast } from "./conflict";

/**
 * "Publish", shown only while the draft differs from what runs. The problems the server
 * found are buttons that open the step they are about; one with no step is a line of its
 * own. A refused publish (422) refetches, so the list is the server's latest.
 */
export function PublishPanel({
  followUp,
  onOpenStep,
}: {
  followUp: FollowUpOut;
  onOpenStep: (stepId: string) => void;
}) {
  const { session } = useClientRealm();
  const move = useMoveFollowUp(session, followUp.id);
  const conflict = useConflictToast();
  const feedback = useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: "Published",
    successDescription: "Leads that start now get these steps. Leads already in it keep theirs.",
  });
  const problems = followUp.problems;
  const refused = move.error && !isFollowUpConflict(move.error) && !(problems.length && isInvalid(move.error));

  return (
    <section
      aria-labelledby="publish-heading"
      className="space-y-3 rounded-lg border-2 border-brand p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 id="publish-heading" className="text-heading text-ink">
            {followUp.status === "draft" ? "Not published yet" : "Changes not published"}
          </h2>
          <p className="text-body text-ink-muted">
            {problems.length
              ? `${formatCount(problems.length)} to fix first`
              : "Leads keep the old steps until you publish."}
          </p>
        </div>
        <ActionButton
          variant="primary-lg"
          status={feedback.status}
          pendingLabel="Publishing…"
          successLabel="Published"
          onClick={() =>
            move.mutate(
              { move: "publish", expectedUpdatedAt: followUp.updated_at },
              { onError: (error) => conflict(error) },
            )
          }
        >
          Publish
        </ActionButton>
      </div>

      {problems.length > 0 && (
        <ul aria-label="To fix before publishing" className="space-y-1.5">
          {problems.map((problem, index) => (
            <li key={`${problem.step_id ?? "all"}-${problem.code}-${index}`}>
              {problem.step_id ? (
                <button
                  type="button"
                  onClick={() => onOpenStep(problem.step_id as string)}
                  className="press inline-flex w-full items-start gap-2 rounded-md border-l-2 border-chart-warn bg-surface px-3 py-2 text-left text-body text-ink hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                >
                  <span className="min-w-0 flex-1">{problem.message}</span>
                  <span className="inline-flex shrink-0 items-center gap-1 font-medium text-brand-strong dark:text-brand-bright">
                    Open step
                    <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                  </span>
                </button>
              ) : (
                <p className="border-l-2 border-chart-warn px-3 py-2 text-body text-ink">{problem.message}</p>
              )}
            </li>
          ))}
        </ul>
      )}

      {refused ? <ProblemNotice error={move.error} /> : null}
    </section>
  );
}

/** The 422 whose problems are now listed above: the list says it, so no second notice. */
function isInvalid(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === "follow_up_invalid";
}
