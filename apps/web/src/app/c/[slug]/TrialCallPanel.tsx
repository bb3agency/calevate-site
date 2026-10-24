"use client";

import Link from "next/link";
import { useState } from "react";
import { CheckCircle2, PhoneOutgoing } from "lucide-react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { UsageMeter } from "@/components/arc/usage-meter";
import {
  Card,
  FIELD_INLINE,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  formatCount,
  formatIST,
} from "@/components/ui";
import { DefaultCheckbox } from "@/components/callHandlingRows";
import { RowLink } from "@/components/console/checklist";
import { TEXT_ACTION } from "@/components/console/section";
import { canTestCall, isDeleted } from "@/lib/agentState";
import { useAgentLifecycle, useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, type TrialPanel } from "@/lib/api/trialCalls";

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
 * The trial comes WITH the dashboard read (`DashboardOut.trial`, D-787) rather than from its
 * own `GET /v1/trial`, so the card renders in the same paint as the rest of the dashboard:
 * a read of its own would be a second round trip, and a card that arrives late pushes the
 * dashboard down. Renders NOTHING for an account that is not on a trial — a placeholder on
 * every other dashboard would be noise — and the dashboard says its own read's failure.
 *
 * AFTER THE FIRST PAYMENT the same card offers the owner's PAID test calls (D-859,
 * `paid_test_calls`): from the agent's own number once it has one, from the shared trial
 * number until then (option A), billed like any call, with no trial words in it.
 */
export function TrialCallPanel({ slug, trial }: { slug: string; trial: TrialPanel | null | undefined }) {
  const { href } = useClientRealm();
  if (!trial?.on_trial && !trial?.paid_test_calls) return null;
  return (
    <TrialCallCard
      trial={trial}
      creditsHref={href(`/c/${slug}/billing?tab=credits`)}
      verifyHref={href(`/c/${slug}/verify-business`)}
      agentsHref={href(`/c/${slug}/agents`)}
      newAgentHref={href(`/c/${slug}/agents/first`)}
    />
  );
}

/** What is left of the free trial's days. */
function TrialDays({ trial }: { trial: TrialPanel }) {
  return (
    <div>
      <dt className={FIELD_LABEL}>Days left</dt>
      <dd className="mt-1 font-semibold text-ink">
        {trial.days_remaining === null || trial.days_remaining === undefined
          ? "Ended"
          : `${trial.days_remaining} ${trial.days_remaining === 1 ? "day" : "days"}`}
      </dd>
      {trial.ends_at ? <dd className="text-xs text-ink-muted">Ends {formatIST(trial.ends_at)} IST</dd> : null}
    </div>
  );
}

