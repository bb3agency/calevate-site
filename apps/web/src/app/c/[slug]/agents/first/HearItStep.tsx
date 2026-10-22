"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { ExternalLink, PhoneCall } from "lucide-react";

import { FIELD, PRIMARY_BUTTON, ProblemNotice, RestrictionNote, Skeleton, formatDuration } from "@/components/ui";
import { useAcceptAgreement, useAgreementsReadiness, needsAction } from "@/lib/api/agreements";
import { useAgentLifecycle, type Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import type { FirstRunJob } from "@/lib/api/firstRun";
import { useMe } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel } from "@/lib/api/trialCalls";
import { useAcceptPledge, useOutboundPledge } from "@/lib/api/verifyBusiness";
import { jobCard, trialMinutesLine } from "@/lib/firstAgent";
import { lookup } from "@/lib/lookup";

import { ChoiceCard, StepScreen } from "./shell";

/** The three things a new owner should know before they hear their agent (D-855). */
const HONEST_WORDS = [
  "It's an AI, and it says so whenever a caller asks.",
  "It only knows what you told it, so it is only as good as what you said.",
  "This is version one. You will make it better after you hear it.",
] as const;

/**
 * STEP 3, HEAR IT (D-855): one screen before the call, then the call itself.
 *
 * Before the call: three honest lines, then only the ticks still outstanding, each its own
 * short tick and never bundled (founder, 23 Oct 2026): each agreement not yet accepted, the
 * no-cold-calls pledge, and "this number is mine". Then the number and the button. No code is
 * sent to the phone.
 *
 * The button accepts what was ticked (`POST /v1/legal/acceptances` per document, the pledge),
 * gets a draft agent ready (`/prepare`), then asks `POST /v1/trial/calls` to ring the number,
 * so every gate that endpoint keeps (the daily cap, the trial's minutes, calling hours) is the
 * one that answers, in its own words. The call is then shown as the call: ringing, talking,
 * ended, and a timer. There is no live transcript, so none is pretended.
 */
