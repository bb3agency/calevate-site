"use client";

import { useState, type ComponentType } from "react";
import {
  Bell,
  Clock,
  CornerDownRight,
  Flag,
  GitBranch,
  MessageCircle,
  Phone,
  Tag,
  UserPlus,
  Zap,
} from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { RowMenu, type MenuItem } from "@/components/arc/menu";
import { ConfirmDialog } from "@/components/confirmDialog";
import { EmptyState } from "@/components/console/emptyState";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { ProblemNotice } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import {
  useEditFollowUp,
  type FollowUpOut,
  type FollowUpStep,
  type FollowUpStepKind,
} from "@/lib/api/followUps";

import { editsFor, stepLines } from "../followUpCopy";
import { isFollowUpConflict, useConflictToast } from "./conflict";
import { StepEditDialog, type EditMode } from "./StepEditDialog";

const KIND_ICON: Record<FollowUpStepKind, ComponentType<{ className?: string }>> = {
  call: Phone,
  decide: GitBranch,
  wait: Clock,
  whatsapp: MessageCircle,
  assign: UserPlus,
  set_status: Tag,
  tell_team: Bell,
  action: Zap,
  end: Flag,
};

/** The DOM id of a step's row, so a publish problem can open it. */
export function stepAnchor(stepId: string): string {
  return `follow-up-step-${stepId}`;
}

/** Scroll a step into view and move focus to it, for a reader who pressed its problem. */
export function focusStep(stepId: string): void {
  const row = document.getElementById(stepAnchor(stepId));
  if (!row) return;
  row.scrollIntoView?.({ block: "center", behavior: "smooth" });
  row.focus({ preventScroll: true });
}

/** Indentation per branch level. Bounded so a deep tree still fits a phone. */
const INDENT = ["", "pl-5 sm:pl-8", "pl-10 sm:pl-16", "pl-14 sm:pl-24"];

/**
 * The steps, top to bottom, with each `decide`'s branches indented under their outcome.
 * Each step is one line (the server's `summary`) and a ⋯ menu of the small edits its kind
 * allows; anything else is Pip's job.
 */
