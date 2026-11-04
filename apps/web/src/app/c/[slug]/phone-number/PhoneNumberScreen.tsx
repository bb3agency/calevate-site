"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { InfoTip } from "@/components/console/infoTip";
import { SegmentedControl, type SegmentedOption } from "@/components/interior/segmented-control";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { ProblemNotice, SECONDARY_BUTTON, Skeleton, formatPhone } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useCampaignNumbers, type CampaignNumber } from "@/lib/api/campaigns";
import { useOwnNumbersStatus } from "@/lib/api/ownNumbers";
import { useClientRealm } from "@/lib/api/session";
import { EXISTING_SECTION, FROM_CALEVATE_SECTION } from "@/lib/phoneNumbersSection";

import { BuyNumber } from "./BuyNumber";
import { CallsAtOnce, ExistingNumberSection, SaveNumber } from "./ExistingNumber";
import { NumberAssignment } from "./NumberAssignment";
import { OwnNumbersJourney, ReleaseOwnNumber } from "./OwnNumbers";
import { TrialLockNotice } from "../TrialLockNotice";
import { HeldNumberLine } from "../HeldNumberNotice";
import { StatusPill } from "@/components/console/statusPill";

/**
 * PHONE NUMBERS: the numbers this business answers and calls from, in two sections of one
 * screen. "Numbers from Calevate" are the ones we provide (D-537); "Your existing number" is
 * the line callers already know, forwarded to one of them (D-746). One screen, because a
 * client setting up forwarding needs both halves and used to find them under two sidebar
 * entries with near-identical names. The section is in the address (`?section=existing`), so
 * the retired forwarding screen's redirect, a bookmark and "Get codes and test" all open the
 * right half.
 */
export function PhoneNumberScreen() {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const params = useSearchParams();
  const section = params.get("section") === EXISTING_SECTION ? EXISTING_SECTION : FROM_CALEVATE_SECTION;
  const sectionHref = (to: string) =>
    href(`/c/${session.orgSlug}/phone-number${to === FROM_CALEVATE_SECTION ? "" : `?section=${to}`}`);

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      <PageHeader description="The numbers your agents answer and call from." />
      <SegmentedControl
        label="Which numbers"
        options={SECTIONS}
        value={section}
        onValueChange={(to) => router.replace(sectionHref(to), { scroll: false })}
        fill
      />
      {section === EXISTING_SECTION ? (
        <ExistingNumberSection fromCalevateHref={sectionHref(FROM_CALEVATE_SECTION)} />
      ) : (
        <CalevateNumbers existingHref={sectionHref(EXISTING_SECTION)} />
      )}
    </div>
  );
}

/**
 * NUMBERS FROM CALEVATE (D-537). PRIMARY JOB: see each number, what it is doing, and put it
 * on an agent.
 *
 * Two kinds of number, told apart by the server's own `supplied_by_us`: one bought for
 * this account is one to forward TO; one the account manager recorded is what the agents
 * call out from and must not be forwarded anywhere. Those are opposite instructions, so
 * they are separate sections. Both are Calevate's to provide on our own telephony account,
 * and no provider is named to a client (white label, founder 6 Oct 2026): neither section
 * may tell a client they hold a connection with an operator of their own.
 *
 * Each number's agent choice sits open on the page, never in a drawer. `answerable` is
 * said in plain words, because a client who forwards their line to a number that cannot
 * answer sends every caller into silence.
 *
 * No price and no operator-specific forwarding steps: neither is a verified fact (the
 * pricing decision is OPERATIONS §2 gate 26, and the steps differ per operator), so the
 * screen says what to ASK for, in the words an Indian operator uses.
 */
