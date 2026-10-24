"use client";

import { PageHeader } from "@/components/console/pageHeader";
import { NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice, Skeleton } from "@/components/ui";
import { usePeRegistration } from "@/lib/api/dltRegistration";
import { useActAccess, useWriteAccess } from "@/lib/api/hooks";
import { useKycRecord, type KycRecord } from "@/lib/api/kyc";
import { useClientSession } from "@/lib/api/session";
import { outboundSteps, useOutboundPledge, type OutboundPledge } from "@/lib/api/verifyBusiness";

import { AboutVerification } from "./About";
import { UNNAMED_STATUS, describeVerification, verdictCopy } from "./copy";
import { useVerifyBusinessCopilot } from "./copilot";
import { DltDetails } from "./DltRegistration";
import { PhoneNumbersNext } from "./PhoneNumbersNext";
import { DigiLockerReturn, VerificationSteps, stepStatuses, type Access, type StepStatus } from "./Steps";
import { TrialLockNotice } from "../TrialLockNotice";

/**
 * Verify your business (D-692, one screen since D-875) — the page somebody opens because
 * their outgoing calls stopped, and the page that starts them again.
 *
 * `check_dispatch` refuses a self-serve account's outbound with `kyc_missing` /
 * `kyc_not_verified` or a missing pledge, `launch_blockers` previews the same names, and
 * `POST /v1/numbers/purchase` refuses every tier on the same fact; this is where they all
 * send the client. It used to be two screens, one doing and one explaining, and a client
 * whose calls had stopped had to guess which to open (founder, 24 Oct 2026). Now: the
 * verdict and the one next thing at the top, the four steps with their forms, the DLT
 * registration where one is on file, and the explanations folded at the foot.
 *
 * WHY THERE IS NO "BUY A NUMBER" CONTROL ON THIS PAGE: the number is ours to provide.
 * Calevate provides the calling number on its own telephony account, naming no provider
 * (white label, founder 6 Oct 2026), and a number is arranged from the phone-number screen.
 * No self-serve provisioning adapter exists
 * either: `campaigns.provisioning.PROVISIONING_IMPLEMENTED = False`.
 *
 * That sentence is also load-bearing for a guard. `scripts/check_docs_drift.py` §5
 * compares prose that STATES a capability constant's value against the constant itself,
 * across three prose kinds — markdown, Python docstrings, and the console's JSDoc — and
 * this file is the console's only such claim, so `tests/capability_claim_guard_test.py`
 * uses it to prove the TSX scanner still works, BY THIS EXACT PATH. Moving it to a sibling
 * module fails that test; deleting it leaves that arm of the scanner unproven.
 *
 * What the page has to get right, each a decision the API already made:
 *
 * 1. **Inbound is unaffected, and it is said before anything else.** The gate lives in
 *    `compliance.service.check_dispatch`, which an inbound call never enters. A client
 *    reading "verification required" will otherwise assume their receptionist is down.
 * 2. **The client cannot self-verify.** They supply details, documents and the pledge; our
 *    review or a DigiLocker result decides the status (Telecom Act 2023 s.3(7)).
 * 3. **The green state comes from `is_verified`, never from `status`.** The server computes
 *    the predicate every gate asks, and a screen that re-derived it would disagree with the
 *    gate on the day it matters (`copy.verdictCopy`).
 * 4. **A failed read is a refusal, never a state.** The KYC record, the pledge and the DLT
 *    registration are three reads; each failure is its own notice with a retry and none
 *    blanks the others, and "outgoing calls are open" is said only when every record it
 *    rests on arrived.
 * 5. **Client-facing text names no telecom or voice vendor.** DigiLocker is named because
 *    it is the government service the owner signs in to, not a supplier of ours.
 */
