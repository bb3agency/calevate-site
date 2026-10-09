"use client";

import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { Card, ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useCampaignNumbers, type CampaignNumber } from "@/lib/api/campaigns";
import { useOwnNumbersStatus } from "@/lib/api/ownNumbers";
import { useClientSession } from "@/lib/api/session";

import { BuyNumber } from "./BuyNumber";
import { NumberAssignment } from "./NumberAssignment";
import { OwnNumbersJourney, ReleaseOwnNumber } from "./OwnNumbers";
import { SenderAttestation } from "./SenderAttestation";
import { TrialLockNotice } from "../TrialLockNotice";

/**
 * THE NUMBERS THIS BUSINESS ANSWERS AND CALLS FROM (D-537).
 *
 * PRIMARY JOB: see each number, what it is doing, and put it on an agent.
 *
 * Two kinds of number, told apart by the server's own `supplied_by_us`: one bought for
 * this account is one to forward TO; one the account manager recorded is what the agents
 * call out from and must not be forwarded anywhere. Those are opposite instructions, so
 * they are separate sections. Both are Calevate's to provide on our own telephony account,
 * and no provider is named to a client (white label, founder 6 Oct 2026): neither section
 * may tell a client they hold a connection with an operator of their own.
 *
 * Each number's agent choice and its sender confirmation sit open on the page, never in a
 * drawer: the confirmation is a TRAI-facing compliance control, and UX-DOCTRINE §8.7 keeps
 * those out of anything that hides them. `answerable` is said in plain words, because a
 * client who forwards their line to a number that cannot answer sends every caller into
 * silence.
 *
 * No price and no operator-specific forwarding steps: neither is a verified fact (the
 * pricing decision is OPERATIONS §2 gate 26, and the steps differ per operator), so the
 * screen says what to ASK for, in the words an Indian operator uses.
 */
