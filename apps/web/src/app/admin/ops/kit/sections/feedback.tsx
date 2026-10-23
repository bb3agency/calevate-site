"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ActionButton, useActionFeedback, useAsyncAction } from "@/components/arc/feedback";
import { useToast } from "@/components/arc/toast";
import { ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";

import { KitDemo, KitGrid, KitSection } from "../kitLayout";

/** A stand-in for a real write: settles after a short wait, or fails with a real problem shape. */
function pretendWrite(fail: boolean): Promise<{ name: string }> {
  return new Promise((resolve, reject) =>
    window.setTimeout(() => {
      if (fail) {
        reject(
          new ApiProblem(409, {
            type: "https://calevate.tech/problems/agent_name_taken",
            title: "That name is taken",
            detail: "Another agent on this account is already called Reception.",
            retryable: false,
          }),
        );
      } else {
        resolve({ name: "Reception" });
      }
    }, 900),
  );
}

function LiveMutation() {
  const [fail, setFail] = useState(false);
  const [inline, setInline] = useState(false);
  const rename = useMutation({ mutationFn: (next: { fail: boolean }) => pretendWrite(next.fail) });
  const renameFeedback = useActionFeedback(rename, {
    errorTitle: "Could not rename the agent",
    errorDisplay: inline ? "inline" : "toast",
    successToast: "Agent renamed",
    successDescription: (data) => `It is now called ${data.name}.`,
    undo: () => undefined,
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-meta text-ink-muted">
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={fail} onChange={(e) => setFail(e.target.checked)} className="h-4 w-4 accent-(--brand)" />
          Fail the next save
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={inline} onChange={(e) => setInline(e.target.checked)} className="h-4 w-4 accent-(--brand)" />
          Show the failure inline
        </label>
      </div>
      <ActionButton status={renameFeedback.status} successLabel="Renamed" onClick={() => renameFeedback.run({ fail })}>
        Rename agent
      </ActionButton>
      {inline && renameFeedback.error != null ? <ProblemNotice error={renameFeedback.error} /> : null}
    </div>
  );
}

function CopyDemo() {
  const copy = useAsyncAction(() => navigator.clipboard.writeText("+91 98765 43210"), {
    errorTitle: "Could not copy the number",
  });
  return (
    <ActionButton variant="secondary" status={copy.status} successLabel="Copied" onClick={() => copy.run()}>
      Copy number
    </ActionButton>
  );
}

function ToastDemos() {
  const { toast, update } = useToast();
  return (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        onClick={() =>
          toast({
            kind: "success",
            title: "Lead moved to Won",
            description: "Priya Sharma, from the Diwali campaign.",
            action: { label: "Undo", onClick: () => undefined },
          })
        }
      >
        Success with Undo
      </button>
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => toast({ kind: "info", title: "Export started", description: "We will email the file when it is ready." })}>
        Info
      </button>
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => toast({ kind: "warning", title: "Credit is running low", description: "About 40 minutes of calls left." })}>
        Warning
      </button>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        onClick={() =>
          toast({
            kind: "error",
            title: "Could not start the campaign",
            description: "Calls can only be placed between 9 am and 9 pm IST.",
            code: "outside_calling_hours",
          })
        }
      >
        Error with code
      </button>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        onClick={() => {
          const id = toast({ kind: "loading", title: "Placing a test call" });
          window.setTimeout(() => update(id, { kind: "success", title: "Test call connected", description: "Pick up on +91 98765 43210." }), 1500);
        }}
      >
        Loading, then result
      </button>
    </div>
  );
}

export function FeedbackSection() {
  return (
    <KitSection
      id="feedback"
      title="Feedback"
      lead="Every action shows pending, then success or failure, on the control that was pressed. Failures also reach the toast stack with the server's sentence and code."
    >
      <KitGrid>
        <KitDemo label="ActionButton · four states">
          <div className="flex flex-wrap gap-2">
            <ActionButton>Save changes</ActionButton>
            <ActionButton status="pending" pendingLabel="Saving">
              Save changes
            </ActionButton>
            <ActionButton status="success" successLabel="Saved">
              Save changes
            </ActionButton>
            <ActionButton status="error">Save changes</ActionButton>
          </div>
        </KitDemo>
        <KitDemo label="ActionButton · variants">
          <div className="flex flex-wrap items-center gap-2">
            <ActionButton variant="primary-lg">Start campaign</ActionButton>
            <ActionButton variant="secondary">Pause</ActionButton>
            <ActionButton variant="secondary-sm">Retry</ActionButton>
            <ActionButton variant="primary-sm">Call back</ActionButton>
            <ActionButton variant="danger">Remove number</ActionButton>
            <ActionButton disabled>Publish</ActionButton>
          </div>
        </KitDemo>
        <KitDemo label="useActionFeedback · a live mutation" note="Turn on the failure to see the error face and the toast; Undo appears on success.">
          <LiveMutation />
        </KitDemo>
        <KitDemo label="useAsyncAction · not a mutation">
          <CopyDemo />
        </KitDemo>
        <KitDemo label="Toast stack" wide note="Bottom-right on a desktop, top on a phone. Errors stay until closed; the rest leave after five seconds. Hover or focus pauses them; swipe or Escape dismisses.">
          <ToastDemos />
        </KitDemo>
      </KitGrid>
    </KitSection>
  );
}
