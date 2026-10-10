"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, PhoneOutgoing, ShieldAlert } from "lucide-react";

import {
  Card,
  FIELD_INLINE,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
} from "@/components/ui";
import { canDialOut } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel, type TrialPanel } from "@/lib/api/trialCalls";
import { useShellWallet } from "@/lib/api/wallet";

import { TestCallTranscript } from "./TestCallTranscript";

/**
 * THE FREE TRIAL, on the dashboard (D-697): what is left of it, a test call, and the one
 * step that ends it.
 *
 * A trial account builds agents and places test calls to a number it types, from a shared
 * Calevate number, and nothing else. Everything a business goes live with — verifying the
 * business, its own phone number, answering calls and calling its leads — opens once it
 * adds credit, and the panel says so in that order.
 *
 * Renders NOTHING while the read is in flight and for an account that is not on a trial:
 * this panel is for the few accounts on a trial, and a placeholder on every other
 * dashboard would be noise. A failed read is said, because a trial account that cannot see
 * its panel cannot place a test call.
 */
export function TrialCallPanel({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  // Asked only of an account the shell's wallet read says is on a test-calls-only trial, so
  // every other dashboard sends no request for it.
  const onTrial = useShellWallet(session)?.trial?.test_calls_only === true;
  const panel = useTrialPanel(session, onTrial);
  if (panel.error) {
    return <ProblemNotice error={panel.error} onRetry={() => void panel.refetch()} />;
  }
  if (!onTrial || panel.isLoading || panel.data === undefined || !panel.data.on_trial) return null;
  return (
    <TrialCallCard
      trial={panel.data}
      creditsHref={href(`/c/${slug}/billing?tab=credits`)}
      verifyHref={href(`/c/${slug}/verify-business`)}
    />
  );
}

function minutesText(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}

/** The card itself, separate from the read so it can be tested with a fixed answer. */
export function TrialCallCard({
  trial,
  creditsHref,
  verifyHref,
}: {
  trial: TrialPanel;
  creditsHref: string;
  verifyHref: string;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const place = usePlaceTrialCall(session);
  const [agentId, setAgentId] = useState("");
  const [number, setNumber] = useState("");

  const dialers = agents.data?.filter(canDialOut);
  const chosen = agentId || (dialers !== undefined && dialers.length > 0 ? dialers[0].id : "");
  const ready = trial.can_call && chosen !== "" && number.trim() !== "" && !place.isPending;

  return (
    <Card title="Your free trial">
      <div className="space-y-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className={FIELD_LABEL}>Days left</dt>
            <dd className="mt-1 font-semibold text-ink">
              {trial.days_remaining === null || trial.days_remaining === undefined
                ? "Ended"
                : `${trial.days_remaining} ${trial.days_remaining === 1 ? "day" : "days"}`}
            </dd>
          </div>
          <div>
            <dt className={FIELD_LABEL}>Free minutes left</dt>
            <dd className="mt-1 font-semibold text-ink">
              {trial.free_minutes === null || trial.free_minutes === undefined
                ? "No minute limit"
                : `${trial.minutes_left ?? trial.free_minutes} of ${trial.free_minutes}`}
            </dd>
          </div>
          <div>
            <dt className={FIELD_LABEL}>Test calls today</dt>
            <dd className="mt-1 font-semibold text-ink">
              {trial.calls_today} of {trial.daily_cap}
            </dd>
          </div>
        </dl>

        <p className="text-sm text-ink-muted">
          Try your agent on a real phone: pick an agent, type an Indian number, and it calls
          that number from a shared Calevate number. Each test call ends after{" "}
          {minutesText(trial.max_call_seconds)}. The do-not-call list and calling hours (9am to
          9pm) still apply, and the agent always says it is an AI when asked.
        </p>

        {!trial.pledge_accepted && (
          <NoticeBox
            tone="warn"
            icon={<ShieldAlert aria-hidden className="h-4 w-4" />}
            title="One step before your first test call"
          >
            Accept the no-cold-calls promise on{" "}
            <Link href={verifyHref} className="font-semibold underline underline-offset-2">
              Verify your business
            </Link>
            .
          </NoticeBox>
        )}

        {trial.blocked_reason && trial.pledge_accepted && (
          <p role="status" className="text-sm text-warn">
            {trial.blocked_reason}
          </p>
        )}

        <form
          className="flex flex-wrap items-end gap-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (ready) place.mutate({ agentId: chosen, number: number.trim() });
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>Agent</span>
            {agents.error ? (
              <span className="mt-1 block text-sm text-ink-muted">
                Your agents did not load. Reload the page to try again.
              </span>
            ) : dialers !== undefined && dialers.length === 0 ? (
              <span className="mt-1 block text-sm text-ink-muted">
                Switch on an agent that places calls first.
              </span>
            ) : (
              <select
                value={chosen}
                onChange={(event) => {
                  setAgentId(event.target.value);
                  place.reset();
                }}
                className={`${FIELD_INLINE} mt-1 sm:min-w-48`}
              >
                {dialers?.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            )}
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Number to call</span>
            <input
              value={number}
              onChange={(event) => {
                setNumber(event.target.value);
                place.reset();
              }}
              minLength={8}
              maxLength={20}
              inputMode="tel"
              autoComplete="off"
              placeholder="9876543210 or +919876543210"
              className={`${FIELD_INLINE} mt-1 w-56 font-mono`}
            />
          </label>
          <button type="submit" disabled={!ready} className={PRIMARY_BUTTON}>
            <PhoneOutgoing aria-hidden className="h-4 w-4" />
            {place.isPending ? "Calling…" : "Make a test call"}
          </button>
        </form>

        {place.data?.status === "queued" && (
          <p role="status" className="flex items-center gap-2 text-sm font-semibold text-brand-strong">
            <CheckCircle2 aria-hidden className="h-4 w-4" />
            Calling now. The call appears under Calls once it ends.
          </p>
        )}
        {place.data?.status === "queued" && place.variables ? (
          <TestCallTranscript agentId={place.variables.agentId} placedAt={place.submittedAt} />
        ) : null}
        {place.data?.status === "blocked" && (
          <p role="status" className="text-sm text-warn">
            {place.data.blocked_reason ?? "This test call was not allowed."}
          </p>
        )}
        {place.error && <ProblemNotice error={place.error} />}

        <NoticeBox tone="neutral" title="Ready to go live?">
          <p>
            Adding credit ends the trial and opens, in order: verifying your business, your own
            phone number, then live calls, with your agents answering your customers and
            calling your leads.
          </p>
          <Link
            href={creditsHref}
            className="mt-2 inline-block font-semibold underline underline-offset-2"
          >
            Add credit to go live
          </Link>
        </NoticeBox>
      </div>
    </Card>
  );
}
