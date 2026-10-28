"use client";

import Link from "next/link";
import { useState } from "react";
import { PhoneOutgoing } from "lucide-react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { UsageMeter } from "@/components/arc/usage-meter";
import {
  Card,
  FIELD_INLINE,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  formatCount,
  formatIST,
} from "@/components/ui";
import { DefaultCheckbox } from "@/components/callHandlingRows";
import { RowLink } from "@/components/console/checklist";
import { canTestCall, isDeleted } from "@/lib/agentState";
import { useAgentLifecycle, useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";
import { usePlaceTrialCall, useRecentTestCalls, type TrialPanel } from "@/lib/api/trialCalls";

import { EarlierTestCalls, TestCallFollow } from "./TestCallStatus";
import { HOME, TRIAL } from "./setup/_ui/copy";
import { Why } from "@/components/why";

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

/** A status chip: a fact at a glance, never a sentence (the card's days and calls today). */
function Chip({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <li title={title} className="rounded-full bg-surface-muted px-3 py-1 text-meta font-medium tabular-nums text-ink">
      {children}
    </li>
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
      caption={TRIAL.minutesLeft(formatCount(left), formatCount(free))}
      noLimitText="No minute limit"
      hint={free > 0 && left === 0 ? TRIAL.minutesUsedUp : undefined}
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

  // The call just placed is followed by its id; with none placed in this visit, the day's
  // newest test call is, so a reload or a trip to another page loses nothing (D-885).
  const recent = useRecentTestCalls(session);
  const placedId = place.data?.status === "queued" ? (place.data.call_id ?? null) : null;
  const newest = recent.data !== undefined && recent.data.length > 0 ? recent.data[0] : null;
  const followedId = placedId ?? newest?.id ?? null;
  const earlier = recent.data?.filter((row) => row.id !== followedId).slice(0, 2);

  return (
    <Card title={paid ? TRIAL.paidTitle : TRIAL.title}>
      <div className="space-y-4">
        <ul className="flex flex-wrap gap-2" aria-label="Your trial at a glance">
          {paid ? null : (
            <Chip title={trial.ends_at ? `Ends ${formatIST(trial.ends_at)} IST` : undefined}>
              {TRIAL.daysLeft(trial.days_remaining)}
            </Chip>
          )}
          <Chip>{TRIAL.callsToday(trial.calls_today, trial.daily_cap)}</Chip>
        </ul>
        {paid ? null : <TrialMinutes trial={trial} />}

        {/* The rules a test call keeps, one line; the whole of them behind a tap. */}
        <div>
          <p className="text-meta text-ink-muted">
            {paid && trial.own_number_max_call_seconds
              ? TRIAL.ownRules(minutesText(trial.own_number_max_call_seconds), minutesText(trial.max_call_seconds))
              : TRIAL.rules(minutesText(trial.max_call_seconds))}
          </p>
          <Why label={TRIAL.howItWorks}>
            <p>
              {paid
                ? "It rings from your agent's own number once it has one, and from a shared Calevate number until then. Test calls are billed like any call."
                : "Pick an agent and type an Indian number. It rings that number from a shared Calevate number and opens with its usual greeting."}
            </p>
            {trial.ends_at && !paid ? <p>Your trial ends {formatIST(trial.ends_at)} IST.</p> : null}
            <p>
              The do-not-call list still applies. Calls go out 9am to 9pm unless the number is your own. The
              agent always says it is an AI when asked.
            </p>
          </Why>
        </div>
        {!trial.pledge_accepted && (
          <NoticeBox
            tone="warn"
            title={TRIAL.pledgeTitle}
            action={
              <Link href={verifyHref} className={PRIMARY_BUTTON_SM}>
                {TRIAL.pledgeAction}
              </Link>
            }
          />
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
            <span className={FIELD_LABEL}>{TRIAL.agent}</span>
            {agents.error ? (
              <span className="mt-1 flex items-center gap-3 text-sm text-ink-muted">
                {TRIAL.agentsFailed}
                <button type="button" onClick={() => void agents.refetch()} className={SECONDARY_BUTTON_SM}>
                  {HOME.tryAgain}
                </button>
              </span>
            ) : agents.data !== undefined && agents.data.length === 0 ? (
              <span className="mt-1 flex flex-wrap items-center gap-3 text-sm text-ink-muted">
                {TRIAL.noAgents}
                <Link href={newAgentHref} className={SECONDARY_BUTTON_SM}>
                  {TRIAL.buildFirst}
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
            <span className={FIELD_LABEL}>{TRIAL.number}</span>
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
              label={TRIAL.ownNumber}
              checked={numberIsMine}
              onChange={(on) => {
                setNumberIsMine(on);
                place.reset();
              }}
            />
          </div>
        </form>

        {place.data?.status === "blocked" && (
          <p role="status" className="text-sm text-warn">
            {place.data.blocked_reason ?? TRIAL.blocked}
          </p>
        )}
        {prepare.error && <ProblemNotice error={prepare.error} />}
        {place.error && <ProblemNotice error={place.error} />}

        {followedId !== null ? (
          <TestCallFollow
            key={followedId}
            callId={followedId}
            callerNumber={followedId === placedId ? place.data?.caller_number : null}
            paid={paid}
            heading={followedId === placedId ? "This test call" : "Your last test call"}
          />
        ) : null}
        {recent.isError ? (
          <ProblemNotice error={recent.error} onRetry={() => void recent.refetch()} />
        ) : earlier !== undefined ? (
          <EarlierTestCalls calls={earlier} />
        ) : null}
        {dialers !== undefined && dialers.length > 0 ? (
          <Link href={agentsHref} className={SECONDARY_BUTTON_SM}>
            {TRIAL.editAgents}
          </Link>
        ) : null}

        {paid ? null : (
          <NoticeBox
            tone="neutral"
            title={TRIAL.goLive}
            action={<RowLink href={creditsHref}>{TRIAL.goLiveAction}</RowLink>}
            info="Adding credit ends the trial and opens business verification, your own phone number, answering calls and campaigns."
          />
        )}
      </div>
    </Card>
  );
}