export function StepsTab({ followUp, canEdit }: { followUp: FollowUpOut; canEdit: boolean }) {
  const { session } = useClientRealm();
  const edit = useEditFollowUp(session, followUp.id);
  const conflict = useConflictToast();
  const feedback = useActionFeedback(edit, {
    errorDisplay: "inline",
    successToast: (_data, body) =>
      body.step_edits?.some((stepEdit) => stepEdit.remove) ? "Step removed" : "Saved to the draft",
    successDescription: "Publish to use it.",
  });
  const [editing, setEditing] = useState<{ step: FollowUpStep; mode: EditMode } | null>(null);
  const [removing, setRemoving] = useState<FollowUpStep | null>(null);

  if (followUp.steps.length === 0) {
    return <EmptyState message="No steps yet." hint="Ask Pip to add them." align="start" />;
  }

  const problemsByStep = new Map<string, string[]>();
  for (const problem of followUp.problems) {
    if (!problem.step_id) continue;
    problemsByStep.set(problem.step_id, [...(problemsByStep.get(problem.step_id) ?? []), problem.message]);
  }

  const menuFor = (step: FollowUpStep): MenuItem[] => {
    const can = editsFor(step);
    const items: MenuItem[] = [];
    if (can.wait) {
      items.push({
        id: "wait",
        label: step.kind === "call" ? "Change the wait before calling" : "Change the wait",
        onSelect: () => setEditing({ step, mode: "wait" }),
      });
    }
    if (can.template) {
      items.push({ id: "template", label: "Change the message", onSelect: () => setEditing({ step, mode: "template" }) });
    }
    if (can.agent) {
      items.push({ id: "agent", label: "Change who calls", onSelect: () => setEditing({ step, mode: "agent" }) });
    }
    items.push({
      id: "remove",
      label: "Remove this step",
      tone: "danger",
      separated: items.length > 0,
      onSelect: () => {
        edit.reset();
        setRemoving(step);
      },
    });
    return items;
  };

  return (
    <>
      <ol aria-label="Steps" className="space-y-1">
        {stepLines(followUp.steps).map((line, index) => {
          const indent = INDENT[Math.min(line.depth, INDENT.length - 1)];
          if (line.type === "end") {
            return (
              <li key={`end-${index}`} className={indent}>
                <BranchLabel text={line.branch} />
                <p className="border-l border-line py-1.5 pl-3 text-meta text-ink-muted">Stops here</p>
              </li>
            );
          }
          if (line.type === "goto") {
            return (
              <li key={`goto-${index}`} className={indent}>
                {line.branch && <BranchLabel text={line.branch} />}
                <p className="flex items-center gap-1 border-l border-line py-1 pl-3 text-meta text-ink-muted">
                  <CornerDownRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
                  Then:
                  <button type="button" className={TEXT_ACTION_SM} onClick={() => focusStep(line.step.id)}>
                    {line.step.summary}
                  </button>
                </p>
              </li>
            );
          }
          const { step } = line;
          const Icon = KIND_ICON[step.kind] ?? Flag;
          const problems = problemsByStep.get(step.id) ?? [];
          return (
            <li key={step.id} className={indent}>
              {line.branch && <BranchLabel text={line.branch} />}
              <div
                id={stepAnchor(step.id)}
                tabIndex={-1}
                className={`flex items-start gap-3 rounded-md border-l-2 px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-brand ${problems.length ? "border-chart-warn" : "border-line"}`}
              >
                <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                <div className="min-w-0 flex-1">
                  <p className="text-body text-ink [overflow-wrap:anywhere]">{step.summary}</p>
                  {problems.map((message) => (
                    <p key={message} className="text-meta text-ink-muted">
                      {message}
                    </p>
                  ))}
                </div>
                {canEdit && <RowMenu label={step.summary} items={menuFor(step)} />}
              </div>
            </li>
          );
        })}
      </ol>

      {editing && (
        <StepEditDialog
          step={editing.step}
          mode={editing.mode}
          pending={edit.isPending}
          error={edit.error && !isFollowUpConflict(edit.error) ? edit.error : null}
          onClose={() => {
            edit.reset();
            setEditing(null);
          }}
          onSave={(stepEdit) =>
            edit.mutate(
              { step_edits: [stepEdit] },
              {
                onSuccess: () => setEditing(null),
                onError: (error) => {
                  if (conflict(error)) setEditing(null);
                },
              },
            )
          }
        />
      )}

      {removing && (
        <ConfirmDialog
          title="Remove this step?"
          confirmLabel="Remove it"
          pendingLabel="Removing…"
          cancelLabel="Keep it"
          status={feedback.status}
          error={edit.error && !isFollowUpConflict(edit.error) ? edit.error : null}
          onCancel={() => {
            edit.reset();
            setRemoving(null);
          }}
          onConfirm={() => {
            const step = removing;
            // Optimistic: the row goes at once and comes back if the server refuses.
            setRemoving(null);
            edit.mutate({ step_edits: [{ step_id: step.id, remove: true }] }, { onError: (error) => conflict(error) });
          }}
        >
          <p className="font-medium text-ink">{removing.summary}</p>
          <p>Only the draft changes. Publish to use it.</p>
        </ConfirmDialog>
      )}
      {edit.error && !editing && !removing && !isFollowUpConflict(edit.error) ? (
        <div className="mt-3">
          <ProblemNotice error={edit.error} />
        </div>
      ) : null}
    </>
  );
}

function BranchLabel({ text }: { text: string }) {
  return (
    <p className="mb-0.5 pl-3 text-meta font-medium text-ink-muted">
      If {text.toLowerCase() === "anything else" ? "anything else" : `“${text}”`}
    </p>
  );
}
