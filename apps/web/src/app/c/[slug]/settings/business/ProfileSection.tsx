"use client";

import type { ReactNode } from "react";
import { Check } from "lucide-react";

import { Card, PRIMARY_BUTTON, ProblemNotice } from "@/components/ui";
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
  const dirty =
    JSON.stringify(toPatch(draft, step.id)) !== JSON.stringify(toPatch(saved, step.id));
  useUnsavedGuard(dirty);
  const fields = save.error instanceof ApiProblem ? save.error.fields : undefined;

  return (
    <Card density="compact" title={step.short} info={step.hint}>
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
          <p role="alert" className="text-[13px] font-medium text-danger">
            {problem}
          </p>
        )}
        {save.error && <ProblemNotice error={save.error} />}
        {canWrite && (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={!dirty || save.isPending || Boolean(problem)}
              aria-busy={save.isPending || undefined}
              className={PRIMARY_BUTTON}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            {save.isSuccess && !dirty && (
              <span
                role="status"
                className="inline-flex items-center gap-1 text-[13px] text-ink-muted"
              >
                <Check aria-hidden className="h-3.5 w-3.5" />
                Saved. Your agents use this now.
              </span>
            )}
          </div>
        )}
      </form>
    </Card>
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
