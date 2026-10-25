"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION } from "@/components/console/section";
import {
  FIELD_LABEL,
  ProblemNotice,
  Skeleton,
  formatDuration,
  formatIST,
  formatPhone,
  type NoticeTone,
} from "@/components/ui";
import { callOutcome, outcomeWords } from "@/lib/callReview";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { testCallIsLive, useTestCall, type TestCall } from "@/lib/api/trialCalls";
import { lookup } from "@/lib/lookup";

/**
 * WHERE A TEST CALL IS, ON THE CARD IT WAS PLACED FROM (D-885; founder, 25 Oct 2026: "I
 * don't see anything about it here — from where I actually called and what is the status").
 *
 * One call, followed by our id: calling, ringing, connected with a running clock, then how it
 * ended in words with what to do next. The full transcript is on the call's own page, which
 * the card links to rather than repeating.
 */

type State = { label: string; tone: NoticeTone; sentence: string };

/** Every status a call can have, in an owner's words, with the next step where there is one. */
const STATES: Record<TestCall["status"], State> = {
  queued: {
    label: "Calling",
    tone: "neutral",
    sentence: "Placing the call. Your phone should ring in a few seconds.",
  },
  ringing: {
    label: "Ringing",
    tone: "neutral",
    sentence: "Your phone is ringing. Pick up to talk to your agent.",
  },
  in_progress: {
    label: "Connected",
    tone: "ok",
    sentence: "You are talking to your agent. Hang up whenever you like.",
  },
  completed: {
    label: "Ended",
    tone: "ok",
    sentence: "The call has ended.",
  },
  no_answer: {
    label: "Not answered",
    tone: "warn",
    sentence: "Nobody picked up. Check the number and that the phone is on, then call again.",
  },
  busy: {
    label: "Line busy",
    tone: "warn",
    sentence: "The phone was busy or the call was declined. Try again in a minute.",
  },
  voicemail: {
    label: "Went to voicemail",
    tone: "warn",
    sentence: "The call reached voicemail, so your agent did not get to talk. Call again and pick up.",
  },
  failed: {
    label: "Did not go through",
    tone: "stop",
    sentence: "The call could not be connected. Check the number and try again.",
  },
};

/** An unknown status is shown as it came rather than hidden behind a guess. */
export function testCallState(status: string): State {
  const known = lookup(STATES, status);
  if (known) return known;
  const words = status.replace(/_/g, " ");
  return { label: words.charAt(0).toUpperCase() + words.slice(1), tone: "neutral", sentence: "" };
}

/** Seconds since `since`, ticking once a second while mounted. */
function useElapsed(since: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!since) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [since]);
  if (!since) return null;
  const start = Date.parse(since);
  return Number.isFinite(start) ? Math.max(0, Math.floor((now - start) / 1_000)) : null;
}

function LiveClock({ since }: { since: string }) {
  const elapsed = useElapsed(since);
  // `role="timer"` is not announced on every tick; the state line above it is.
  return (
    <span role="timer" className="font-mono tabular-nums">
      {formatDuration(elapsed)}
    </span>
  );
}

/** Where the call rings from, said once it is known; the number never breaks across lines. */
function FromLine({ number, paid, live }: { number: string | null | undefined; paid: boolean; live: boolean }) {
  const verb = live ? "It rings" : "It rang";
  if (number) {
    return (
      <>
        {` ${verb} from `}
        <span className="whitespace-nowrap">{formatPhone(number)}</span>.
      </>
    );
  }
  return paid ? <>{` ${verb} from your agent's own number.`}</> : null;
}

/**
 * The followed call. `callerNumber` is the placement's own answer, used until the call's row
 * says the same; `paid` words a call from the account's own line.
 */
export function TestCallFollow({
  callId,
  callerNumber,
  paid,
  heading,
  link = true,
}: {
  callId: string;
  callerNumber?: string | null;
  paid: boolean;
  heading: string;
  /** False where the transcript below already links to the call. */
  link?: boolean;
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const read = useTestCall(session, callId);

  if (read.isPending) return <Skeleton rows={2} label="Getting your test call" />;
  if (read.isError) return <ProblemNotice error={read.error} onRetry={() => void read.refetch()} />;

  const call = read.data;
  const state = testCallState(call.status);
  const live = testCallIsLive(call);
  const outcome = call.status === "completed" ? outcomeWords(call) : null;
  return (
    <section aria-label={heading} className="space-y-2 border-t border-line pt-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h3 className="text-body font-semibold text-ink">{heading}</h3>
        <StatusPill tone={state.tone}>{state.label}</StatusPill>
      </div>
      <p role="status" className="text-body text-ink">
        {state.sentence}
        <FromLine number={call.caller_number ?? callerNumber} paid={paid} live={live} />
      </p>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div className="min-w-0">
          <dt className={FIELD_LABEL}>Agent</dt>
          <dd className="mt-1 truncate text-ink">{call.agent_name ?? "Your agent"}</dd>
        </div>
        <div>
          <dt className={FIELD_LABEL}>Placed</dt>
          <dd className="mt-1 text-ink">{formatIST(call.placed_at)}</dd>
        </div>
        {call.status === "in_progress" && call.started_at ? (
          <div>
            <dt className={FIELD_LABEL}>Talking for</dt>
            <dd className="mt-1 text-ink">
              <LiveClock since={call.started_at} />
            </dd>
          </div>
        ) : !live ? (
          <div>
            <dt className={FIELD_LABEL}>Length</dt>
            <dd className="mt-1 font-mono tabular-nums text-ink">{formatDuration(call.duration_s)}</dd>
          </div>
        ) : null}
        {outcome ? (
          <div className="min-w-0">
            <dt className={FIELD_LABEL}>How it went</dt>
            <dd className="mt-1 text-ink">{outcome}</dd>
          </div>
        ) : null}
      </dl>
      {call.status === "completed" ? (
        <p className="text-meta text-ink-muted">
          {call.headline ?? "A short summary appears here once the call has been read."}
        </p>
      ) : null}
      {live || !link ? null : (
        <Link href={href(`/c/${session.orgSlug}/calls/${call.id}`)} className={TEXT_ACTION}>
          Open this call
        </Link>
      )}
    </section>
  );
}

/** The day's other test calls, one line each, so returning to the dashboard still shows them. */
export function EarlierTestCalls({ calls }: { calls: TestCall[] }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  if (calls.length === 0) return null;
  return (
    <section aria-label="Earlier test calls today" className="space-y-2">
      <h3 className={FIELD_LABEL}>Earlier today</h3>
      <ul className="divide-y divide-line">
        {calls.map((call) => (
          <li key={call.id} className="flex items-center gap-x-4 py-2 text-sm">
            <div className="min-w-0 flex-1">
              <span className="block truncate text-ink">{call.agent_name ?? "Your agent"}</span>
              <span className="block text-meta text-ink-muted">{formatIST(call.placed_at)}</span>
            </div>
            <span className="text-right text-ink">
              {testCallIsLive(call) ? testCallState(call.status).label : callOutcome(call).words}
            </span>
            <span className="font-mono tabular-nums text-ink-muted">{formatDuration(call.duration_s)}</span>
            <Link
              href={href(`/c/${session.orgSlug}/calls/${call.id}`)}
              className={TEXT_ACTION}
              aria-label={`Open the test call placed ${formatIST(call.placed_at)}`}
            >
              Open
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
