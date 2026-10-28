"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { ArrowRight, Check, FileText, Link2, PencilLine, PhoneCall } from "lucide-react";

import type { CallAudioPlayerHandle } from "@/components/callAudioPlayer";
import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { VoiceWave } from "@/components/illustration/voiceWave";
import { TEXT_ACTION } from "@/components/console/section";
import {
  Disclosure,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatDuration,
} from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRun } from "@/lib/api/firstRun";
import { useFinishFirstRun } from "@/lib/api/firstRun";
import { useGoLive, type GoLive } from "@/lib/api/goLive";
import { useCall } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useTrialPanel } from "@/lib/api/trialCalls";
import { callsLeft, jobOf, jobsTitle } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";

import { CapturedDetails } from "../../calls/[callId]/CapturedDetails";
import { RecordingCard } from "../../calls/[callId]/RecordingCard";
import { useRecordingLink } from "../../calls/[callId]/transcriptAccess";
import { TestCallTranscript } from "../../TestCallTranscript";
import { Monogram, VoiceLine } from "./AgentTakingShape";
import { CallStage } from "./LiveStage";
import { OpeningLine } from "./OpeningLine";
import { StepScreen } from "./shell";
import { FIRST } from "../../setup/_ui/copy";
import { Why } from "@/components/why";

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
      hint={FIRST.resultHint(formatDuration(call.duration_s))}
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
      <Why>Open this call to save it as a practice test. Each new version is tried against it.</Why>
      <div className="mt-2 flex flex-wrap gap-2">
        <Link href={scriptHref} className={SECONDARY_BUTTON}>
          <PencilLine aria-hidden className="h-4 w-4" />
          Change its script
        </Link>
        <Link href={callHref} className={SECONDARY_BUTTON}>
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
  const agentHref = href(`/c/${session.orgSlug}/agents/${agent.id}`);
  const finishThen = (to: string) => {
    setPressed(to);
    finish.mutate(null, { onSettled: () => router.push(to) });
  };
  const tourHref = `${agentHref}?tour=1`;
  const homeHref = href(`/c/${session.orgSlug}`);
  const statusOf = (to: string) => (pressed === to ? finishFeedback.status : "idle");
  const held = (to: string) => finish.isPending && pressed !== to;
  const chips = trial?.on_trial
    ? [
        FIRST.trialMinutes(trial.minutes_left ?? 0),
        left !== null ? FIRST.trialCalls(left) : null,
        trial.days_remaining !== null && trial.days_remaining !== undefined ? FIRST.trialDays(trial.days_remaining) : null,
      ].filter((chip): chip is string => chip !== null)
    : [];

  return (
    <StepScreen title={`${agent.name} is on your team`} hint={<span className="hidden sm:inline">Ready for its first real callers.</span>}
      onBack={onBack}
    >
      <div className="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start lg:gap-6">
        <section aria-label={`${agent.name}, ready`} className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-5">
          <div className="flex min-w-0 items-center gap-3">
            <Monogram name={agent.name} />
            <div className="min-w-0 flex-1">
              <p className="break-words text-heading text-ink">{agent.name}</p>
              <p className="text-meta text-ink-muted">{jobsTitle(run.jobs) ?? jobOf(agent)}</p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-brand-soft px-2.5 py-0.5 text-meta font-medium text-brand-strong">
              <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} />
              Ready
            </span>
          </div>
          <div className="mt-3 space-y-3 border-t border-line pt-3 sm:mt-4 sm:space-y-4 sm:pt-4">
            <VoiceLine agent={agent} note={null} />
            <OpeningLine agent={agent} lang={agent.language_primary} />
          </div>
          {/* Beside the agent from `lg`; on a phone they follow Go live, so its button stays
              on the first screen. */}
          <TrialChips chips={chips} className="mt-4 hidden lg:flex" />
        </section>

        <div className="space-y-4">
          <GoLiveCard agentName={agent.name} statusOf={statusOf} held={held} onGo={finishThen} />
          <TrialChips chips={chips} className="flex lg:hidden" />
          {run.jobs.includes("call_new_leads") ? (
            <section aria-label={FIRST.leadForm} className="flex items-start gap-3 rounded-card border border-line p-4">
              <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-strong">
                <Link2 className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-body font-medium text-ink">{FIRST.leadForm}</p>
                <Why>New enquiries reach {agent.name} in minutes, so it can ring them while they care.</Why>
              </div>
              <Link href={href(`/c/${session.orgSlug}/lead-sources`)} className={`${SECONDARY_BUTTON_SM} shrink-0`}>
                Connect
              </Link>
            </section>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-4">
        <ActionButton
          variant="secondary"
          status={statusOf(tourHref)}
          disabled={held(tourHref)}
          successLabel="Opening"
          onClick={() => finishThen(tourHref)}
        >
          <span className="truncate" title={`Show me around ${agent.name}`}>
            Show me around {agent.name}
          </span>
        </ActionButton>
        <button type="button" className={TEXT_ACTION} disabled={held(homeHref)} onClick={() => finishThen(homeHref)}>
          Go to my dashboard
          <ArrowRight aria-hidden className="h-4 w-4" />
        </button>
      </div>
    </StepScreen>
  );
}

