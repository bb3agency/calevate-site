"use client";

import type { ComponentType, ReactNode } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneOff } from "lucide-react";

import type { ChecklistItem } from "@/components/console/checklist";
import { MonoValue, formatIST } from "@/components/ui";
import {
  documentKindLabel,
  entityTypeLabel,
  type KycRecord,
} from "@/lib/api/kyc";
import { Term } from "@/lib/glossary";

import {
  LEAD_IN,
  LIST,
  describeVerification,
  joinDocument,
  stateLabel,
  verdictCopy,
} from "./copy";

/**
 * The KYC half of `/c/[slug]/verification`: who this business is, as we verified it.
 *
 * The screen's own decisions — no upload control, no self-verification, `is_verified`
 * and never `status` — are recorded in the route module's docstring, which is also the
 * console's one prose claim about `PROVISIONING_IMPLEMENTED` and is pinned there by
 * `tests/capability_claim_guard_test.py`.
 *
 * ORDER, and it is the reason this file exists rather than a second card: what the client
 * can DO ("What to send us") sits above what they cannot ("What this affects"). The
 * verdict names the state, the next step follows it, and the consequences qualify it —
 * a client who has read the first two has already left, which is the point.
 */
export function KycSections({ record }: { record: KycRecord }) {
  return (
    <>
      {!record.is_verified && (
        <>
          <WhatWeNeed />
          <WhatItAffects />
        </>
      )}
      {record.recorded && <OnFile record={record} />}
    </>
  );
}

/** "What we keep, and what we never ask for" — the identity-document refusals, in words. */
export function WhatWeKeep() {
  return (
    <ul className={LIST}>
      <li>
        <span className={LEAD_IN}>Your business certificate.</span> The GST certificate, or
        the Certificate of Incorporation or Udyam certificate, encrypted, for as long as the
        account is open. It is deleted when the account is closed.
      </li>
      <li>
        <span className={LEAD_IN}>Only a masked owner ID.</span> If you upload the
        owner&apos;s PAN card, the file is deleted as soon as our review is done, or after 30
        days if it is not reviewed. We keep the PAN masked, as XXXXX1234X. We do not accept
        a copy of an Aadhaar card, and we never take a full Aadhaar number.
      </li>
      <li>
        <span className={LEAD_IN}>Nothing from DigiLocker but the result.</span> If you
        verify through DigiLocker, we receive whether it succeeded, the name on the record and
        a masked number. The document itself is never sent to us or stored.
      </li>
      <li>
        <span className={LEAD_IN}>Verification is ours to do, not yours to declare.</span>{" "}
        There is no control anywhere that sets your own status: our review, or the
        DigiLocker result, decides it.
      </li>
    </ul>
  );
}

export function kycItem(record: KycRecord): ChecklistItem {
  const copy = verdictCopy(record);
  return {
    id: "kyc",
    label: copy.headline,
    state: record.is_verified ? "done" : "todo",
    detail: (
      <>
        {record.is_verified ? `${describeVerification(record)} ${copy.next}`.trim() : copy.next}
        {!record.is_verified && record.rejection_reason && (
          <span className="mt-1 block text-ink">
            <span className="font-semibold">What we said:</span> {record.rejection_reason}
          </span>
        )}
      </>
    ),
  };
}

function WhatWeNeed() {
  return (
    <Section title="What we need">
      <p className="text-sm text-ink-muted">
        Everything is done on the Verify your business page.
      </p>
      <ul className={`mt-3 ${LIST}`}>
        <li>
          <span className={LEAD_IN}>Your business details</span> — the legal name, how the
          business is registered, whether it is GST-registered and the GSTIN if so.
        </li>
        <li>
          <span className={LEAD_IN}>One business certificate</span> — the GST certificate,
          or the Certificate of Incorporation or Udyam certificate.
        </li>
        <li>
          <span className={LEAD_IN}>The owner&apos;s identity</span> — either the
          owner&apos;s PAN card for our review, or a DigiLocker verification with Aadhaar or
          PAN.
        </li>
        <li>
          <span className={LEAD_IN}>The no-cold-calls pledge</span> — accepted by somebody at
          the business.
        </li>
      </ul>
    </Section>
  );
}

/**
 * The three consequences, stated in the order that stops the wrong assumption first:
 * inbound is never affected; outbound is stopped on every plan until the business is
 * verified and the pledge accepted (D-692); a new number is blocked on every account.
 * The icons carry the direction of the call, which is what a worried client skims for.
 */