export function PhoneNumberScreen() {
  const session = useClientSession();
  const numbers = useCampaignNumbers(session);
  const rows = numbers.data;
  const ours = rows?.filter((number) => number.supplied_by_us) ?? [];
  const theirs = rows?.filter((number) => !number.supplied_by_us) ?? [];
  const none = rows !== undefined && rows.length === 0;
  // `NumberOut` does not carry the agent's direction, so it is read from the agent list
  // (the same query `NumberAssignment` already makes). An agent that only makes calls never
  // answers a number, so "we are still connecting it" would be false for it; until the list
  // is read neither sentence is said.
  const agents = useAgents(session);
  const outboundOnly = (number: CampaignNumber): boolean =>
    agents.data?.some((agent) => agent.id === number.agent_id && agent.direction === "outbound") ===
    true;
  const waiting = (number: CampaignNumber): boolean =>
    !number.answerable && number.agent_id != null && agents.data !== undefined && !outboundOnly(number);
  // Where numbers are rented in the business's own calling account (D-693), the three-step
  // journey replaces the older purchase panel; elsewhere the older panel stays.
  const own = useOwnNumbersStatus(session);
  const ownNumbers = own.data?.available === true;
  const getNumber = own.isLoading ? (
    <Skeleton rows={3} label="Loading how to get a number" />
  ) : own.error || !own.data ? (
    <ProblemNotice error={own.error} onRetry={() => void own.refetch()} />
  ) : ownNumbers ? (
    <OwnNumbersJourney status={own.data} />
  ) : (
    <BuyNumber />
  );

  return (
    <div className="space-y-6 pb-12">
      <PageHeader description="The numbers your agents answer and call from." />
      <TrialLockNotice lock="numbers" />

      {/* With no number yet, getting one IS the job, so it comes first. */}
      {none && getNumber}

      {numbers.error && <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />}
      {numbers.isLoading || !rows ? (
        !numbers.error && <Skeleton rows={3} />
      ) : none ? (
        <p className="text-sm text-ink-muted">No number set up yet.</p>
      ) : (
        <>
          {ours.length > 0 && (
            <section className="space-y-3">
              <h2 className="flex items-center gap-1 text-[15px] font-semibold text-ink">
                Point your existing phone at this number
                <InfoTip label="How to forward your line">
                  Ask your telephone operator to set up conditional call forwarding on your
                  business line — forward a call when it is busy, unanswered, or out of reach —
                  and give them this number as the destination. Keep advertising your own
                  number; nobody needs to know this one.
                </InfoTip>
              </h2>
              <p className="text-sm text-ink-muted">
                Ask your operator for <span className="font-medium text-ink">conditional call forwarding</span> to
                the number below.
              </p>
              {/* `answerable` needs an agent on the number AND our connection of it at the
                  carrier. Only the first is the client's to fix, so the two get different
                  sentences: "nothing for you to do" beside a number with no agent would
                  leave it silent for good. */}
              {ours.some((number) => !number.answerable && !number.agent_id) && (
                <p className="text-sm text-ink-muted">
                  A number with no agent on it cannot take calls. Choose the agent that should
                  answer it on its card below, and wait until it says <em>Ready to answer</em>{" "}
                  before you set the forwarding up, or callers will reach silence.
                </p>
              )}
              {ours.some((number) => !number.answerable && outboundOnly(number)) && (
                <p className="text-sm text-ink-muted">
                  A number on an agent that only makes calls places calls but does not answer
                  them. To have it answer, choose an agent that answers calls on its card below,
                  or change that agent&apos;s <em>What it does</em> to <em>Answer calls</em> or{" "}
                  <em>Both</em>. Wait until it says <em>Ready to answer</em> before you set the
                  forwarding up, or callers will reach silence.
                </p>
              )}
              {ours.some(waiting) && (
                <p className="text-sm text-ink-muted">
                  A number with an agent on it is not ready to take calls yet — we are still
                  connecting it. Please wait until it says <em>Ready to answer</em> before you
                  set the forwarding up, or callers will reach silence. There is nothing for
                  you to do here.
                </p>
              )}
              {ours.map((number) => (
                <NumberCard
                  key={number.id}
                  number={number}
                  releasable={ownNumbers && number.releasable === true}
                  outboundOnly={outboundOnly(number)}
                />
              ))}
            </section>
          )}
          {theirs.length > 0 && (
            <section className="space-y-3">
              <h2 className="flex items-center gap-1 text-[15px] font-semibold text-ink">
                Numbers your agents call out from
                <InfoTip label="Where these numbers come from">
                  Your account manager set these numbers up for you. Calevate provides them on
                  our own telephony account, so there is no operator account for you to open or
                  manage.
                </InfoTip>
              </h2>
              <p className="text-sm text-ink-muted">
                Do not forward these anywhere — they are what your agents call out from.
              </p>
              {theirs.map((number) => (
                <NumberCard key={number.id} number={number} releasable={ownNumbers && number.releasable === true} />
              ))}
            </section>
          )}
        </>
      )}

      {!none && getNumber}
    </div>
  );
}

/** One number: what it is, whether it is live, which agent uses it, and its sender status. */
function NumberCard({
  number,
  releasable,
  outboundOnly = false,
}: {
  number: CampaignNumber;
  releasable: boolean;
  /** On an agent that only makes calls, so it cannot answer whatever else is in place. */
  outboundOnly?: boolean;
}) {
  const status = number.supplied_by_us
    ? number.answerable
      ? { text: "Ready to answer", tone: "bg-brand-soft text-brand-strong" }
      : !number.agent_id
        ? { text: "No agent on it yet", tone: "border border-line text-ink-muted" }
        : outboundOnly
          ? { text: "Makes calls only", tone: "border border-line text-ink-muted" }
          : { text: "Not ready yet", tone: "border border-line text-ink-muted" }
    : number.dlt_status === "registered"
      ? { text: "Registered for calling out", tone: "bg-ink/[0.06] text-ink" }
      : { text: "Registration still in progress", tone: "border border-line text-ink-muted" };
  return (
    <Card density="compact">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {/* The client's OWN number, not a called party's (hard rule 6 is about those). */}
          <p className="font-mono text-base font-semibold tabular-nums text-ink">{formatPhone(number.e164)}</p>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${status.tone}`}>{status.text}</span>
          <span className="text-xs text-ink-faint">{number.series} series</span>
        </div>
        <NumberAssignment
          numberId={number.id}
          series={number.series}
          currentAgentId={number.agent_id ?? null}
          currentDirection={number.direction}
        />
        <SenderAttestation numberId={number.id} />
        {releasable && <ReleaseOwnNumber numberId={number.id} e164={number.e164} />}
      </div>
    </Card>
  );
}
