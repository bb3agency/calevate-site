"use client";

import Link from "next/link";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { PageHeader } from "@/components/console/pageHeader";
import { Disclosure, ProblemNotice, Skeleton } from "@/components/ui";
import { useKycRecord } from "@/lib/api/kyc";
import { usePeRegistration } from "@/lib/api/dltRegistration";
import { useClientRealm } from "@/lib/api/session";

import { useVerificationCopilot } from "./copilot";
import { DltDetails, dltItem } from "./DltRegistration";
import { KycSections, PhoneNumbers, WhatWeKeep, kycItem } from "./SubscriberVerification";

/**
 * Business verification — the page somebody opens because their calls stopped.
 *
 * `check_dispatch` refuses a self-serve account's outbound with `kyc_missing` /
 * `kyc_not_verified`, `launch_blockers` previews the same two names, and
 * `POST /v1/numbers/purchase` refuses every tier on the same fact; this is where they send
 * the client.
 *
 * WHY THERE IS NO "BUY A NUMBER" CONTROL ON THIS PAGE: this page is about verification,
 * and the number is ours to provide. Calevate provides the calling number on its own
 * telephony account, naming no provider (white label, founder 6 Oct 2026), and a number is
 * arranged from the phone-number screen. No self-serve provisioning adapter exists
 * either: `campaigns.provisioning.PROVISIONING_IMPLEMENTED = False`.
 *
 * That sentence is also load-bearing for a guard. `scripts/check_docs_drift.py` §5
 * compares prose that STATES a capability constant's value against the constant itself,
 * across three prose kinds — markdown, Python docstrings, and the console's JSDoc — and
 * this file is the console's only such claim, so `tests/capability_claim_guard_test.py`
 * uses it to prove the TSX scanner still works, BY THIS EXACT PATH. Deleting it does not
 * merely lose a true statement; it leaves that arm of the scanner unproven, and moving it
 * to a sibling module fails that test.
 *
 * Five things it has to get right, each of them a decision the API already made:
 *
 * 1. **Inbound is unaffected, and it is said before anything else.** The gate lives in
 *    `compliance.service.check_dispatch`, which an inbound call never enters (D-38 makes
 *    the receptionist the headline product). A client reading "verification required"
 *    will otherwise assume their receptionist is down. It is not, and that distinction
 *    is the entire reason the gate is outbound-only.
 * 2. **The client cannot self-verify.** Our review or a DigiLocker result decides the
 *    status (Telecom Act 2023 s.3(7)); the client's part — details, documents, the
 *    pledge — is on the separate Verify your business page (D-692).
 * 3. **This page takes no input.** It shows what we hold; every upload and acceptance is
 *    on Verify your business, which keeps this screen usable in a read-only support
 *    session (`tests/readiness_copy_actionability_test.py`).
 * 4. **The green state comes from `is_verified`, never from `status`.** Same doctrine as
 *    `messageable` on the consent screen: the server computes the predicate every gate
 *    asks, and a screen that re-derived it would disagree with the gate on the day it
 *    matters.
 * 5. **Where the number comes from is said plainly: from us.** No provider is named. The client
 *    opens no operator account and issues us no credentials; their part is passing our
 *    business verification and keeping the details we hold accurate. No price and no
 *    timeline is promised here, because neither is a fact this page can stand behind.
 *
 * Read-only throughout, deliberately: `org:read` is not a mutating permission and BOTH
 * client roles hold it (core/rbac.py), so every reader of this page may read all of it
 * and there is no control to gate. It therefore keeps working inside a D-22 "view as
 * client" session — the session a support person is in exactly when this account is the
 * thing being discussed. `tests/readiness_copy_actionability_test.py` asserts that
 * read-only-ness over this whole directory.
 *
 * The page reads both records once and composes the halves: one checklist of the two
 * verdicts, then the KYC sections (`SubscriberVerification.tsx`) and the DLT details
 * (`DltRegistration.tsx`). A failed read of either is its own refusal and never blanks
 * the other: the client whose KYC read fails is often asking why campaigns are refused.
 */
export default function VerificationPage() {
  const { session, href } = useClientRealm();
  const kyc = useKycRecord(session);
  const dlt = usePeRegistration(session);

  useVerificationCopilot(kyc, dlt);

  if (kyc.isLoading || dlt.isLoading) return <Skeleton rows={8} />;

  const kycRecord = kyc.data;
  const pe = dlt.data;
  // Only rows whose state the server returned: a failed read is a refusal, never an unticked box (§52).
  // D-692: the DLT registration no longer gates outbound, so only the KYC verdict is a
  // "before outgoing calls" item; the registration stays visible below for the record.
  const items: ChecklistItem[] = kycRecord ? [kycItem(kycRecord)] : [];
  const blocked = kycRecord && !kycRecord.is_verified;

  return (
    <div className="space-y-8 pb-12">
      <PageHeader
        description={
          <>
            What we hold about your business. To verify it, or to accept the no-cold-calls
            pledge, go to{" "}
            <Link href={href(`/c/${session.orgSlug}/verify-business`)} className="font-semibold underline">
              Verify your business
            </Link>
            . Neither affects the calls coming in.
          </>
        }
      />

      <div className="space-y-3">
        {(kyc.error || !kycRecord) && (
          <ProblemNotice
            error={kyc.error ?? new Error("The verification record did not load.")}
            onRetry={() => void kyc.refetch()}
          />
        )}
        {(dlt.error || !pe) && (
          <ProblemNotice
            error={dlt.error ?? new Error("Your DLT registration did not load, so we cannot say where it stands.")}
            onRetry={() => void dlt.refetch()}
          />
        )}
        {items.length > 0 && <Checklist label="Before outgoing calls can start" headingLevel={2} items={items} />}
        {pe && <Checklist label="DLT registration, on record" headingLevel={2} items={[dltItem(pe)]} />}
        {blocked && (
          <p className="text-sm font-semibold text-ink">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>

      {kycRecord && <KycSections record={kycRecord} />}
      {pe && <DltDetails registration={pe} />}

      <div className="space-y-3">
        {kycRecord && (
          <Disclosure title="Where your calling number comes from" subtitle="From us, on our own telephony account.">
            <PhoneNumbers record={kycRecord} />
          </Disclosure>
        )}
        <Disclosure title="What we keep, and what we never ask for" subtitle="A business certificate and a masked owner ID — never a full Aadhaar.">
          <WhatWeKeep />
        </Disclosure>
      </div>
    </div>
  );
}
