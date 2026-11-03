"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TextShimmer } from "@/components/arc/text-shimmer";
import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { useRewriteStarterScript, type CallScript } from "@/lib/api/script";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import type { ScriptWriting } from "./scriptWriting";
import { SetupStep, SkipButton } from "./setupStep";

/**
 * STEP 3: THE SCRIPT WRITTEN FOR THIS BUSINESS. It is written after creation (`scriptWriting`),
 * so the step waits for it, then reads it back for review: the main task, the steps by name
 * and the opening line. Editing is the Script tab's; nothing here saves a script, because an
 * owner edit would stop the written one being applied to the untouched draft.
 *
 * The wait is capped: past `WAIT_CAP_MS` the owner may go on, and the script still lands on
 * the agent when it is done.
 */

/** The worker spends up to three model budgets; a minute covers the usual write. */
const WAIT_CAP_MS = 60_000;

/** What the writer works through, revealed in turn while it runs. Never ticked: the
 *  screen cannot see which part is done, only that the whole is not. */
const WRITING_PARTS = [
  "Reading about your business",
  "Planning the call, step by step",
  "Writing how it opens a call",
  "Checking every line it will say",
] as const;

/** The write failed: ask again (it is the same request creation made), or write it oneself. */
function ScriptFailed({
  agentId,
  note,
  scriptTab,
  onBack,
  onSkip,
}: {
  agentId: string;
  note: string | null;
  scriptTab: string;
  onBack: () => void;
  onSkip: () => void;
}) {
  const again = useRewriteStarterScript(useClientSession(), agentId);
  const feedback = useActionFeedback(again, { errorDisplay: "inline" });
  return (
    <SetupStep
      title="We couldn't write the script"
      hint={note ?? "Try again, or write it on the Script tab."}
      onBack={onBack}
      actions={
        <>
          <ActionButton status={feedback.status} pendingLabel="Asking…" onClick={() => again.mutate()}>
            Try again
          </ActionButton>
          <Link href={scriptTab} className={SECONDARY_BUTTON}>
            Write it yourself
          </Link>
          <SkipButton onSkip={onSkip} />
        </>
      }
    >
      {again.error ? <ProblemNotice error={again.error} /> : null}
    </SetupStep>
  );
}

export function ScriptStep({
  slug,
  agentId,
  writing,
  onNext,
  onSkip,
  onBack,
}: {
  slug: string;
  agentId: string;
  writing: ScriptWriting;
  onNext: () => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  const { href } = useClientRealm();
  const scriptTab = href(`/c/${slug}/agents/${agentId}?section=script&from=starter`);
  const [late, setLate] = useState(false);
  const waiting = writing.phase === "writing";
  useEffect(() => {
    if (!waiting) return;
    const timer = setTimeout(() => setLate(true), WAIT_CAP_MS);
    return () => clearTimeout(timer);
  }, [waiting]);

  switch (writing.phase) {
    case "writing":
      return (
        <SetupStep
          title="Writing your script"
          hint="Written for your business. Usually under a minute."
          onBack={onBack}
          actions={
            late ? (
              <>
                <button type="button" onClick={onSkip} className={PRIMARY_BUTTON}>
                  Continue anyway
                </button>
                <span className="text-meta text-ink-muted">It lands on the agent when done.</span>
              </>
            ) : (
              <SkipButton onSkip={onSkip} />
            )
          }
        >
          <TextShimmer className="text-body font-medium">Writing the script for your business…</TextShimmer>
          <ul className="space-y-2" aria-hidden>
            {WRITING_PARTS.map((part, index) => (
              <li
                key={part}
                className="stage-in flex items-center gap-2.5 text-body text-ink-muted"
                style={{ animationDelay: `${index * 1200}ms` }}
              >
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-strong/60" />
                {part}
              </li>
            ))}
          </ul>
          {late ? <p className="text-body text-ink">This is taking longer than usual.</p> : null}
        </SetupStep>
      );
    case "done":
      return (
        <SetupStep
          title="Your script"
          hint="Written for your business. Check it reads right."
          onBack={onBack}
          actions={
            <>
              <button type="button" onClick={onNext} className={PRIMARY_BUTTON}>
                Looks good, continue
              </button>
              <Link href={scriptTab} className={SECONDARY_BUTTON}>
                Edit it
              </Link>
              <SkipButton onSkip={onSkip} />
            </>
          }
        >
          <ScriptSummary script={writing.script} />
        </SetupStep>
      );
    case "ready":
      return (
        <SetupStep
          title="Your script is written"
          hint="It waits on the Script tab until you use it."
          onBack={onBack}
          actions={
            <>
              <Link href={scriptTab} className={PRIMARY_BUTTON}>
                Review and use it
              </Link>
              <SkipButton onSkip={onSkip} />
            </>
          }
        >
          <ScriptSummary script={writing.script} />
        </SetupStep>
      );
    case "failed":
      return <ScriptFailed agentId={agentId} note={writing.note} scriptTab={scriptTab} onBack={onBack} onSkip={onSkip} />;
    case "unread":
      return (
        <SetupStep title="Your script" onBack={onBack} actions={<SkipButton onSkip={onSkip} />}>
          <ProblemNotice error={writing.error} onRetry={writing.retry} />
        </SetupStep>
      );
  }
}

/** The script as an owner reads it: what it is for, its steps, and its first words. */
function ScriptSummary({ script }: { script: CallScript }) {
  const steps =
    script.stages.length > 0
      ? script.stages.map((stage) => stage.name)
      : script.steps.map((step) => step.instruction);
  const goal = script.goal.trim();
  const opening = script.opening_line.trim();
  if (!goal && steps.length === 0 && !opening) {
    return <p className="text-body text-ink-muted">Nothing written yet. Open the Script tab.</p>;
  }
  return (
    <dl className="settings-enter divide-y divide-line border-y border-line">
      {goal ? (
        <SummaryRow label="Main task">
          <p>{goal}</p>
        </SummaryRow>
      ) : null}
      {steps.length > 0 ? (
        <SummaryRow label="Steps">
          <ol className="list-decimal space-y-1 pl-5 marker:text-ink-muted">
            {steps.map((step, index) => (
              <li key={`${index}-${step}`}>{step}</li>
            ))}
          </ol>
        </SummaryRow>
      ) : null}
      {opening ? (
        <SummaryRow label="Opening line">
          <p>“{opening}”</p>
        </SummaryRow>
      ) : null}
    </dl>
  );
}

function SummaryRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 py-3 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
      <dt className="text-meta font-medium text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words text-body text-ink">{children}</dd>
    </div>
  );
}