function WhatItAffects() {
  return (
    <Section title="What this affects while it is outstanding">
      <ul className="space-y-3 text-sm text-ink-muted">
        <Affected icon={PhoneIncoming} tone="ok" claim="Incoming calls: unaffected, on every plan.">
          Your agent answers the phone exactly as before. Nothing on this page can stop
          it — the check only ever runs before we dial OUT, and somebody who rang you
          started that call themselves.
        </Affected>
        <Affected
          icon={PhoneOutgoing}
          claim="Outgoing calls: stopped, on every plan."
        >
          Campaigns will not launch and one-off outbound calls are refused, naming this
          verification or the no-cold-calls pledge as the reason, until both are done.
        </Affected>
        <Affected
          icon={PhoneOff}
          claim="A new phone number: blocked on every account, without exception."
        >
          The obligation attaches to the connection itself, so it applies whoever you are
          and whatever you pay us. Numbers you already have keep working.
        </Affected>
      </ul>
    </Section>
  );
}

/** One consequence: what it is, and who it lands on. `ok` is the one piece of good news. */
function Affected({
  icon: Icon,
  tone,
  claim,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  tone?: "ok";
  claim: string;
  children: React.ReactNode;
}) {
  const emphasis =
    tone === "ok" ? "font-semibold text-brand-strong dark:text-brand-bright" : LEAD_IN;
  return (
    <li className="flex items-start gap-3">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone === "ok" ? "text-brand" : "text-ink-faint"}`} />
      <span>
        <span className={emphasis}>{claim}</span> {children}
      </span>
    </li>
  );
}

/**
 * Where the calling number comes from: us, on our own telephony account.
 *
 * The number is ours (founder, 2 Oct 2026) and no provider is named (white label, 6 Oct 2026): Calevate
 * provides the number and the carrier connection; the client's part is our business
 * verification and keeping the details we hold accurate. The card is a sentence and not a
 * control: getting a number is the phone-number screen's job, not this page's.
 *
 * No prices and no timelines: neither is a fact this screen can stand behind, and the
 * number screen is where a price is shown once it is frozen on a purchase.
 */
export function PhoneNumbers({ record }: { record: KycRecord }) {
  return (
    <div>
      <p className="text-sm text-ink-muted">
        Calevate provides your calling number. It is connected on our own telephony account, and we
        look after the connection, so there is no operator account for you to open.
      </p>
      <ul className={`mt-3 ${LIST}`}>
        <li>
          <span className={LEAD_IN}>
            Your part is passing our business verification (<Term id="kyc" />).
          </span>{" "}
          Indian telecom rules require the business behind every calling number to be
          identified, and the check above is that check.
        </li>
        <li>
          <span className={LEAD_IN}>Then keep your caller details accurate.</span> If your
          business name, address or the person who signs for it changes, tell your account
          manager, so the details held against your number stay true.
        </li>
      </ul>
      {!record.is_verified && (
        <p className="mt-3 text-sm text-ink-muted">
          Your verification is still outstanding. Numbers you already have keep working,
          and calls coming in are never affected.
        </p>
      )}
    </div>
  );
}

/**
 * What is on file, shown to the business it is about.
 *
 * Nothing here is personal data: `document_ref` is a public registry identifier and
 * `signatory_name` is the person that business already knows signed for it (hard rule
 * 6 — there is no identity-document number in the schema to leak). `evidence_ref` is
 * our own filing reference and appears because it is the thing worth quoting when they
 * call us about it, the same reason the top-up card prints its receipt reference.
 *
 * A row with no value is DROPPED rather than dashed: this list is the answer to "what
 * do you hold about me", and a column we hold nothing in is not something we hold.
 */
function OnFile({ record }: { record: KycRecord }) {
  const rows: { label: string; value: string | null; mono?: boolean }[] = [
    /* "Verification status", not "State": in a list of business-registration details a
       reader in India takes "State" for Telangana, not for a workflow step. It is the
       RECORDED label — the verdict box above is where the account stands — and it prints
       an unrecognised status verbatim, so a client whose record is in a state this build
       cannot name still has a word to quote at us. */
    { label: "Verification status", value: stateLabel(record) },
    { label: "Kind of business", value: entityTypeLabel(record.entity_type) },
    {
      label: "Checked against",
      value: joinDocument(documentKindLabel(record.document_kind), record.document_ref),
    },
    { label: "Signed for the business by", value: record.signatory_name },
    { label: "Received", value: record.submitted_at ? formatIST(record.submitted_at) : null },
    { label: "Verified", value: record.verified_at ? formatIST(record.verified_at) : null },
    { label: "Our file reference", value: record.evidence_ref, mono: true },
  ];
  const present = rows.filter((row) => row.value !== null && row.value !== "");

  return (
    <Section title="What we hold about your business">
      <dl className="divide-y divide-line">
        {present.map((row) => (
          <div key={row.label} className="flex flex-wrap justify-between gap-2 py-2 text-sm first:pt-0 last:pb-0">
            <dt className="text-ink-muted">{row.label}</dt>
            <dd className="font-semibold text-ink">
              {row.mono ? <MonoValue>{row.value}</MonoValue> : row.value}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-faint">
        That is the whole record — there is nothing else stored about your identity.
      </p>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {children}
    </section>
  );
}