export function HearItStep({
  agent,
  job,
  calls,
  onBack,
  onEnded,
}: {
  agent: Agent;
  job: FirstRunJob | null;
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
      <StepScreen title={`Hear ${agent.name}`} hint="Talk to it in the chat on its page: it answers as it would on a call." onBack={onBack}>
        <Link href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=training`)} className={PRIMARY_BUTTON}>
          Try it in the chat
        </Link>
      </StepScreen>
    );
  }
  return <CallYou agent={agent} job={job} calls={calls} business={business} onBack={onBack} onEnded={onEnded} />;
}

function CallYou({
  agent,
  job,
  calls,
  business,
  onBack,
  onEnded,
}: {
  agent: Agent;
  job: FirstRunJob | null;
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
  const numberId = useId();
  const [number, setNumber] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(() => new Set());
  const [placedAt, setPlacedAt] = useState<number | null>(null);
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

  const ring = async () => {
    const statement = readiness.data?.acceptance_statement_version;
    for (const doc of docs) {
      if (!statement) break;
      await acceptAgreement.mutateAsync({ slug: doc.slug, version: doc.version, statementVersion: statement });
    }
    if (pledgeOutstanding && pledge.data) {
      await acceptPledge.mutateAsync({ version: pledge.data.version, text_sha256: pledge.data.text_sha256 });
    }
    if (!agent.published) await prepare.mutateAsync("prepare");
    const fresh = await panel.refetch();
    if (fresh.data?.can_call === false && fresh.data.blocked_reason) return;
    setPlacedAt(Date.now());
    place.mutate({ agentId: agent.id, number: number.trim(), numberIsMine: true });
  };

  const intro = jobCard(job)?.callIntro(business) ?? "It rings you and talks to you as it would to a caller.";
  const placed = place.data?.status === "queued" && placedAt !== null;
  const call = placed ? calls?.find((row) => Date.parse(row.started_at ?? "") >= (placedAt ?? 0) - 60_000) : undefined;

  if (placed) {
    return (
      <StepScreen title={`${agent.name} is calling you`} hint={intro}>
        <CallLive call={call} onEnded={onEnded} />
      </StepScreen>
    );
  }

  const blocked =
    trial && !trial.can_call && agent.published && trial.blocked_reason ? trial.blocked_reason : null;

  return (
    <StepScreen
      title={`Hear ${agent.name} on your phone`}
      hint={intro}
      onBack={onBack}
      primary={
        <>
          <PhoneCall aria-hidden className="h-4 w-4" />
          {prepare.isPending ? "Getting it ready…" : busy ? "Calling…" : "Call me now"}
        </>
      }
      pending={busy}
      disabled={!ready}
      onSubmit={() => void ring().catch(() => undefined)}
    >
      <ul className="space-y-2">
        {HONEST_WORDS.map((line) => (
          <li key={line} className="flex gap-2.5 text-body text-ink">
            <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink/40" />
            {line}
          </li>
        ))}
      </ul>

      {viewing ? (
        <RestrictionNote reason="You are viewing this account. Only its owner can accept its agreements and take the test call." />
      ) : readiness.data && !readiness.data.can_accept && docs.length > 0 ? (
        <RestrictionNote reason={readiness.data.can_accept_reason ?? "Only the account's owner can accept its agreements."} />
      ) : null}

      {loading ? (
        <Skeleton rows={2} label="Checking what is left to agree" />
      ) : (
        <fieldset className="space-y-2">
          <legend className="text-heading text-ink">Before it rings</legend>
          {readiness.isError ? <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} /> : null}
          {docs.map((doc) => (
            <ChoiceCard
              key={doc.slug}
              type="checkbox"
              name="agree"
              value={doc.slug}
              checked={ticked.has(`doc:${doc.slug}`)}
              onChange={(on) => tick(`doc:${doc.slug}`, on)}
            >
              <span className="block text-body text-ink">I accept the {doc.title}</span>
              <a
                href={doc.href}
                target="_blank"
                rel="noreferrer"
                onClick={(event) => event.stopPropagation()}
                className="mt-0.5 inline-block text-meta font-medium text-brand-strong underline-offset-2 hover:underline"
              >
                Read it<span className="sr-only"> (opens in a new tab)</span>
                <ExternalLink aria-hidden className="ml-1 inline h-3 w-3 align-[-1px]" />
              </a>
            </ChoiceCard>
          ))}
          {docs.length > 0 && readiness.data?.acceptance_statement ? (
            <p className="text-meta text-ink-faint">{readiness.data.acceptance_statement}</p>
          ) : null}
          {pledgeOutstanding && pledge.data ? (
            <div>
              <ChoiceCard type="checkbox" name="pledge" value="pledge" checked={ticked.has("pledge")} onChange={(on) => tick("pledge", on)}>
                <span className="block text-body text-ink">I take the no-cold-calls pledge</span>
                <span className="mt-0.5 block text-meta text-ink-muted">
                  It only calls people who asked to hear from you.
                </span>
              </ChoiceCard>
              <details className="mt-1 px-4">
                <summary className="cursor-pointer py-2 text-meta font-medium text-brand-strong">Read the pledge</summary>
                <p className="whitespace-pre-line pb-2 text-meta text-ink-muted">{pledge.data.pledge_text}</p>
              </details>
            </div>
          ) : null}
          <ChoiceCard type="checkbox" name="mine" value="mine" checked={ticked.has("mine")} onChange={(on) => tick("mine", on)}>
            <span className="block text-body text-ink">The number below is my own</span>
            <span className="mt-0.5 block text-meta text-ink-muted">Test calls only ring a phone you own.</span>
          </ChoiceCard>
        </fieldset>
      )}

      <div>
        <label htmlFor={numberId} className="text-heading text-ink">
          Your mobile number
        </label>
        <div className="mt-2 flex items-stretch overflow-hidden rounded-md border border-line focus-within:ring-2 focus-within:ring-brand">
          <span aria-hidden className="flex items-center border-r border-line bg-ink/[0.03] px-3 text-body text-ink-muted">
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
            onChange={(event) => {
              setNumber(event.target.value);
              place.reset();
            }}
            className={`${FIELD} min-w-0 flex-1 rounded-none border-0 font-mono text-[16px] focus:ring-0`}
          />
        </div>
        {trial ? <p className="mt-2 text-meta text-ink-muted">{trialMinutesLine(trial)}</p> : null}
      </div>

      {!agent.engine_voice_id ? (
        <p role="status" className="text-meta text-warn">
          {agent.name} needs a voice before it can ring you.{" "}
          <Link href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=voice`)} className="font-medium underline underline-offset-2">
            Choose one
          </Link>
        </p>
      ) : null}
      {blocked ? (
        <p role="status" className="text-meta text-warn">
          {blocked}
        </p>
      ) : null}
      {place.data?.status === "blocked" ? (
        <p role="status" className="text-meta text-warn">
          {place.data.blocked_reason ?? "This test call was not allowed."}
        </p>
      ) : null}
      {[acceptAgreement.error, acceptPledge.error, prepare.error, place.error].map((error, index) =>
        error ? <ProblemNotice key={index} error={error} /> : null,
      )}
    </StepScreen>
  );
}