function CalevateNumbers({ existingHref }: { existingHref: string }) {
  const { session } = useClientRealm();
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
    !number.held && !number.answerable && number.agent_id != null && agents.data !== undefined && !outboundOnly(number);
  // Where numbers are rented in the business's own calling account (D-693), the three-step
  // journey replaces the older purchase panel; elsewhere the older panel stays.
  const own = useOwnNumbersStatus(session);
  const ownNumbers = own.data?.available === true;
  const getNumber = own.isLoading ? (
    <Skeleton rows={3} label="Loading how to get a number" />
  ) : own.error || !own.data ? (
    <ProblemNotice error={own.error ?? new Error("Your number options did not load.")} onRetry={() => void own.refetch()} />
  ) : ownNumbers ? (
    <OwnNumbersJourney status={own.data} />
  ) : (
    <BuyNumber />
  );

  return (
    <div className="space-y-6">
      {/* The own-number flow says the trial's state and offers credit itself; a second
          notice above it would be a second primary action for the same step. */}
      {own.data?.available === false && <TrialLockNotice lock="numbers" />}
      {/* With no number yet, getting one IS the job, so it comes first. */}
      {none && getNumber}

      {numbers.error && <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />}
      {numbers.isLoading || !rows ? (
        !numbers.error && <Skeleton rows={3} />
      ) : none ? (
        <p className="text-body text-ink-muted">No number set up yet.</p>
      ) : (
        <>
          {ours.length > 0 && (
            <Section
              title="Forward your phone to this number"
              info={
                <p>
                  Your existing phone forwards calls to this number. Keep advertising your own
                  number; nobody needs to know this one.
                </p>
              }
            >
              <div className="space-y-3">
                <Link
                  href={existingHref}
                  scroll={false}
                  className={`${SECONDARY_BUTTON} w-full justify-center sm:w-auto`}
                >
                  Get codes and test
                </Link>
                {/* `answerable` needs an agent on the number AND our connection of it at the
                    carrier. Only the first is the client's to fix, so the two get different
                    lines: "nothing for you to do" beside a number with no agent would leave it
                    silent for good. Each says what to do; the why is behind the ⓘ. */}
                {ours.some((number) => !number.held && !number.answerable && !number.agent_id) && (
                  <WaitLine why="A number with no agent cannot take calls. Forward calls only once it says Ready to answer.">
                    Pick an agent below before you forward.
                  </WaitLine>
                )}
                {ours.some((number) => !number.held && !number.answerable && outboundOnly(number)) && (
                  <WaitLine why="An agent that only makes calls does not answer them. Choose an agent that answers calls, or set that agent's What it does to Answer calls or Both.">
                    Its agent only calls out. Pick one that answers.
                  </WaitLine>
                )}
                {ours.some(waiting) && (
                  <WaitLine why="We are still connecting it. Forward calls only once it says Ready to answer, or callers hear silence.">
                    Still connecting. Nothing to do yet.
                  </WaitLine>
                )}
                {ours.map((number) => (
                  <NumberCard
                    key={number.id}
                    number={number}
                    releasable={ownNumbers && number.releasable === true}
                    outboundOnly={outboundOnly(number)}
                  />
                ))}
              </div>
            </Section>
          )}
          {theirs.length > 0 && (
            <Section
              title="Numbers your agents call out from"
              info={
                <p>
                  We set these up for you on our own telephony account. Nothing to open or
                  manage.
                </p>
              }
            >
              {/* A warning, not a description: Section folds a description behind the ⓘ on
                  a phone, and this line has to stay in sight. */}
              <div className="space-y-3">
                <p className="text-body text-ink-muted">Do not forward these anywhere.</p>
                {theirs.map((number) => (
                  <NumberCard key={number.id} number={number} releasable={ownNumbers && number.releasable === true} />
                ))}
              </div>
            </Section>
          )}
        </>
      )}

      {!none && getNumber}
      <CallsAtOnce session={session} />
      <SaveNumber session={session} />
    </div>
  );
}

const SECTIONS: SegmentedOption[] = [
  { value: FROM_CALEVATE_SECTION, label: "From Calevate" },
  { value: EXISTING_SECTION, label: "Your existing number" },
];

/** A short line of what to do about a number that cannot answer yet; the why behind ⓘ. */
function WaitLine({ why, children }: { why: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-1 text-body text-ink-muted">
      <span>{children}</span>
      <InfoTip label="why this number is not answering" className="touch:-my-2.5">
        {why}
      </InfoTip>
    </p>
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
  const { session, href } = useClientRealm();
  const status = number.held
    ? { text: "Calls stopped", tone: "stop" as const }
    : number.supplied_by_us
    ? number.answerable
      ? { text: "Ready to answer", tone: "ok" as const }
      : number.direction === "outbound"
        ? { text: "Calls out only", tone: "neutral" as const }
      : !number.agent_id
        ? { text: "No agent on it yet", tone: "neutral" as const }
        : outboundOnly
          ? { text: "Makes calls only", tone: "neutral" as const }
          : { text: "Not ready yet", tone: "neutral" as const }
    : number.dlt_status === "registered"
      ? { text: "Registered for calling out", tone: "ok" as const }
      : { text: "Registration still in progress", tone: "neutral" as const };
  return (
    <div className="border-b border-line py-5">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {/* The client's OWN number, not a called party's (hard rule 6 is about those). */}
          <p className="font-mono text-heading tabular-nums text-ink">{formatPhone(number.e164)}</p>
          <StatusPill tone={status.tone}>{status.text}</StatusPill>
          <span className="text-meta text-ink-faint">{number.series} series</span>
        </div>
        <HeldNumberLine number={number} topUpHref={href(`/c/${session.orgSlug}/billing?tab=credits`)} />
        <NumberAssignment
          numberId={number.id}
          currentAgentId={number.agent_id ?? null}
          currentDirection={number.direction}
        />
        {releasable && <ReleaseOwnNumber numberId={number.id} e164={number.e164} />}
      </div>
    </div>
  );
}
