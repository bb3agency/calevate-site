"use client";

/**
 * PRACTICE CALL — hearing the agent on a real phone, in the agent's Training tab (D-825).
 * Phone only: there is no in-browser call (founder, 19 Oct 2026).
 *
 * Built only from what already exists, never a new request:
 *
 * - an account on a test-calls-only trial (D-697) can have THIS agent, once it is ready
 *   and whichever way it points (D-853), ring the owner's own
 *   phone, through the same `POST /v1/trial/calls` the dashboard's trial panel uses, with
 *   the same gate, daily cap and blocked reasons, which are the server's words;
 * - any other account hears an answering agent by ringing its own number, so the block
 *   says that and links to where the number is;
 * - an agent that can do neither yet says why in one line and what changes that, rather
 *   than offering a call the product cannot place.
 *
 * The number is owned by the screen (Training) so the one copilot declaration there can
 * offer it as a field.
 */

import Link from "next/link";
import { createContext, useContext, useState, type ReactNode } from "react";
import { PhoneOutgoing } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { DefaultCheckbox } from "@/components/callHandlingRows";
import { Section } from "@/components/console/section";
import { TryPart } from "@/components/improvement/TryPart";
import { FIELD_INLINE, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { canTestCall, isAnsweringNow } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel } from "@/lib/api/trialCalls";

import { TestCallFollow } from "../../../TestCallStatus";
import { TestCallTranscript } from "../../../TestCallTranscript";

export function TryIt({
  agent,
  slug,
  onTrial,
  number,
  onNumber,
  bare = false,
}: {
  agent: Agent;
  slug: string;
  /** The wallet's word that this account is on a test-calls-only trial. */
  onTrial: boolean;
  number: string;
  onNumber: (next: string) => void;
  bare?: boolean;
}) {
  let body;
  if (onTrial && canTestCall(agent)) {
    body = <TrialTestCall agent={agent} number={number} onNumber={onNumber} />;
  } else if (!onTrial && isAnsweringNow(agent) && agent.direction !== "outbound" && agent.inbound_number_count > 0) {
    body = <RingYourNumber slug={slug} />;
  } else {
    body = <NoCallYet agent={agent} slug={slug} onTrial={onTrial} />;
  }
  return <BareContext.Provider value={bare}>{body}</BareContext.Provider>;
}

/** Why no practice call can be placed yet, and the one move that changes it. */
function NoCallYet({ agent, slug, onTrial }: { agent: Agent; slug: string; onTrial: boolean }) {
  const { href } = useClientRealm();
  let line: string;
  let move: { href: string; label: string } | null = null;
  if (onTrial) {
    line = "Press Get it ready above, then test it here.";
  } else if (!isAnsweringNow(agent)) {
    line = "Switch on Taking calls above, then ring it.";
  } else if (agent.direction === "outbound") {
    line = "Its calls go out through campaigns. Try the chat.";
  } else {
    line = "Give it a phone number, then ring it.";
    move = { href: href(`/c/${slug}/phone-number`), label: "Get a number" };
  }
  return (
    <PracticeFrame
      description={line}
      action={
        move ? (
          <Link href={move.href} className={SECONDARY_BUTTON}>
            {move.label}
          </Link>
        ) : undefined
      }
    />
  );
}

/** Set by `bare`: the call half of the Training tab's Try it card, under a small title. */
const BareContext = createContext(false);

function PracticeFrame({
  description,
  action,
  children,
}: {
  description?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  const bare = useContext(BareContext);
  const Frame = bare ? TryPart : Section;
  return (
    <Frame headingLevel={3} title={bare ? "Call" : "Practice call"} description={description} action={action}>
      {children}
    </Frame>
  );
}

function RingYourNumber({ slug }: { slug: string }) {
  const { href } = useClientRealm();
  return (
    <PracticeFrame
      description="Ring your number from any phone. It answers."
      action={
        <Link href={href(`/c/${slug}/phone-number`)} className={SECONDARY_BUTTON}>
          See your number
        </Link>
      }
    />
  );
}

function TrialTestCall({
  agent,
  number,
  onNumber,
}: {
  agent: Agent;
  number: string;
  onNumber: (next: string) => void;
}) {
  const session = useClientSession();
  const panel = useTrialPanel(session);
  const place = usePlaceTrialCall(session);
  // The outcome is said under the form (calling now, the server's refusal, or the problem).
  const placeFeedback = useActionFeedback(place, { errorDisplay: "inline" });
  const [numberIsMine, setNumberIsMine] = useState(false);

  let body;
  if (panel.isPending) body = <Skeleton rows={1} label="Checking your test calls" />;
  else if (panel.isError) body = <ProblemNotice error={panel.error} onRetry={() => void panel.refetch()} />;
  else {
    const trial = panel.data;
    const ready = trial.can_call && number.trim() !== "";
    // A refused call is an answer said below, not a tick on the button.
    const callStatus =
      placeFeedback.status === "success" && place.data?.status === "blocked" ? "idle" : placeFeedback.status;
    body = (
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (ready && callStatus !== "pending") placeFeedback.run({ agentId: agent.id, number: number.trim(), numberIsMine });
        }}
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="block min-w-0">
            <span className="block text-meta text-ink-muted">Your phone number</span>
            <input
              value={number}
              onChange={(event) => {
                onNumber(event.target.value);
                place.reset();
              }}
              minLength={8}
              maxLength={20}
              inputMode="tel"
              autoComplete="tel"
              placeholder="+91 98765 43210"
              className={`${FIELD_INLINE} mt-1 w-56 max-w-full font-mono`}
            />
          </label>
          <ActionButton
            type="submit"
            variant="secondary"
            status={callStatus}
            pendingLabel="Calling…"
            successLabel="Calling"
            disabled={!ready}
          >
            <PhoneOutgoing aria-hidden className="h-4 w-4" />
            Ring my phone
          </ActionButton>
        </div>
        <DefaultCheckbox
          label="This number is my own. Test calls to it can ring at any hour."
          checked={numberIsMine}
          onChange={(on) => {
            setNumberIsMine(on);
            place.reset();
          }}
        />
        <p className="text-meta text-ink-muted">
          {trial.calls_today} of {trial.daily_cap} test calls used today.
        </p>
        {!trial.can_call && trial.blocked_reason ? (
          <p role="status" className="text-meta text-warn">
            {trial.blocked_reason}
          </p>
        ) : null}
        {place.data?.status === "queued" && place.data.call_id ? (
          <>
            <TestCallFollow
              callId={place.data.call_id}
              callerNumber={place.data.caller_number}
              paid={false}
              heading="This test call"
              link={false}
            />
            <TestCallTranscript callId={place.data.call_id} />
          </>
        ) : null}
        {place.data?.status === "blocked" && (
          <p role="status" className="text-meta text-warn">
            {place.data.blocked_reason ?? "This test call was not allowed."}
          </p>
        )}
        {place.error ? <ProblemNotice error={place.error} /> : null}
      </form>
    );
  }

  return (
    <PracticeFrame
      description={`${agent.name} rings you from a shared trial number.`}
    >
      {body}
    </PracticeFrame>
  );
}
