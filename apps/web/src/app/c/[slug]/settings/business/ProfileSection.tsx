"use client";

import { Section } from "@/components/console/section";

import type { ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  draftFromProfile,
  fieldMessage,
  toPatch,
  useSaveBusinessProfile,
  type ProfileDraft,
  type StepCopy,
  type StepId,
} from "@/lib/api/businessProfile";
import { useClientSession } from "@/lib/api/session";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

/** One topic of the profile, saved on its own. Save is offered only when this topic
 *  differs from what is stored. */
export function ProfileSection({
  step,
  draft,
  saved,
  canWrite,
  onDraft,
  problem,
  render,
}: {
  step: StepCopy;
  draft: ProfileDraft;
  saved: ProfileDraft;
  canWrite: boolean;
  onDraft: (next: ProfileDraft) => void;
  problem: string | null;
  render: (errorAt: (path: string) => string | undefined) => ReactNode;
}) {
  const session = useClientSession();
  const save = useSaveBusinessProfile(session);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const dirty =
    JSON.stringify(toPatch(draft, step.id)) !== JSON.stringify(toPatch(saved, step.id));
  useUnsavedGuard(dirty);
  const fields = save.error instanceof ApiProblem ? save.error.fields : undefined;

  return (
    <Section title={step.short} info={step.hint}>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!dirty || problem) return;
          save.mutate(toPatch(draft, step.id), {
            // The stored answer comes back tidied (blank rows dropped, ids assigned); take
            // this topic from it so the form shows exactly what the agents now say.
            onSuccess: (profile) => {
              const key = sectionKey(step.id);
              onDraft({ ...draft, [key]: draftFromProfile(profile)[key] });
            },
          });
        }}
        className="space-y-4"
      >
        <fieldset disabled={!canWrite || save.isPending} className="min-w-0">
          {render((path) => fieldMessage(fields, path))}
        </fieldset>
        {problem && (
          <p role="alert" className="text-meta font-medium text-danger">
            {problem}
          </p>
        )}
        {save.error && <ProblemNotice error={save.error} />}
        {canWrite && (
          <div className="flex flex-wrap items-center gap-3">
            {/* Stays enabled while it shows "Saved", so the tick is not greyed out; a press
                with nothing changed is ignored by the submit handler. */}
            <ActionButton
              type="submit"
              status={saveFeedback.status}
              disabled={(!dirty && saveFeedback.status !== "success") || Boolean(problem)}
              successLabel="Saved"
            >
              Save
            </ActionButton>
            {save.isSuccess && !dirty && (
              <span className="text-meta text-ink-muted">Your agents use this now.</span>
            )}
          </div>
        )}
      </form>
    </Section>
  );
}

function sectionKey(step: StepId): keyof ProfileDraft {
  switch (step) {
    case "hours":
      return "business_hours";
    case "booking":
      return "booking_rules";
    case "contacts":
      return "escalation_contacts";
    default:
      return step;
  }
}
