"use client";

import type { ComponentType, ReactNode } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneOff } from "lucide-react";

import { Accordion, type AccordionItem } from "@/components/arc/accordion";
import { MonoValue, formatIST } from "@/components/ui";
import { documentKindLabel, entityTypeLabel, type KycRecord } from "@/lib/api/kyc";
import { Term } from "@/lib/glossary";

import { LEAD_IN, LIST, joinDocument, stateLabel } from "./copy";

/**
 * The explaining half of Verify your business, folded into disclosures at the foot of the
 * page: the steps above are what a client came to do, and these answer the questions that
 * follow ("what does this stop?", "what do you keep?"). Closed by default, so a phone shows
 * the work first; the facts stay in the DOM, where find-in-page and a screen reader reach them.
 *
 * Read-only throughout: nothing here sets a status. Our review, or the DigiLocker result,
 * decides it (Telecom Act 2023 s.3(7)).
 */
export function AboutVerification({ record, outgoingOpen }: { record: KycRecord | undefined; outgoingOpen: boolean }) {
  const items: AccordionItem[] = [];
  if (!outgoingOpen) {
    items.push({
      id: "affects",
      title: "What this affects while it is outstanding",
      subtitle: "Incoming calls never. Outgoing calls and new numbers until it is done.",
      content: <WhatItAffects />,
    });
  }
  if (record?.recorded) {
    items.push({
      id: "on-file",
      title: "What we hold about your business",
      subtitle: "The whole record, with nothing else stored about your identity.",
      content: <OnFile record={record} />,
    });
  }
  items.push(
    {
      id: "number",
      title: "Where your calling number comes from",
      subtitle: "From us, on our own telephony account.",
      content: <PhoneNumbers verified={record?.is_verified ?? false} />,
    },
    {
      id: "keep",
      title: "What we keep, and what we never ask for",
      subtitle: "A business certificate and a masked owner ID, never an Aadhaar copy or a full Aadhaar number.",
      content: <WhatWeKeep />,
    },
  );
  return (
    <section aria-labelledby="about-verification" className="space-y-2">
      <h2 id="about-verification" className="text-heading text-ink">
        About verification
      </h2>
      <Accordion items={items} exclusive={false} headingLevel={3} />
    </section>
  );
}

/** "What we keep, and what we never ask for": the identity-document refusals, in words. */
function WhatWeKeep() {
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

/**
 * The three consequences, in the order that stops the wrong assumption first: inbound is
 * never affected; outbound is stopped on every plan until the business is verified and the
 * pledge accepted (D-692); a new number is blocked on every account. The icons carry the
 * direction of the call, which is what a worried client skims for.
 */
function WhatItAffects() {
  return (
    <ul className={LIST}>
      <Affected icon={PhoneIncoming} tone="ok" claim="Incoming calls: unaffected, on every plan.">
        Your agent answers the phone exactly as before. Nothing on this page can stop it: the
        check only ever runs before we dial out, and somebody who rang you started that call
        themselves.
      </Affected>
      <Affected icon={PhoneOutgoing} claim="Outgoing calls: stopped, on every plan.">
        Campaigns will not launch and one-off outgoing calls are refused, naming this
        verification or the no-cold-calls pledge as the reason, until both are done.
      </Affected>
      <Affected icon={PhoneOff} claim="A new phone number: blocked on every account, without exception.">
        The obligation attaches to the connection itself, so it applies whoever you are and
        whatever you pay us. Numbers you already have keep working.
      </Affected>
    </ul>
  );
}

function Affected({
  icon: Icon,
  tone,
  claim,
  children,
}: {
  icon: ComponentType<{ className?: string }>;
  tone?: "ok";
  claim: string;
  children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-3">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone === "ok" ? "text-brand" : "text-ink-faint"}`} />
      <span>
        <span className={tone === "ok" ? "font-semibold text-brand-strong" : LEAD_IN}>{claim}</span> {children}
      </span>
    </li>
  );
}

/**
 * Where the calling number comes from: us, on our own telephony account, naming no provider
 * (white label, founder 6 Oct 2026). A sentence, not a control: getting a number is the
 * phone-number screen's job. No price and no timeline, because neither is a fact this page
 * can stand behind.
 */
function PhoneNumbers({ verified }: { verified: boolean }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted">
        Calevate provides your calling number. It is connected on our own telephony account, and we
        look after the connection, so there is no operator account for you to open.
      </p>
      <ul className={LIST}>
        <li>
          <span className={LEAD_IN}>
            Your part is passing our business verification (<Term id="kyc" />).
          </span>{" "}
          Indian telecom rules require the business behind every calling number to be
          identified, and the steps above are that check.
        </li>
        <li>
          <span className={LEAD_IN}>Then keep your caller details accurate.</span> If your
          business name, address or the person who signs for it changes, tell your account
          manager, so the details held against your number stay true.
        </li>
      </ul>
      {!verified && (
        <p className="text-sm text-ink-muted">
          Your verification is still outstanding. Numbers you already have keep working,
          and calls coming in are never affected.
        </p>
      )}
    </div>
  );
}

/**
 * What is on file, shown to the business it is about. Nothing here is personal data:
 * `document_ref` is a public registry identifier, `signatory_name` the person the business
 * knows signed for it, and `evidence_ref` our own filing reference, shown because it is the
 * thing worth quoting when they call us.
 *
 * A row with no value is dropped rather than dashed: this list answers "what do you hold
 * about me", and a column we hold nothing in is not something we hold.
 */
function OnFile({ record }: { record: KycRecord }) {
  const rows: { label: string; value: string | null; mono?: boolean }[] = [
    // "Verification status", not "State": in a list of registration details a reader in
    // India takes "State" for Telangana. It prints an unrecognised status verbatim, so the
    // client still has a word to quote at us.
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
    <div data-section="on-file">
      <dl className="divide-y divide-line">
        {present.map((row) => (
          <div key={row.label} className="flex flex-wrap justify-between gap-x-4 gap-y-0.5 py-2 text-sm first:pt-0 last:pb-0">
            <dt className="text-ink-muted">{row.label}</dt>
            <dd className="min-w-0 font-semibold text-ink [overflow-wrap:anywhere]">
              {row.mono ? <MonoValue>{row.value}</MonoValue> : row.value}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-faint">
        That is the whole record. There is nothing else stored about your identity.
      </p>
    </div>
  );
}
