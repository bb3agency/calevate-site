"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef } from "react";
import { ArrowRight, Check, PhoneCall } from "lucide-react";

import type { CallAudioPlayerHandle } from "@/components/callAudioPlayer";
import { TEXT_ACTION } from "@/components/console/section";
import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, Skeleton, formatDuration } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRun } from "@/lib/api/firstRun";
import { primaryJob, useFinishFirstRun } from "@/lib/api/firstRun";
import { useCall } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { callsLeft, jobCard } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";

import { CapturedDetails } from "../../calls/[callId]/CapturedDetails";
import { RecordingCard } from "../../calls/[callId]/RecordingCard";
import { useRecordingLink } from "../../calls/[callId]/transcriptAccess";
import { TestCallTranscript } from "../../TestCallTranscript";
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
 * "That was {name}'s first call", version one, with what it caught (the business's own
 * labels, values as the call page words them), the summary, the recording and the transcript
 * in place. Then Call again, Change its script, or move on to make it yours.
 */
export function ResultStep({
  agent,
  call,
  placedAt,
  onCallAgain,
  onNext,
}: {
  agent: Agent;
  call: CallSummary;
  placedAt: number;
  onCallAgain: () => void;
  onNext: () => void;
}) {
  const { session, href } = useClientRealm();
  const detail = useCall(session, call.id);
  const scriptHref = href(`/c/${session.orgSlug}/agents/${agent.id}?section=script`);
  const missed = lookup(NOT_CONNECTED, call.status);

  if (missed) {
    return (
      <StepScreen title="The call didn't reach you" hint={missed} primary={<><PhoneCall aria-hidden className="h-4 w-4" />Call me again</>} onSubmit={onCallAgain}>
        <p className="text-meta text-ink-muted">Check your phone is on and has signal, then try again.</p>
      </StepScreen>
    );
  }

  return (
    <StepScreen
      title={`That was ${agent.name}'s first call`}
      hint={
        <span className="inline-flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-brand-soft px-2 py-0.5 text-meta font-medium text-brand-strong">Version one</span>
          <span>It lasted {formatDuration(call.duration_s)}. Here is what it caught.</span>
        </span>
      }
      primary={
        <>
          Make it yours
          <ArrowRight aria-hidden className="h-4 w-4" />
        </>
      }
      onSubmit={onNext}
      aside={
        <span className="flex flex-wrap items-center justify-center gap-x-5">
          <button type="button" className={TEXT_ACTION} onClick={onCallAgain}>
            Call me again
          </button>
          <Link href={scriptHref} className={TEXT_ACTION}>
            Change its script
          </Link>
        </span>
      }
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
              <p className="mt-1 text-body text-ink">{detail.data.summary}</p>
            </section>
          ) : detail.data.summary_state === "pending" ? (
            <p role="status" className="text-meta text-ink-muted">
              <span className="text-shimmer">Reading your call…</span> The summary and what it caught appear here in a moment.
            </p>
          ) : null}
          <CapturedDetails detail={detail.data} />
          {detail.data.has_recording ? <Recording callId={call.id} durationS={detail.data.duration_s ?? null} moments={detail.data.moments} /> : null}
          <ImproveIt callHref={href(`/c/${session.orgSlug}/calls/${call.id}`)} />
        </>
      )}
      <TestCallTranscript agentId={agent.id} placedAt={placedAt} />
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
  const player = useRef<CallAudioPlayerHandle>(null);
  return <RecordingCard recording={recording} playerRef={player} onTimeUpdate={() => undefined} durationS={durationS} moments={moments} />;
}

/**
 * The one improvement this screen offers. A suggested fix needs the call read against the
 * script as a practice test (D-844), which is a run of its own, so it is offered as the next
 * step on the call's page rather than invented here.
 */
function ImproveIt({ callHref }: { callHref: string }) {
  return (
    <section aria-labelledby="first-call-improve" className="rounded-card border border-line p-4">
      <h3 id="first-call-improve" className="text-heading text-ink">
        Make version two better
      </h3>
      <p className="mt-1 text-meta text-ink-muted">
        Save this call as a practice test on its page, so each new version of the script is tried against it.
      </p>
      <Link href={callHref} className={`${SECONDARY_BUTTON} mt-3`}>
        Open the call
      </Link>
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
  const router = useRouter();
  const trial = panel.data;
  const left = trial?.on_trial ? callsLeft(trial.minutes_left, trial.max_call_seconds) : null;
  const done = [
    `${jobCard(primaryJob(run))?.title ?? "Its job"}, in your words`,
    "A voice, a greeting and its AI notice",
    "Its first call, to you",
  ];
  const agentHref = href(`/c/${session.orgSlug}/agents/${agent.id}`);
  const finishThen = (to: string) => finish.mutate(null, { onSettled: () => router.push(to) });

  return (
    <StepScreen title={`${agent.name} is on your team`} hint="Version one is done. Here is what is next." onBack={onBack}>
      <ul className="space-y-2">
        {done.map((line) => (
          <li key={line} className="flex items-center gap-2.5 text-body text-ink">
            <span aria-hidden className="flex h-5 w-5 items-center justify-center rounded-full bg-brand-strong text-white">
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
          {trial.days_remaining !== null && trial.days_remaining !== undefined ? `, for ${trial.days_remaining} more ${trial.days_remaining === 1 ? "day" : "days"}` : ""}.
        </p>
      ) : null}

      {run.jobs.includes("call_new_leads") ? (
        <p className="text-body text-ink">
          <Link href={href(`/c/${session.orgSlug}/lead-sources`)} className={TEXT_ACTION}>
            Connect your lead form later
          </Link>{" "}
          <span className="text-ink-muted">so each new enquiry is called within minutes.</span>
        </p>
      ) : null}

      <div className="rounded-card border border-line p-4">
        <h3 className="text-heading text-ink">Go live</h3>
        <p className="mt-1 text-meta text-ink-muted">
          Add credit, then verify your business and choose your number. Until then {agent.name} only makes test calls to you.
        </p>
        <button type="button" className={`${PRIMARY_BUTTON} mt-3`} disabled={finish.isPending} onClick={() => finishThen(href(`/c/${session.orgSlug}/billing?tab=credits`))}>
          Add credit
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <button type="button" className={SECONDARY_BUTTON} disabled={finish.isPending} onClick={() => finishThen(`${agentHref}?tour=1`)}>
          Show me around {agent.name}
        </button>
        <button type="button" className={SECONDARY_BUTTON} disabled={finish.isPending} onClick={() => finishThen(href(`/c/${session.orgSlug}`))}>
          Go to my dashboard
        </button>
      </div>
      {finish.error ? <ProblemNotice error={finish.error} /> : null}
    </StepScreen>
  );
}
