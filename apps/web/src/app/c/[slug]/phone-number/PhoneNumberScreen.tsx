"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { SegmentedControl, type SegmentedOption } from "@/components/interior/segmented-control";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import { useAgents, type Agent } from "@/lib/api/agents";
import { useCampaignNumbers, type CampaignNumber } from "@/lib/api/campaigns";
import { useOwnNumbersStatus } from "@/lib/api/ownNumbers";
import { useClientRealm } from "@/lib/api/session";
import { EXISTING_SECTION, FROM_CALEVATE_SECTION } from "@/lib/phoneNumbersSection";

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
        <CalevateNumbers />
      )}
    </div>
  );
}

/**
 * NUMBERS FROM CALEVATE (D-537). PRIMARY JOB: see every number this business rents and put
 * each on an agent. One list, one choice per number (`NumberAssignment`); the number does
 * what its agent does, so there is nothing else to ask. Getting another number sits below.
 */
function CalevateNumbers() {
  const { session } = useClientRealm();
  const numbers = useCampaignNumbers(session);
  const agents = useAgents(session);
  const rows = numbers.data;
  const none = rows !== undefined && rows.length === 0;
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
    // Clients buy in their own workspace (D-693); a deployment without it arranges numbers
    // with us, and says so rather than offering a purchase it would refuse.
    <p className="text-body text-ink-muted">Talk to us and we will set up a number for you.</p>
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
        <p className="text-body text-ink-muted">No number yet.</p>
      ) : (
        <Section title="Your numbers">
          <div>
            {rows.map((number) => (
              <NumberCard
                key={number.id}
                number={number}
                agent={agents.data?.find((agent) => agent.id === number.agent_id && agent.status !== "archived")}
                releasable={ownNumbers && number.releasable === true}
              />
            ))}
          </div>
        </Section>
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

/** One number: the number, one word for its state, what happens on it, and its agent. */
function NumberCard({
  number,
  agent,
  releasable,
}: {
  number: CampaignNumber;
  /** The number's agent, when it has one that is not deleted. */
  agent: Agent | undefined;
  releasable: boolean;
}) {
  const { session, href } = useClientRealm();
  const answers = agent !== undefined && agent.direction !== "outbound";
  // Only a switched-on agent answers or calls (`engine_numbers.wanted_attachment` needs
  // `live`). An answering number is Ready only once the platform routes it (`answerable`);
  // until then it is still being set up, which is ours to finish, not the owner's.
  const status = number.held
    ? { text: "Calls stopped", tone: "stop" as const }
    : !number.supplied_by_us && number.dlt_status !== "registered"
      ? { text: "Registration in progress", tone: "neutral" as const }
      : agent === undefined
        ? { text: "No agent yet", tone: "neutral" as const }
        : agent.status !== "live"
          ? { text: `${agent.name} is off`, tone: "neutral" as const }
          : answers && number.supplied_by_us && !number.answerable
            ? { text: "Setting up", tone: "neutral" as const }
            : { text: "Ready", tone: "ok" as const };
  const doing =
    agent === undefined
      ? "Pick an agent to use this number."
      : agent.direction === "inbound"
        ? `${agent.name} answers calls to this number.`
        : agent.direction === "outbound"
          ? `${agent.name} calls out from this number.`
          : `${agent.name} answers calls to this number and calls out from it.`;
  return (
    <div className="space-y-3 border-b border-line py-5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* The client's OWN number, not a called party's (hard rule 6 is about those). */}
        <p className="font-mono text-heading tabular-nums text-ink">{formatPhone(number.e164)}</p>
        <StatusPill tone={status.tone}>{status.text}</StatusPill>
      </div>
      <p className="text-body text-ink-muted">
        {doing}
        {agent !== undefined && agent.status !== "live" && (
          <>
            {" "}
            <Link href={href(`/c/${session.orgSlug}/agents/${agent.id}`)} className="underline">
              Switch {agent.name} on
            </Link>
          </>
        )}
      </p>
      <HeldNumberLine number={number} topUpHref={href(`/c/${session.orgSlug}/billing?tab=credits`)} />
      <NumberAssignment numberId={number.id} currentAgentId={number.agent_id ?? null} />
      {releasable && <ReleaseOwnNumber numberId={number.id} e164={number.e164} />}
    </div>
  );
}