const WATCH_MS = 3000;

/** How a placed test call is going, from its own row, in the owner's words. */
const CALL_WORDS: Record<string, string> = {
  queued: "Ringing your phone…",
  ringing: "Ringing your phone…",
  in_progress: "You're talking to it",
  completed: "The call has ended",
  no_answer: "You didn't pick up",
  busy: "Your line was busy",
  failed: "The call didn't connect",
  voicemail: "It reached your voicemail",
};

/**
 * The call while it happens: its state and a timer from the moment it was answered. The
 * calls read is asked every few seconds while it is live, because the change stream slows to
 * a safety poll when healthy and the owner is watching this one call.
 */
export function CallLive({ call, onEnded }: { call: CallSummary | undefined; onEnded: (call: CallSummary) => void }) {
  const { session } = useClientRealm();
  const queries = useQueryClient();
  const status = call?.status ?? "queued";
  const live = status === "queued" || status === "ringing" || status === "in_progress";
  const talking = status === "in_progress";
  const [answeredAt, setAnsweredAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!live) return undefined;
    const timer = window.setInterval(
      () => void queries.invalidateQueries({ queryKey: ["calls", session.orgSlug] }),
      WATCH_MS,
    );
    return () => window.clearInterval(timer);
  }, [live, queries, session.orgSlug]);

  useEffect(() => {
    if (talking && answeredAt === null) setAnsweredAt(Date.now());
    if (!talking) return undefined;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, [talking, answeredAt]);

  useEffect(() => {
    if (call && !live) onEnded(call);
  }, [call, live, onEnded]);

  const seconds = answeredAt === null ? 0 : Math.max(0, Math.floor((now - answeredAt) / 1000));
  return (
    <div role="status" className="flex flex-col items-center gap-4 rounded-card border border-line bg-surface px-6 py-10 text-center">
      <span
        aria-hidden
        className={`relative flex h-16 w-16 items-center justify-center rounded-full ${talking ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"}`}
      >
        {live ? <span className="ring-pulse absolute inset-0 rounded-full" /> : null}
        <PhoneCall className="relative h-6 w-6" />
      </span>
      <p className="text-heading text-ink">{lookup(CALL_WORDS, status) ?? "Calling…"}</p>
      {talking ? <p className="text-title tabular-nums text-ink">{formatDuration(seconds)}</p> : null}
      {!talking && live ? <p className="text-meta text-ink-muted">Pick up when it rings.</p> : null}
    </div>
  );
}