export default function VerifyBusinessPage() {
  const session = useClientSession();
  const kyc = useKycRecord(session);
  const pledge = useOutboundPledge(session);
  const dlt = usePeRegistration(session);
  const access: Access = {
    write: useWriteAccess(session, "org:manage", "verify the business"),
    upload: useActAccess(session, "org:manage", "compliance.kyc_documents", "upload verification documents"),
    pledge: useActAccess(session, "org:manage", "compliance.outbound_pledge", "accept the pledge"),
  };
  const record = kyc.data;
  const outgoingOpen = record ? outgoingState(record, pledge.data) : null;

  useVerifyBusinessCopilot(kyc, pledge, dlt, outgoingOpen);

  if (kyc.isLoading || pledge.isLoading) return <Skeleton rows={8} />;

  return (
    <div className="max-w-3xl space-y-8 pb-12">
      <PageHeader
        description="Outgoing calls open once we verify your business and you accept the no-cold-calls pledge. Calls coming in are never affected."
      />
      <div className="space-y-3">
        <DigiLockerReturn session={session} />
        {kyc.error || !record ? (
          <ProblemNotice
            error={kyc.error ?? new Error("The verification record did not load.")}
            onRetry={() => void kyc.refetch()}
          />
        ) : (
          <OutgoingSummary record={record} pledge={pledge.data} open={outgoingOpen} />
        )}
        <TrialLockNotice lock="kyc" />
      </div>
      {record && (
        <VerificationSteps
          session={session}
          record={record}
          pledge={pledge.data}
          pledgeError={pledge.error}
          onPledgeRetry={() => void pledge.refetch()}
          access={access}
        />
      )}
      <PhoneNumbersNext />
      {dlt.error ? (
        <ProblemNotice error={dlt.error} onRetry={() => void dlt.refetch()} />
      ) : (
        // Only a registration somebody filed: since D-692 none is needed to call.
        dlt.data?.recorded && <DltDetails registration={dlt.data} />
      )}
      <AboutVerification record={record} outgoingOpen={outgoingOpen === true} />
    </div>
  );
}

/**
 * `true` when outgoing calls are open, `false` when something is left, `null` when the
 * answer rests on a record that did not load (the pledge): never "open" on a failed read.
 */
function outgoingState(record: KycRecord, pledge: OutboundPledge | undefined): boolean | null {
  if (outboundSteps(record, pledge).length > 0) return false;
  return pledge === undefined ? null : true;
}

/** The sentence for the one next thing, in the owner's words. */
function nextSentence(step: StepStatus, record: KycRecord, pledge: OutboundPledge | undefined): string {
  switch (step.id) {
    case "details":
      return "Next: add your business details.";
    case "certificate":
      return "Next: upload the business certificate.";
    case "owner":
      if (record.digilocker_outstanding) return "Next: complete the DigiLocker check we asked for.";
      return record.status === "rejected" ? "Next: correct it and send the owner's ID again." : "Next: verify the owner's identity.";
    case "pledge":
      return pledge?.accepted_version != null
        ? "Next: accept the updated no-cold-calls pledge."
        : "Next: accept the no-cold-calls pledge.";
  }
}

/**
 * Where outgoing calls stand, first on the page: open, or paused with the one next thing and
 * a jump to it. Inbound is said before the verdict, because "paused" read alone sounds like
 * the phone line is down.
 */
function OutgoingSummary({
  record,
  pledge,
  open,
}: {
  record: KycRecord;
  pledge: OutboundPledge | undefined;
  open: boolean | null;
}) {
  if (open === null) return null;
  if (open) {
    const checked = describeVerification(record);
    return (
      <NoticeBox tone="ok" title="Outgoing calls are open">
        Your business is verified and the no-cold-calls pledge is accepted.{checked ? ` ${checked}` : ""}
      </NoticeBox>
    );
  }
  const next = stepStatuses(record, pledge).find((step) => step.state === "todo");
  const verdict = record.is_verified ? null : verdictCopy(record);
  return (
    <NoticeBox
      tone={record.status === "rejected" && !record.is_verified ? "stop" : "warn"}
      title="Outgoing calls are paused"
      action={
        next && (
          <a href={`#step-${next.id}`} className={PRIMARY_BUTTON_SM}>
            Go to step {next.number}
          </a>
        )
      }
    >
      <div className="space-y-1.5">
        <p>Calls coming in are unaffected. Your agent keeps answering the phone.</p>
        {verdict && (
          <p>
            <span>{verdict.headline}</span>
            {verdict === UNNAMED_STATUS && <span> {verdict.next}</span>}
          </p>
        )}
        {verdict && record.rejection_reason && (
          <p>
            <span className="font-semibold">What we said:</span> {record.rejection_reason}
          </p>
        )}
        <p className="text-ink-muted">
          {next
            ? nextSentence(next, record, pledge)
            : "Nothing for you to do now. We will let you know when our review is done."}
        </p>
      </div>
    </NoticeBox>
  );
}