function TrialChips({ chips, className }: { chips: readonly string[]; className: string }) {
  if (chips.length === 0) return null;
  return (
    <ul className={`flex-wrap gap-2 ${className}`} aria-label="Your free trial">
      {chips.map((chip) => (
        <li key={chip} className="rounded-full bg-surface-muted px-3 py-1 text-meta font-medium tabular-nums text-ink">
          {chip}
        </li>
      ))}
    </ul>
  );
}

type GoLiveStepId = "credit" | "verify" | "number";
type StepState = "done" | "current" | "waiting" | "in_review" | "attention";

/** The three steps to real callers, each one short line, from the go-live guide's own state. */
export function goLiveSteps(
  guide: Pick<GoLive, "owed_at" | "verify" | "number"> | undefined,
): { id: GoLiveStepId; label: string; state: StepState }[] {
  const credit = guide?.owed_at ? "done" : "todo";
  const verify = guide?.verify ?? "todo";
  const number = guide?.number ?? "todo";
  const raw: { id: GoLiveStepId; label: string; done: boolean; note: StepState | null }[] = [
    { id: "credit", label: "Add credit", done: credit === "done", note: null },
    {
      id: "verify",
      label: "Verify your business",
      done: verify === "done",
      note: verify === "in_review" ? "in_review" : verify === "needs_attention" ? "attention" : null,
    },
    { id: "number", label: "Choose your number", done: number === "done", note: null },
  ];
  const current = raw.findIndex((step) => !step.done);
  return raw.map((step, index) => ({
    id: step.id,
    label: step.label,
    state: step.done ? "done" : index === current ? (step.note ?? "current") : "waiting",
  }));
}

const STEP_NOTE: Partial<Record<StepState, string>> = { in_review: "In review", attention: "Needs you" };

/**
 * THE GO LIVE CARD (D-918): the screen's one primary next step. Its header band is the
 * auth pages' ASCII voice field, contained (`VoiceWave contained`), with nothing on it:
 * the steps and the button sit below it on the opaque card, so their contrast is the
 * card's own. The steps come from `GET /v1/go-live`; the current one carries the button.
 */
function GoLiveCard({
  agentName,
  statusOf,
  held,
  onGo,
}: {
  agentName: string;
  statusOf: (to: string) => FeedbackStatus;
  held: (to: string) => boolean;
  onGo: (to: string) => void;
}) {
  const { session, href } = useClientRealm();
  const guide = useGoLive(session);
  const creditsHref = href(`/c/${session.orgSlug}/billing?tab=credits`);
  const guideHref = href(`/c/${session.orgSlug}/go-live`);
  const steps = guide.isError ? goLiveSteps(undefined) : goLiveSteps(guide.data);
  return (
    <section aria-labelledby="go-live-title" className="overflow-hidden rounded-card border border-brand/30 bg-surface shadow-card">
      {/* The band IS the picture: one voice talking, across the card. Nothing sits on it. */}
      <div className="relative h-16 overflow-hidden border-b border-line sm:h-[6.5rem]">
        <VoiceWave contained />
      </div>
      <div className="p-4 sm:p-5">
        <h3 id="go-live-title" className="mb-2 text-heading text-ink sm:mb-3">
          Go live
        </h3>
        {guide.isPending ? (
          <Skeleton rows={3} label="Checking where you are" />
        ) : (
          <ol className="space-y-3">
            {steps.map((step, index) => (
              <li key={step.id} className="flex items-center gap-3">
                <StepMark state={step.state} index={index} />
                <span className={`min-w-0 flex-1 text-body ${step.state === "waiting" ? "text-ink-muted" : "text-ink"}`}>
                  {step.label}
                  {STEP_NOTE[step.state] ? <span className="text-ink-muted"> · {STEP_NOTE[step.state]}</span> : null}
                </span>
                {step.state === "current" || step.state === "attention" ? (
                  <ActionButton
                    variant="primary-sm"
                    status={statusOf(step.id === "credit" ? creditsHref : guideHref)}
                    disabled={held(step.id === "credit" ? creditsHref : guideHref)}
                    successLabel="Opening"
                    onClick={() => onGo(step.id === "credit" ? creditsHref : guideHref)}
                  >
                    {step.id === "credit" ? "Add credit" : "Continue"}
                  </ActionButton>
                ) : null}
              </li>
            ))}
          </ol>
        )}
        {guide.isError ? <p className="mt-3 text-meta text-ink-muted">Couldn&apos;t check your progress.</p> : null}
        <p className="mt-4 text-meta text-ink-muted">Until then, {agentName} only makes test calls to you.</p>
      </div>
    </section>
  );
}

function StepMark({ state, index }: { state: StepState; index: number }) {
  if (state === "done")
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-strong text-white">
        <span className="sr-only">Done: </span>
        <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
    );
  const current = state !== "waiting";
  return (
    <span
      className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[12px] font-medium tabular-nums ${
        current ? "border-brand-strong text-brand-strong" : "border-line text-ink-faint"
      }`}
    >
      <span className="sr-only">{current ? "Next: " : "Later: "}</span>
      {index + 1}
    </span>
  );
}
