"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PhoneCall, PhoneIncoming } from "lucide-react";

import { FIELD_INLINE, PRIMARY_BUTTON, ProblemNotice, Skeleton, formatDuration } from "@/components/ui";
import { useAgentLifecycle, type Agent } from "@/lib/api/agents";
import type { CallSummary } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel } from "@/lib/api/trialCalls";
import { lookup } from "@/lib/lookup";

/**
 * THE FINALE: "Your agent calls you" (D-854).
 *
 * One number and one button. On a trial account the button first gets a draft agent ready
 * (`POST /v1/agents/{id}/prepare`, the agent page's own "Get it ready": on the calling system,
 * taking no calls) and then asks `POST /v1/trial/calls` to ring the number, so every gate
 * that endpoint keeps (the daily cap, the trial's minutes, its blocked reasons) is the one
 * that answers. Its refusal is shown in the server's words.
 *
 * The call is then followed on this agent's newest call row: ringing, on the call, and how it
 * ended, with a link to the call's own page. An account that is not on a trial has no test
 * line, so it is sent to try the agent in the chat on its Training tab instead.
 */
export function FirstCall({ agent, calls }: { agent: Agent | null; calls: readonly CallSummary[] | undefined }) {
  const { session, href } = useClientRealm();
  const panel = useTrialPanel(session);

  if (agent === null) {
    return (
      <Finale>
        <p className="text-meta text-ink-muted">Once it has a job, it can ring your phone so you hear it.</p>
      </Finale>
    );
  }
  if (panel.isPending) return <Skeleton rows={1} label="Checking your test calls" />;
  if (panel.isError) return <ProblemNotice error={panel.error} onRetry={() => void panel.refetch()} />;
  if (!panel.data.on_trial) {
    return (
      <Finale>
        <p className="text-meta text-ink-muted">Hear how it answers by trying it in the chat.</p>
        <Link
          href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=training`)}
          className={`${PRIMARY_BUTTON} mt-3`}
        >
          Try it in the chat
        </Link>
      </Finale>
    );
  }
  return <RingMe agent={agent} calls={calls} />;
}

function Finale({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <h3 className="flex items-center gap-2 text-body font-semibold text-ink">
        <PhoneIncoming aria-hidden className="h-4 w-4 text-brand-strong" />
        Your agent calls you
      </h3>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function RingMe({ agent, calls }: { agent: Agent; calls: readonly CallSummary[] | undefined }) {
  const { session } = useClientRealm();
  const panel = useTrialPanel(session);
  const place = usePlaceTrialCall(session);
  const prepare = useAgentLifecycle(session, agent.id);
  const [number, setNumber] = useState("");
  const trial = panel.data;
  const busy = prepare.isPending || place.isPending;
  /* Pressable while the agent still needs getting ready: the trial line may name a ready
     agent as the thing it is missing, and getting this one ready is what the press does. */
  const pressable = number.trim().length >= 8 && !busy && (trial?.can_call === true || !agent.published);

  const ring = async () => {
    if (!agent.published) {
      await prepare.mutateAsync("prepare");
      const fresh = await panel.refetch();
      if (fresh.data?.can_call !== true) return;
    }
    place.mutate({ agentId: agent.id, number: number.trim() });
  };

  const placed = place.data?.status === "queued";
  const call = placed ? calls?.find((row) => Date.parse(row.started_at ?? "") >= place.submittedAt - 60_000) : undefined;

  return (
    <Finale>
      {placed ? (
        <CallProgress call={call} />
      ) : (
        <form
          noValidate
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (pressable) void ring().catch(() => undefined);
          }}
        >
          <p className="text-meta text-ink-muted">Type your mobile number. It rings you from a trial line and talks to you as it would to a caller.</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="block min-w-0 flex-1 basis-44">
              <span className="sr-only">Your mobile number</span>
              <input
                value={number}
                onChange={(event) => {
                  setNumber(event.target.value);
                  place.reset();
                }}
                maxLength={20}
                inputMode="tel"
                autoComplete="tel"
                placeholder="+91 98765 43210"
                className={`${FIELD_INLINE} w-full font-mono text-[16px]`}
              />
            </label>
            <button type="submit" disabled={!pressable} className={PRIMARY_BUTTON}>
              <PhoneCall aria-hidden className="h-4 w-4" />
              {prepare.isPending ? "Getting it ready…" : place.isPending ? "Calling…" : "Call me"}
            </button>
          </div>
          {trial ? (
            <p className="text-meta text-ink-faint">
              {trial.calls_today} of {trial.daily_cap} test calls used today.
            </p>
          ) : null}
          {trial && !trial.can_call && agent.published && trial.blocked_reason ? (
            <p role="status" className="text-meta text-warn">
              {trial.blocked_reason}
            </p>
          ) : null}
          {place.data?.status === "blocked" ? (
            <p role="status" className="text-meta text-warn">
              {place.data.blocked_reason ?? "This test call was not allowed."}
            </p>
          ) : null}
          {prepare.error ? <ProblemNotice error={prepare.error} /> : null}
          {place.error ? <ProblemNotice error={place.error} /> : null}
        </form>
      )}
    </Finale>
  );
}

const WATCH_MS = 3000;

/** How a placed test call is going, from its own row, in the owner's words. */
const CALL_WORDS: Record<string, string> = {
  queued: "Ringing your phone…",
  ringing: "Ringing your phone…",
  in_progress: "You're on the call",
  completed: "Your first call is done",
  no_answer: "You didn't pick up",
  busy: "Your line was busy",
  failed: "The call didn't connect",
  voicemail: "It reached your voicemail",
};

function CallProgress({ call }: { call: CallSummary | undefined }) {
  const { session, href } = useClientRealm();
  const status = call?.status ?? "queued";
  const live = status === "queued" || status === "ringing" || status === "in_progress";
  /* The change stream slows the calls read to a safety poll while it is healthy; the owner
     is watching this one call, so it is read every few seconds until it ends. */
  const queries = useQueryClient();
  useEffect(() => {
    if (!live) return undefined;
    const timer = window.setInterval(
      () => void queries.invalidateQueries({ queryKey: ["calls", session.orgSlug] }),
      WATCH_MS,
    );
    return () => window.clearInterval(timer);
  }, [live, queries, session.orgSlug]);
  const connected = status === "completed" || status === "in_progress";
  return (
    <div className="space-y-2" role="status">
      <p className="flex items-center gap-3 text-body font-medium text-ink">
        <span aria-hidden className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${connected ? "bg-brand-strong text-white" : "bg-brand-soft text-brand-strong"}`}>
          {live ? <span className="ring-pulse absolute inset-0 rounded-full" /> : null}
          <PhoneCall className="relative h-4 w-4" />
        </span>
        {lookup(CALL_WORDS, status) ?? "Calling…"}
      </p>
      {call && !live ? (
        <p className="text-meta text-ink-muted">
          {status === "completed" ? `It lasted ${formatDuration(call.duration_s)}. ` : ""}
          <Link href={href(`/c/${session.orgSlug}/calls/${call.id}`)} className="font-medium text-brand-strong underline-offset-2 hover:underline">
            Open the call
          </Link>{" "}
          to hear it and read what was said.
        </p>
      ) : null}
    </div>
  );
}
