"use client";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NoticeBox, ProblemNotice } from "@/components/ui";
import { useSetUpTrialLine, type TrialLine } from "@/lib/api/opsTrialNumber";

/**
 * What somebody who rings the shared trial number back hears (D-742). The number's own line
 * is one agent in our developer workspace that never answers and has ThinnestAI's phone
 * provider read our sentence; it is nobody's client agent. The daily number sweep keeps it in
 * step; "Set it up now" does the same at once.
 */

const STATE_WORDS: Record<TrialLine["state"], string> = {
  ready: "Callers who ring back hear the message below.",
  no_number: "No shared trial number is set.",
  no_agent: "Not set up yet: callers who ring back hear ThinnestAI's standard sentence.",
  not_attached:
    "The message is ready but the number does not use it yet: callers hear the standard sentence.",
  drifted: "Someone changed the line in ThinnestAI's console; set it up again.",
  unavailable: "ThinnestAI could not be read just now.",
};

export function TrialLinePanel({ line }: { line: TrialLine }) {
  const setUp = useSetUpTrialLine();
  // The button leaves once the line is ready, so the outcome is also said in a toast.
  const setUpFeedback = useActionFeedback(setUp, {
    errorDisplay: "inline",
    successToast: "Trial line set up",
  });
  const shown = setUp.data ?? line;
  return (
    <NoticeBox
      tone={shown.state === "ready" ? "neutral" : "warn"}
      title="When someone rings this number back"
      action={
        shown.state !== "ready" ? (
          <ActionButton
            variant="secondary-sm"
            status={setUpFeedback.status}
            pendingLabel="Setting it up…"
            successLabel="Set up"
            onClick={() => setUpFeedback.run()}
          >
            Set it up now
          </ActionButton>
        ) : undefined
      }
    >
      <p className="mt-1">{STATE_WORDS[shown.state]}</p>
      <p className="mt-1 text-ink-muted">&ldquo;{shown.message ?? shown.wanted_message}&rdquo;</p>
      {shown.message_note && <p className="mt-1 text-ink-muted">{shown.message_note}</p>}
      {setUp.error && <ProblemNotice error={setUp.error} />}
    </NoticeBox>
  );
}
