"use client";

/**
 * HEAR IT FOR YOURSELF — the "talk to your agent" moment, on the agent's own screen.
 *
 * Built only from what already exists, never a new request:
 *
 * - an account on a test-calls-only trial (D-697) can have THIS agent ring the owner's own
 *   phone, through the same `POST /v1/trial/calls` the dashboard's trial panel uses, with
 *   the same gate, daily cap and blocked reasons, which are the server's words;
 * - any other account hears an answering agent by ringing its own number, so the block
 *   says that and links to where the number is;
 * - an agent that can do neither yet (switched off, or a dial-out agent on a paid
 *   account, whose calls go out through campaigns) renders nothing rather than a
 *   promise the product cannot keep.
 *
 * The number is owned by the screen (`Overview`) so the one copilot declaration there can
 * offer it as a field.
 */

import Link from "next/link";
import { PhoneOutgoing } from "lucide-react";

import { Section } from "@/components/console/section";
import { FIELD_INLINE, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { canDialOut, isAnsweringNow } from "@/lib/agentState";
import type { Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { usePlaceTrialCall, useTrialPanel } from "@/lib/api/trialCalls";

import { TestCallTranscript } from "../../../TestCallTranscript";

export function TryIt({
  agent,
  slug,
  onTrial,
  number,
  onNumber,
}: {
  agent: Agent;
  slug: string;
  /** The wallet's word that this account is on a test-calls-only trial. */
  onTrial: boolean;
  number: string;
  onNumber: (next: string) => void;
}) {
  if (onTrial && canDialOut(agent)) {
    return <TrialTestCall agent={agent} number={number} onNumber={onNumber} />;
  }
  if (!onTrial && isAnsweringNow(agent) && agent.direction !== "outbound" && agent.inbound_number_count > 0) {
    return <RingYourNumber slug={slug} />;
  }
  return null;
}

function RingYourNumber({ slug }: { slug: string }) {
  const { href } = useClientRealm();
  return (
    <Section
      headingLevel={3}
      title="Hear it for yourself"
      description="Ring your number from any phone. This agent answers it the way your callers hear it."
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

  let body;
  if (panel.isPending) body = <Skeleton rows={1} label="Checking your test calls" />;
  else if (panel.isError) body = <ProblemNotice error={panel.error} onRetry={() => void panel.refetch()} />;
  else {
    const trial = panel.data;
    const ready = trial.can_call && number.trim() !== "" && !place.isPending;
    body = (
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) place.mutate({ agentId: agent.id, number: number.trim() });
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
              placeholder="9876543210"
              className={`${FIELD_INLINE} mt-1 w-56 max-w-full font-mono`}
            />
          </label>
          <button type="submit" disabled={!ready} className={SECONDARY_BUTTON}>
            <PhoneOutgoing aria-hidden className="h-4 w-4" />
            {place.isPending ? "Calling…" : "Ring my phone"}
          </button>
        </div>
        <p className="text-meta text-ink-muted">
          {trial.calls_today} of {trial.daily_cap} test calls used today.
        </p>
        {!trial.can_call && trial.blocked_reason ? (
          <p role="status" className="text-meta text-warn">
            {trial.blocked_reason}
          </p>
        ) : null}
        {place.data?.status === "queued" && (
          <p role="status" className="text-body font-medium text-brand-strong">
            Calling now. The call appears under Calls once it ends.
          </p>
        )}
        {place.data?.status === "queued" ? (
          <TestCallTranscript agentId={agent.id} placedAt={place.submittedAt} />
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
    <Section
      headingLevel={3}
      title="Hear it for yourself"
      description={`${agent.name} rings the number you type, from a shared trial number, and talks to you as it would to a caller.`}
    >
      {body}
    </Section>
  );
}
