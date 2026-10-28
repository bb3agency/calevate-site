"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { ArrowRight, Bot, ExternalLink, MessageCircle, PhoneCall, RotateCcw, Sprout, Target } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import {
  FIELD_GROUP,
  FIELD_GROUP_AFFIX,
  FIELD_GROUP_INPUT,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { useAcceptAgreement, useAgreementsReadiness, needsAction } from "@/lib/api/agreements";
import { useAgentLifecycle, type Agent } from "@/lib/api/agents";
import { ApiProblem, type CallSummary } from "@/lib/api/client";
import type { FirstRunJob } from "@/lib/api/firstRun";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel } from "@/lib/api/trialCalls";
import { useAcceptPledge, useOutboundPledge } from "@/lib/api/verifyBusiness";
import { callIntroFor, trialMinutesLine } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";

import { CallStage, limitIcon, type CallPhase } from "./LiveStage";
import { StepScreen, TickRow } from "./shell";
import { FIRST } from "../../setup/_ui/copy";

/** The three things a new owner should know before they hear their agent (D-855). */
export const HONEST_WORDS = [
  { icon: Bot, line: "It is an AI, and says so when asked." },
  {
    icon: Target,
    line: "It only knows what you told it.",
  },
  {
    icon: Sprout,
    line: "This is version one. You improve it next.",
  },
] as const;

/** A refusal that is a limit of the trial, not a fault: it gets the limit's own frame. */
export function isLimitRule(rule: string | null | undefined): boolean {
  return Boolean(rule && /daily_cap|minutes_used|trial_ended/.test(rule));
}

/**
 * STEP 3, HEAR IT (D-855): one screen before the call, then the call itself on the stage.
 *
 * Before the call: three honest lines, then only the ticks still outstanding, each its own
 * short tick and never bundled (founder, 23 Oct 2026): each agreement not yet accepted, the
 * no-cold-calls pledge, and "this number is mine". Then the number and the button. No code is
 * sent to the phone.
 *
 * The button accepts what was ticked (`POST /v1/legal/acceptances` per document, the pledge),
 * gets a draft agent ready (`/prepare`), then asks `POST /v1/trial/calls` to ring the number,
 * so every gate that endpoint keeps (the daily cap, the trial's minutes; calling hours only
 * without the own-number tick) is the
 * one that answers, in its own words. From the press on, the stage shows the call as the
 * call: getting ready, dialling, ringing, talking with a clock, ended; or why it did not
 * connect, with a way to try again. There is no live transcript, so none is pretended.
 */
