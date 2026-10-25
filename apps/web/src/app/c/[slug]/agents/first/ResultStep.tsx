"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { ArrowRight, Check, FileText, Link2, PencilLine, PhoneCall } from "lucide-react";

import type { CallAudioPlayerHandle } from "@/components/callAudioPlayer";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { Disclosure, PRIMARY_BUTTON, ProblemNotice, Skeleton, formatDuration } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRun } from "@/lib/api/firstRun";
import { useFinishFirstRun } from "@/lib/api/firstRun";
import { useCall } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { callsLeft, jobsTitle } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";

import { CapturedDetails } from "../../calls/[callId]/CapturedDetails";
import { RecordingCard } from "../../calls/[callId]/RecordingCard";
import { useRecordingLink } from "../../calls/[callId]/transcriptAccess";
import { TestCallTranscript } from "../../TestCallTranscript";
import { CallStage } from "./LiveStage";
import { StepScreen } from "./shell";

/** A call that did not connect has nothing to show; it gets "Try again" instead. */
const NOT_CONNECTED: Record<string, string> = {
  no_answer: "You didn't pick up, so it couldn't talk to you.",
  busy: "Your line was busy.",
  failed: "The call didn't connect.",
  voicemail: "It reached your voicemail.",
};

/**
 * AFTER THE CALL (D-855): the reward, then the next step.
 *
 * One column read top to bottom (founder, 25 Oct 2026: the two-column version was "so messy"
 * for a new owner): how long it lasted, the summary, what it caught (the business's own
 * labels, values as the call page words them), the recording, the conversation behind a
 * disclosure, then a quiet way to change it. The step's one action is "Make it yours", with
 * "Call me again" beside it; the bar closes the column on a wide screen rather than sticking
 * over the details being read.
 */