/** The free minutes as a meter; a trial with no minute limit draws no bar. */
function TrialMinutes({ trial }: { trial: TrialPanel }) {
  const free = trial.free_minutes ?? 0;
  const left = Math.max(0, Math.min(free, trial.minutes_left ?? free));
  return (
    <UsageMeter
      label="Free minutes"
      used={free - left}
      limit={free}
      usedText={formatCount(free - left)}
      limitText={formatCount(free)}
      caption={`${formatCount(left)} of ${formatCount(free)} minutes left`}
      noLimitText="No minute limit"
      hint={free > 0 && left === 0 ? "Your free minutes are used up. Add credit to keep calling." : undefined}
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
  agentsHref,
  newAgentHref,
}: {
  trial: TrialPanel;
  creditsHref: string;
  verifyHref: string;
  agentsHref: string;
  newAgentHref: string;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const place = usePlaceTrialCall(session);
  const [agentId, setAgentId] = useState("");
  const [number, setNumber] = useState("");
  const [numberIsMine, setNumberIsMine] = useState(false);

  // Every agent can be test-called, including a draft and one that only answers calls: a
  // draft is got ready first (the same `/prepare` the first run uses), and the server says in
  // its own words what stops that. After payment the call rings from the agent's own number
  // once it has one, and from the shared Calevate number until then (D-859, option A).
  const paid = trial.paid_test_calls === true;
  const dialers = agents.data?.filter((agent) => !isDeleted(agent));
  const chosen = agentId || (dialers !== undefined && dialers.length > 0 ? dialers[0].id : "");
  const chosenAgent = dialers?.find((agent) => agent.id === chosen);
  const prepare = useAgentLifecycle(session, chosen);
  // Both failures are said beside the form (ProblemNotice below), so neither is toasted.
  const prepareFeedback = useActionFeedback(prepare, { errorDisplay: "inline" });
  const placeFeedback = useActionFeedback(place, { errorDisplay: "inline" });
  const ready = trial.can_call && chosen !== "" && number.trim() !== "";
  /* One button runs both steps, so it shows the step in flight. A refusal (`blocked`) is an
     answer the status line gives, not a success to tick. */
  const callStatus: FeedbackStatus =
    prepareFeedback.status === "pending" || prepareFeedback.status === "error"
      ? prepareFeedback.status
      : placeFeedback.status === "success" && place.data?.status !== "queued"
        ? "idle"
        : placeFeedback.status;

  const call = async () => {
    if (chosenAgent && !canTestCall(chosenAgent)) await prepare.mutateAsync("prepare");
    placeFeedback.run({ agentId: chosen, number: number.trim(), numberIsMine });
  };

  return (
    <Card title={paid ? "Test calls" : "Your free trial"}>
      <div className="space-y-4">
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          {paid ? null : <TrialDays trial={trial} />}
          <div>
            <dt className={FIELD_LABEL}>Test calls today</dt>
            <dd className="mt-1 font-semibold text-ink">
              {trial.calls_today} of {trial.daily_cap}
            </dd>
          </div>
        </dl>
        {paid ? null : <TrialMinutes trial={trial} />}

        <p className="text-sm text-ink-muted">
          {paid
            ? "Ring your own phone from one of your agents. It calls from your own number once the agent has one, and from a shared Calevate number until then. Test calls are billed like any call. "
            : "Try your agent on a real phone: pick an agent, type an Indian number, and it calls that number from a shared Calevate number, opening with its usual greeting. "}
          Each test call ends after {minutesText(trial.max_call_seconds)}. The do-not-call list
          still applies, calls go out between 9am and 9pm unless the number is your own, and the
          agent always says it is an AI when asked.
        </p>
        {!trial.pledge_accepted && (
          <NoticeBox
            tone="warn"
            title="One step before your first test call"
            action={<RowLink href={verifyHref}>Verify your business</RowLink>}
          >
            Accept the no-cold-calls promise.
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
            if (ready && callStatus !== "pending") call().catch(() => undefined);
          }}
        >
          <label className="block w-full min-w-0 sm:w-auto">
            <span className={FIELD_LABEL}>Agent</span>
            {agents.error ? (
              <span className="mt-1 block text-sm text-ink-muted">
                Your agents did not load. Reload the page to try again.
              </span>
            ) : agents.data !== undefined && agents.data.length === 0 ? (
              <span className="mt-1 block text-sm text-ink-muted">
                You have no agents yet.{" "}
                <Link href={newAgentHref} className={TEXT_ACTION}>
                  Build your first agent
                </Link>
              </span>
            ) : (
              <select
                value={chosen}
                onChange={(event) => {
                  setAgentId(event.target.value);
                  place.reset();
                  prepare.reset();
                }}
                className={`${FIELD_INLINE} mt-1 w-full sm:w-auto sm:min-w-48`}
              >
                {dialers?.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {canTestCall(agent) ? agent.name : `${agent.name} (gets ready when you call)`}
                  </option>
                ))}
              </select>
            )}
          </label>
          <label className="block w-full min-w-0 sm:w-auto">
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
              className={`${FIELD_INLINE} mt-1 w-full font-mono sm:w-72`}
            />
          </label>
          <ActionButton
            type="submit"
            disabled={!ready}
            status={callStatus}
            pendingLabel={prepare.isPending ? "Getting it ready" : "Calling"}
            successLabel="Calling"
          >
            <PhoneOutgoing aria-hidden className="h-4 w-4" />
            Make a test call
          </ActionButton>
          <div className="basis-full">
            <DefaultCheckbox
              label="This number is my own. Test calls to it can ring at any hour."
              checked={numberIsMine}
              onChange={(on) => {
                setNumberIsMine(on);
                place.reset();
              }}
            />
          </div>
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
        {prepare.error && <ProblemNotice error={prepare.error} />}
        {place.error && <ProblemNotice error={place.error} />}
        {dialers !== undefined && dialers.length > 0 ? (
          <p className="text-xs text-ink-muted">
            Want to change what it says first?{" "}
            <Link href={agentsHref} className={TEXT_ACTION}>
              Your agents
            </Link>
          </p>
        ) : null}

        {paid ? null : (
          <NoticeBox
            tone="neutral"
            title="Ready to go live?"
            action={<RowLink href={creditsHref}>Add credit to go live</RowLink>}
            info="Adding credit ends the trial and opens business verification, your own phone number, answering calls and campaigns."
          />
        )}
      </div>
    </Card>
  );
}