export function HearItStep({
  agent,
  jobs,
  calls,
  onBack,
  onEnded,
}: {
  agent: Agent;
  jobs: readonly FirstRunJob[];
  calls: readonly CallSummary[] | undefined;
  onBack: () => void;
  onEnded: (call: CallSummary) => void;
}) {
  const { session, href } = useClientRealm();
  const panel = useTrialPanel(session);
  const me = useMe(session);
  const business = me.data?.organization?.name ?? "your business";

  if (panel.isPending) return <Skeleton rows={4} label="Checking your test calls" />;
  if (panel.isError) return <ProblemNotice error={panel.error} onRetry={() => void panel.refetch()} />;
  if (!panel.data.on_trial) {
    return (
      <StepScreen
        title={`Hear ${agent.name}`}
        hint={FIRST.hearHint}
        onBack={onBack}
      >
        <Link href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=training`)} className={PRIMARY_BUTTON}>
          <MessageCircle aria-hidden className="h-4 w-4" />
          Try it in the chat
        </Link>
      </StepScreen>
    );
  }
  return <CallYou agent={agent} jobs={jobs} calls={calls} business={business} onBack={onBack} onEnded={onEnded} />;
}

function CallYou({
  agent,
  jobs,
  calls,
  business,
  onBack,
  onEnded,
}: {
  agent: Agent;
  jobs: readonly FirstRunJob[];
  calls: readonly CallSummary[] | undefined;
  business: string;
  onBack: () => void;
  onEnded: (call: CallSummary) => void;
}) {
  const { session, href } = useClientRealm();
  const panel = useTrialPanel(session);
  const readiness = useAgreementsReadiness(session);
  const pledge = useOutboundPledge(session);
  const acceptAgreement = useAcceptAgreement(session);
  const acceptPledge = useAcceptPledge(session);
  const prepare = useAgentLifecycle(session, agent.id);
  const place = usePlaceTrialCall(session);
  // From the press on, the call stage below IS these actions' feedback: preparing, dialling,
  // ringing, or the refusal in its own words with a way to try again. So each failure is
  // shown there, not toasted, and nothing here offers Undo (a call placed cannot be).
  useActionFeedback(acceptAgreement, { errorDisplay: "inline" });
  useActionFeedback(acceptPledge, { errorDisplay: "inline" });
  useActionFeedback(prepare, { errorDisplay: "inline" });
  useActionFeedback(place, { errorDisplay: "inline" });
  const numberId = useId();
  const [number, setNumber] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(() => new Set());
  // The press of "Call me now": from then on the stage, not the form, is the screen.
  // `dialled`: the ring was asked for (before it, the agreements and the draft are being
  // made ready). `skip`: the call this attempt replaces, so "Call me again" never shows the
  // missed call's row as the new one.
  const [attempt, setAttempt] = useState<{
    at: number;
    refused: string | null;
    dialled: boolean;
    skip: string | null;
  } | null>(null);
  const trial = panel.data;

  const tick = (key: string, on: boolean) =>
    setTicked((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const viewing = Boolean(session.impersonateOrg);
  const docs = (readiness.data?.documents ?? []).filter(needsAction);
  const pledgeOutstanding = pledge.data !== undefined && !pledge.data.is_current;
  const canAccept = readiness.data?.can_accept === true && !viewing;
  const outstanding = [...docs.map((doc) => `doc:${doc.slug}`), ...(pledgeOutstanding ? ["pledge"] : []), "mine"];
  const allTicked = outstanding.every((key) => ticked.has(key));
  const busy = acceptAgreement.isPending || acceptPledge.isPending || prepare.isPending || place.isPending;
  const loading = readiness.isPending || pledge.isPending;
  const ready = !loading && allTicked && number.trim().length >= 8 && !busy && (docs.length === 0 || canAccept);
  const failure = acceptAgreement.error ?? acceptPledge.error ?? prepare.error ?? place.error;

  const dial = (skip: string | null = null) => {
    setAttempt({ at: Date.now(), refused: null, dialled: true, skip });
    place.mutate({
      agentId: agent.id,
      number: number.trim(),
      numberIsMine: true,
    });
  };

  const ring = async () => {
    setAttempt({ at: Date.now(), refused: null, dialled: false, skip: null });
    const statement = readiness.data?.acceptance_statement_version;
    for (const doc of docs) {
      if (!statement) break;
      await acceptAgreement.mutateAsync({
        slug: doc.slug,
        version: doc.version,
        statementVersion: statement,
      });
    }
    if (pledgeOutstanding && pledge.data) {
      await acceptPledge.mutateAsync({
        version: pledge.data.version,
        text_sha256: pledge.data.text_sha256,
      });
    }
    if (!agent.published) await prepare.mutateAsync("prepare");
    const fresh = await panel.refetch();
    if (fresh.data?.can_call === false && fresh.data.blocked_reason) {
      setAttempt({
        at: Date.now(),
        refused: fresh.data.blocked_reason,
        dialled: false,
        skip: null,
      });
      return;
    }
    dial();
  };

  const startOver = () => {
    place.reset();
    acceptAgreement.reset();
    acceptPledge.reset();
    prepare.reset();
    setAttempt(null);
  };

  const intro = callIntroFor(jobs, business);

  if (attempt !== null) {
    return (
      <StepScreen title={`Hear ${agent.name} on your phone`} hint={intro}>
        <CallInProgress
          agent={agent}
          calls={calls}
          since={attempt.at}
          skip={attempt.skip}
          preparing={!attempt.dialled}
          placing={place.isPending}
          placed={place.data ?? null}
          refused={attempt.refused}
          failure={failure}
          onRetry={dial}
          onStartOver={startOver}
          // A refused ring is asked again as it was; a failure before it starts the form over,
          // since the agreements or the draft may not have gone through.
          onRetryFailure={
            place.error
              ? () => {
                  place.reset();
                  dial();
                }
              : startOver
          }
          onEnded={onEnded}
          creditHref={href(`/c/${session.orgSlug}/billing?tab=credits`)}
          chatHref={href(`/c/${session.orgSlug}/agents/${agent.id}?section=training`)}
        />
      </StepScreen>
    );
  }

  const blocked = trial && !trial.can_call && agent.published && trial.blocked_reason ? trial.blocked_reason : null;

  return (
    <StepScreen
      title={`Hear ${agent.name} on your phone`}
      hint={intro}
      onBack={onBack}
      primary={
        blocked ? undefined : (
          <>
            <PhoneCall aria-hidden className="h-4 w-4" />
            Call me now
          </>
        )
      }
      pending={busy}
      disabled={!ready}
      onSubmit={() => void ring().catch(() => undefined)}
    >
      {blocked ? (
        <CallStage
          phase="limit"
          name={agent.name}
          icon={limitIcon(null)}
          detail={blocked}
          actions={
            <Link
              href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=training`)}
              className={SECONDARY_BUTTON}
            >
              <MessageCircle aria-hidden className="h-4 w-4" />
              Try it in the chat instead
            </Link>
          }
        />
      ) : null}

      <ul className="space-y-2">
        {HONEST_WORDS.map(({ icon: Icon, line }) => (
          <li key={line} className="flex items-start gap-3 text-body text-ink">
            <span
              aria-hidden
              className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-strong"
            >
              <Icon className="h-4 w-4" />
            </span>
            <span className="pt-0.5">{line}</span>
          </li>
        ))}
      </ul>

      {viewing ? (
        <RestrictionNote reason={FIRST.viewOnly} />
      ) : readiness.data && !readiness.data.can_accept && docs.length > 0 ? (
        <RestrictionNote
          reason={readiness.data.can_accept_reason ?? "Only the account's owner can accept its agreements."}
        />
      ) : null}

      <div>
        <label htmlFor={numberId} className="text-heading text-ink">
          Your mobile number
        </label>
        <div className={`${FIELD_GROUP} mt-2 sm:max-w-xs`}>
          <span aria-hidden className={FIELD_GROUP_AFFIX}>
            +91
          </span>
          <input
            id={numberId}
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            enterKeyHint="go"
            maxLength={20}
            value={number}
            placeholder="98765 43210"
            onChange={(event) => setNumber(event.target.value)}
            className={`${FIELD_GROUP_INPUT} pl-16 font-mono text-[16px]`}
          />
        </div>
        {trial ? <p className="mt-2 text-meta text-ink-muted">{trialMinutesLine(trial)}</p> : null}
      </div>

      {loading ? (
        <Skeleton rows={2} label="Checking what is left to agree" />
      ) : (
        <fieldset>
          <legend className="text-heading text-ink">Before it rings</legend>
          {readiness.isError ? (
            <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} />
          ) : null}
          <ul className="mt-2 divide-y divide-line overflow-hidden rounded-card border border-line bg-surface">
            {docs.map((doc) => (
              <TickRow
                key={doc.slug}
                name="agree"
                checked={ticked.has(`doc:${doc.slug}`)}
                onChange={(on) => tick(`doc:${doc.slug}`, on)}
                label={`I accept the ${doc.title}`}
                extra={
                  <a
                    href={doc.href}
                    target="_blank"
                    rel="noreferrer"
                    className="press inline-flex min-h-8 items-center gap-1 rounded-md px-2 text-meta font-medium text-brand-strong hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                  >
                    <span>
                      Read it<span className="sr-only"> (opens in a new tab)</span>
                    </span>
                    <ExternalLink aria-hidden className="h-3 w-3" />
                  </a>
                }
              />
            ))}
            {pledgeOutstanding && pledge.data ? (
              <TickRow
                name="pledge"
                checked={ticked.has("pledge")}
                onChange={(on) => tick("pledge", on)}
                label="I take the no-cold-calls pledge"
                hint="It only calls people who asked to hear from you."
              />
            ) : null}
            <TickRow
              name="mine"
              checked={ticked.has("mine")}
              onChange={(on) => tick("mine", on)}
              label="This number is my own"
              hint="Test calls only ring a phone you own."
            />
          </ul>
          {docs.length > 0 && readiness.data?.acceptance_statement ? (
            <p className="mt-2 text-meta text-ink-faint">{readiness.data.acceptance_statement}</p>
          ) : null}
          {pledgeOutstanding && pledge.data ? (
            <details className="mt-1">
              <summary className="inline-flex min-h-8 cursor-pointer items-center rounded-md text-meta font-medium text-brand-strong">
                Read the pledge
              </summary>
              <p className="whitespace-pre-line pb-2 text-meta text-ink-muted">{pledge.data.pledge_text}</p>
            </details>
          ) : null}
        </fieldset>
      )}

      {!agent.engine_voice_id ? (
        <p role="status" className="text-meta text-warn">
          {agent.name} needs a voice before it can ring you.{" "}
          <Link
            href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=voice`)}
            className="font-medium underline underline-offset-2"
          >
            Choose one
          </Link>
        </p>
      ) : null}
    </StepScreen>
  );
}

const WATCH_MS = 3000;
/** How long "Call ended" holds before the next step, so the end is seen, not skipped. */
const ENDED_HOLD_MS = 1600;

/** A call that ended without a conversation, in the owner's words. */
const NOT_CONNECTED: Record<string, string> = {
  no_answer: "You didn't pick up, so it couldn't talk to you.",
  busy: "Your line was busy.",
  failed: "The call didn't connect. Check your phone has signal.",
  voicemail: "It reached your voicemail.",
};

/** The phase the stage shows, from what has happened since the press. */
export function callPhaseOf({
  preparing,
  placing,
  placedStatus,
  callStatus,
  refused,
  failed,
  limit,
}: {
  preparing: boolean;
  placing: boolean;
  placedStatus: "queued" | "blocked" | null;
  callStatus: string | null;
  refused: boolean;
  failed: boolean;
  limit: boolean;
}): CallPhase {
  if (failed) return "error";
  if (refused || placedStatus === "blocked") return limit ? "limit" : "missed";
  if (preparing) return "preparing";
  if (placing || placedStatus === null) return "dialling";
  switch (callStatus) {
    case null:
    case "queued":
      return "dialling";
    case "ringing":
      return "ringing";
    case "in_progress":
      return "talking";
    case "completed":
      return "ended";
    default:
      return "missed";
  }
}

/**
 * The call from the press on. Its row is read every few seconds while it is live, because the
 * change stream slows to a safety poll when healthy and the owner is watching this one call.
 */
function CallInProgress({
  agent,
  calls,
  since,
  skip,
  preparing,
  placing,
  placed,
  refused,
  failure,
  onRetry,
  onRetryFailure,
  onStartOver,
  onEnded,
  creditHref,
  chatHref,
}: {
  agent: Agent;
  calls: readonly CallSummary[] | undefined;
  since: number;
  skip: string | null;
  preparing: boolean;
  placing: boolean;
  placed: {
    status: "queued" | "blocked";
    blocked_reason?: string | null;
    blocked_rule?: string | null;
  } | null;
  refused: string | null;
  failure: Error | null;
  onRetry: (skip: string | null) => void;
  onRetryFailure: () => void;
  onStartOver: () => void;
  onEnded: (call: CallSummary) => void;
  creditHref: string;
  chatHref: string;
}) {
  const { session } = useClientRealm();
  const queries = useQueryClient();
  const call =
    placed?.status === "queued"
      ? calls?.find((row) => row.id !== skip && Date.parse(row.started_at ?? "") >= since - 60_000)
      : undefined;
  const rule = placed?.blocked_rule ?? null;
  const limit = refused !== null || isLimitRule(rule);
  const phase = callPhaseOf({
    preparing,
    placing,
    placedStatus: placed?.status ?? null,
    callStatus: call?.status ?? null,
    refused: refused !== null,
    failed: failure !== null,
    limit,
  });
  const live = phase === "dialling" || phase === "ringing" || phase === "talking";
  const [answeredAt, setAnsweredAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const handedOn = useRef(false);

  useEffect(() => {
    if (!live || placed?.status !== "queued") return undefined;
    const timer = window.setInterval(
      () =>
        void queries.invalidateQueries({
          queryKey: ["calls", session.orgSlug],
        }),
      WATCH_MS,
    );
    return () => window.clearInterval(timer);
  }, [live, placed?.status, queries, session.orgSlug]);

  useEffect(() => {
    if (phase !== "talking") return undefined;
    if (answeredAt === null) setAnsweredAt(Date.now());
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [phase, answeredAt]);

  const ended = phase === "ended" && call ? call : null;
  useEffect(() => {
    if (!ended || handedOn.current) return undefined;
    const timer = window.setTimeout(() => {
      handedOn.current = true;
      onEnded(ended);
    }, ENDED_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [ended, onEnded]);

  const talked =
    phase === "ended"
      ? (call?.duration_s ?? 0)
      : answeredAt === null
        ? 0
        : Math.max(0, Math.floor((now - answeredAt) / 1000));

  switch (phase) {
    case "preparing":
      return (
        <CallStage
          phase={phase}
          name={agent.name}
          title={`Getting ${agent.name} ready`}
          detail="A few seconds, then it dials."
        />
      );
    case "dialling":
      return <CallStage phase={phase} name={agent.name} detail="Keep your phone close. It rings in a moment." />;
    case "ringing":
      return (
        <CallStage
          phase={phase}
          name={agent.name}
          title="Your phone is ringing"
          detail="Pick up and talk to it like a customer would."
        />
      );
    case "talking":
      return <CallStage phase={phase} name={agent.name} title={`You're talking to ${agent.name}`} seconds={talked} />;
    case "ended":
      return (
        <CallStage
          phase={phase}
          name={agent.name}
          seconds={talked}
          detail="Reading the call now."
          actions={
            ended ? (
              <button
                type="button"
                className={PRIMARY_BUTTON}
                onClick={() => {
                  handedOn.current = true;
                  onEnded(ended);
                }}
              >
                See what it caught
                <ArrowRight aria-hidden className="h-4 w-4" />
              </button>
            ) : null
          }
        />
      );
    case "limit": {
      const minutes = /minutes_used|trial_ended/.test(rule ?? "");
      return (
        <CallStage
          phase={phase}
          name={agent.name}
          icon={limitIcon(rule)}
          detail={refused ?? placed?.blocked_reason ?? "Your trial's test calls are used up for now."}
          actions={
            <>
              {minutes ? (
                <Link href={creditHref} className={PRIMARY_BUTTON}>
                  Add credit
                </Link>
              ) : null}
              <Link href={chatHref} className={SECONDARY_BUTTON}>
                <MessageCircle aria-hidden className="h-4 w-4" />
                Try it in the chat instead
              </Link>
            </>
          }
        />
      );
    }
    case "error":
      return (
        <CallStage
          phase={phase}
          name={agent.name}
          detail={failure instanceof ApiProblem ? failure.message : "Check your connection, then try again."}
          actions={
            <>
              <button type="button" className={PRIMARY_BUTTON} onClick={onRetryFailure}>
                <RotateCcw aria-hidden className="h-4 w-4" />
                Try again
              </button>
            </>
          }
        />
      );
    default:
      return (
        <CallStage
          phase="missed"
          name={agent.name}
          detail={
            placed?.status === "blocked"
              ? (placed.blocked_reason ?? "This test call was not allowed.")
              : (lookup(NOT_CONNECTED, call?.status ?? "") ?? "The call didn't connect.")
          }
          actions={
            <>
              {placed?.status === "queued" ? (
                <button type="button" className={PRIMARY_BUTTON} onClick={() => onRetry(call?.id ?? null)}>
                  <PhoneCall aria-hidden className="h-4 w-4" />
                  Call me again
                </button>
              ) : null}
              <button type="button" className={SECONDARY_BUTTON} onClick={onStartOver}>
                Use another number
              </button>
            </>
          }
        />
      );
  }
}