export function ResultStep({
  agent,
  call,
  onCallAgain,
  onNext,
}: {
  agent: Agent;
  call: CallSummary;
  onCallAgain: () => void;
  onNext: () => void;
}) {
  const { session, href } = useClientRealm();
  const detail = useCall(session, call.id);
  const scriptHref = href(`/c/${session.orgSlug}/agents/${agent.id}?section=script`);
  const missed = lookup(NOT_CONNECTED, call.status);

  if (missed) {
    return (
      <StepScreen title="The call didn't reach you" hint="Check your phone is on and has signal, then try again.">
        <CallStage
          phase="missed"
          name={agent.name}
          detail={missed}
          actions={
            <button type="button" className={PRIMARY_BUTTON} onClick={onCallAgain}>
              <PhoneCall aria-hidden className="h-4 w-4" />
              Call me again
            </button>
          }
        />
      </StepScreen>
    );
  }

  const transcript = <TestCallTranscript callId={call.id} />;

  return (
    <StepScreen
      title={`That was ${agent.name}'s first call`}
      hint={`It lasted ${formatDuration(call.duration_s)}. Here is what it heard.`}
      primary={
        <>
          Make it yours
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      onSubmit={onNext}
      aside={
        <button type="button" className={TEXT_ACTION} onClick={onCallAgain}>
          <PhoneCall aria-hidden className="h-4 w-4" />
          Call me again
        </button>
      }
      barAtEnd
    >
      {detail.isPending ? (
        <Skeleton rows={4} label="Reading your call" />
      ) : detail.isError ? (
        <ProblemNotice error={detail.error} onRetry={() => void detail.refetch()} />
      ) : (
        <>
          {detail.data.summary ? (
            <section aria-labelledby="first-call-summary">
              <h3 id="first-call-summary" className="text-heading text-ink">
                In short
              </h3>
              <p className="mt-1 max-w-prose text-body text-ink">{detail.data.summary}</p>
            </section>
          ) : detail.data.summary_state === "pending" ? (
            <p role="status" className="text-meta text-ink-muted">
              <span className="text-shimmer">Reading your call…</span> The summary and what it caught appear here in a
              moment.
            </p>
          ) : null}
          <CapturedDetails detail={detail.data} />
          {detail.data.has_recording ? (
            <Recording callId={call.id} durationS={detail.data.duration_s ?? null} moments={detail.data.moments} />
          ) : null}
          {(detail.data.transcript ?? []).length > 0 ? (
            // The summary and the details above are what an owner needs now; the word-for-word
            // read is there for whoever wants it.
            <Disclosure
              variant="inline"
              headingLevel={3}
              title="Read the whole conversation"
              subtitle="Word for word, with personal details hidden."
              className="border-t"
            >
              {transcript}
            </Disclosure>
          ) : (
            transcript
          )}
          <ChangeIt scriptHref={scriptHref} callHref={href(`/c/${session.orgSlug}/calls/${call.id}`)} />
        </>
      )}
    </StepScreen>
  );
}

function Recording({
  callId,
  durationS,
  moments,
}: {
  callId: string;
  durationS: number | null;
  moments: NonNullable<ReturnType<typeof useCall>["data"]>["moments"];
}) {
  const { session } = useClientRealm();
  const recording = useRecordingLink(session, callId);
  // The card shows its own pending face and the refusal under its button.
  useActionFeedback(recording, { errorDisplay: "inline" });
  const player = useRef<CallAudioPlayerHandle>(null);
  return (
    <RecordingCard
      recording={recording}
      playerRef={player}
      onTimeUpdate={() => undefined}
      durationS={durationS}
      moments={moments}
    />
  );
}

/**
 * The quiet way to change it, after the reward and before the next step: the script, or this
 * call kept as a practice test. A suggested fix needs the call read against the script as a
 * practice test (D-844), which is a run of its own, so it is offered on the call's page
 * rather than invented here. Plain links, not buttons: "Make it yours" is the one action.
 */
function ChangeIt({ scriptHref, callHref }: { scriptHref: string; callHref: string }) {
  return (
    <section aria-labelledby="first-call-change" className="pt-2">
      <h3 id="first-call-change" className="text-heading text-ink">
        Want it to say something different?
      </h3>
      <p className="mt-1 max-w-prose text-meta text-ink-muted">
        Change its script any time. Open this call to save it as a practice test, and each new version is
        tried against it.
      </p>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
        <Link href={scriptHref} className={TEXT_ACTION}>
          <PencilLine aria-hidden className="h-4 w-4" />
          Change its script
        </Link>
        <Link href={callHref} className={TEXT_ACTION}>
          <FileText aria-hidden className="h-4 w-4" />
          Open this call
        </Link>
      </div>
    </section>
  );
}

/**
 * STEP 4, MAKE IT YOURS (D-855): "{name} is on your team".
 *
 * What is done, what the trial has left (as calls where that can be said honestly), and the
 * next step: add credit to go live. No go-live reward: that is recorded as a possible feature
 * only (onboarding-vs-outpero §7).
 */
export function TeamStep({ agent, run, onBack }: { agent: Agent; run: FirstRun; onBack: () => void }) {
  const { session, href } = useClientRealm();
  const panel = useTrialPanel(session);
  const finish = useFinishFirstRun(session);
  // Each button finishes the guide and then leaves for its page whatever the answer, so a
  // refusal is toasted (the stack outlives the navigation) and the state is on the button
  // that was pressed.
  const finishFeedback = useActionFeedback(finish, { errorTitle: "Could not finish the guide" });
  const [pressed, setPressed] = useState<string | null>(null);
  const router = useRouter();
  const trial = panel.data;
  const left = trial?.on_trial ? callsLeft(trial.minutes_left, trial.max_call_seconds) : null;
  const done = [
    `${jobsTitle(run.jobs) ?? "Its job"}, in your words`,
    "A voice, a greeting and its AI notice",
    "Its first call, to you",
  ];
  const agentHref = href(`/c/${session.orgSlug}/agents/${agent.id}`);
  const finishThen = (to: string) => {
    setPressed(to);
    finish.mutate(null, { onSettled: () => router.push(to) });
  };
  const creditsHref = href(`/c/${session.orgSlug}/billing?tab=credits`);
  const tourHref = `${agentHref}?tour=1`;
  const homeHref = href(`/c/${session.orgSlug}`);
  const statusOf = (to: string) => (pressed === to ? finishFeedback.status : "idle");
  const othersHeld = finish.isPending;

  return (
    <StepScreen
      title={`${agent.name} is on your team`}
      hint="Here is what is next."
      onBack={onBack}
    >
      <ul className="space-y-2">
        {done.map((line) => (
          <li key={line} className="flex items-center gap-2.5 text-body text-ink">
            <span
              aria-hidden
              className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-strong text-white"
            >
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
            {line}
          </li>
        ))}
      </ul>

      {trial?.on_trial ? (
        <p className="text-body text-ink-muted">
          {trial.minutes_left ?? 0} free trial minutes left
          {left !== null ? `, about ${left} more test ${left === 1 ? "call" : "calls"}` : ""}
          {trial.days_remaining !== null && trial.days_remaining !== undefined
            ? `, for ${trial.days_remaining} more ${trial.days_remaining === 1 ? "day" : "days"}`
            : ""}
          .
        </p>
      ) : null}

      {run.jobs.includes("call_new_leads") ? (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <p className="text-body text-ink-muted">
            Connect your lead form so each new enquiry is called within minutes.
          </p>
          <Link href={href(`/c/${session.orgSlug}/lead-sources`)} className={TEXT_ACTION}>
            <Link2 aria-hidden className="h-4 w-4" />
            Connect it later
          </Link>
        </div>
      ) : null}

      <div className="rounded-card border border-line p-4">
        <h3 className="text-heading text-ink">Go live</h3>
        <p className="mt-1 text-meta text-ink-muted">
          Add credit, then verify your business and choose your number. Until then {agent.name} only makes test calls to
          you.
        </p>
        <ActionButton
          className="mt-3"
          status={statusOf(creditsHref)}
          disabled={othersHeld && pressed !== creditsHref}
          successLabel="Opening"
          onClick={() => finishThen(creditsHref)}
        >
          Add credit
        </ActionButton>
      </div>

      <div className="flex flex-wrap gap-3">
        <ActionButton
          variant="secondary"
          status={statusOf(tourHref)}
          disabled={othersHeld && pressed !== tourHref}
          successLabel="Opening"
          onClick={() => finishThen(tourHref)}
        >
          Show me around {agent.name}
        </ActionButton>
        <ActionButton
          variant="secondary"
          status={statusOf(homeHref)}
          disabled={othersHeld && pressed !== homeHref}
          successLabel="Opening"
          onClick={() => finishThen(homeHref)}
        >
          Go to my dashboard
        </ActionButton>
      </div>
    </StepScreen>
  );
}
