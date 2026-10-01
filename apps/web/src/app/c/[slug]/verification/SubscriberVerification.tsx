"use client";

import type { ComponentType, ReactNode } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneOff } from "lucide-react";

import type { ChecklistItem } from "@/components/console/checklist";
import { MonoValue, formatIST } from "@/components/ui";
import {
  DOCUMENT_KINDS,
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
        <span className={LEAD_IN}>There is nothing to upload here, on purpose.</span> We
        record your business&apos;s public registration number — the one anyone can
        look up on the government register — and a reference to where our paperwork
        is filed. No scan, no photograph and no copy of any document is stored.
      </li>
      <li>
        <span className={LEAD_IN}>Never send an Aadhaar or an individual&apos;s PAN.</span>{" "}
        We do not ask for one, we have nowhere to put one, and a value shaped like an
        Aadhaar is refused by the system rather than merely discouraged. What we need
        identifies the business, not a person.
      </li>
      <li>
        <span className={LEAD_IN}>Verification is ours to do, not yours to declare.</span>{" "}
        There is no control on this page that sets your own status — the rules make
        confirming who holds the connection our job, not something you can claim about
        yourself, so a business marking itself verified would be worth nothing to
        anyone.
      </li>
      <li>
        <span className={LEAD_IN}>
          This is separate from your{" "}
          <Term id="dlt" />{" "}
          registration.
        </span>{" "}
        The two overlap in the documents they rest on, but they are held by different
        people for different purposes, and neither one clears the other. Your campaign
        registration is on this page too.
      </li>
    </ul>
  );
}

/**
 * Business verification as one checklist row: the verdict as its label, the next step as
 * its detail, and the last refusal reason (non-null whenever the status is `rejected`)
 * while the account is not yet cleared, never under a verified record.
 */
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
    <Section title="What to send us">
      <p className="text-sm text-ink-muted">
        Send these to your account manager and we will verify the account. We only need
        the numbers below — not copies of anything.
      </p>
      <ul className={`mt-3 ${LIST}`}>
        <li>
          <span className={LEAD_IN}>
            Your registered business name and what kind of business it is
          </span>{" "}
          — company, LLP, partnership, sole proprietorship, trust or HUF.
        </li>
        <li>
          <span className={LEAD_IN}>One registration number for the business.</span> Any one
          of: {Object.values(DOCUMENT_KINDS).map((spec) => spec.label).join(", ")}.
        </li>
        <li>
          <span className={LEAD_IN}>The registered address of the business.</span> It has to
          match the city a number is issued in, so a mismatch is the most common reason one
          gets held up.
        </li>
        <li>
          <span className={LEAD_IN}>
            The name of the person authorised to sign for the business.
          </span>{" "}
          A name only — we do not record their identity document.
        </li>
      </ul>
      <p className="mt-3 text-sm text-ink">
        <span className={LEAD_IN}>Never send an Aadhaar or an individual&apos;s PAN.</span>{" "}
        What we need identifies the business, not a person.
      </p>
    </Section>
  );
}

/**
 * The three consequences, split by who they hit and stated in the order that stops the
 * wrong assumption first.
 *
 * The dial gate is scoped to self-serve and trial accounts and the purchase gate is
 * not, and the difference is deliberate in the API (`apps/api/compliance/kyc.py`). The
 * client response carries no `plan_tier`, and `/v1/usage` — which does — needs
 * `billing:read`, so a member of staff would be refused it. Rather than either fetch a
 * panel this reader may not be allowed to see, or assert a stop that may not apply to
 * their account, the copy states each gate with the accounts it applies to. Saying "on
 * self-serve and trial plans" to a managed client costs them a moment; telling a
 * managed client their outbound calling has stopped when it has not costs them a day.
 *
 * WHICH WAY ROUND THE SENTENCE GOES CHANGED WITH THE MOTION, though the fact behind it
 * did not. The claim read "stopped on self-serve and trial accounts" — our own tier names,
 * and phrased as though the gate were the exception. Every account is now prepaid unless
 * an operator deliberately puts it on a retainer, so the gate is what almost every reader
 * is under: it is stated as the rule, with the managed account as the carve-out, and in
 * words rather than in plan tiers. The API's scoping is unchanged.
 *
 * The icons carry the direction of the call, which is the whole distinction the list is
 * making and the one a worried client skims for.
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
          claim="Outgoing calls: stopped, unless yours is an account we run for you."
        >
          Campaigns will not launch and one-off outbound calls are refused, naming this
          verification as the reason. Accounts we set up and manage for you are not gated
          here — their identity was verified with us before the number was bought.
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
 * Where the calling number comes from — which is not us.
 *
 * `number_purchase_available` is the server's own selector — the SAME one
 * `POST /v1/numbers/purchase` asks — so this card can never promise something that
 * route would refuse. It is false for every account in every deployment and by
 * DECISION rather than by omission (Model B), so the card is a sentence and not a
 * control, and the sentence is the next step rather than a refusal: the carriers to
 * open an account with, and the two things to send back afterwards.
 *
 * No prices, no timelines and no signup URL — none of those is a fact this repository
 * has read, and each operator publishes its own. The KYC sentence is here because it
 * is true on both sides at once: their operator asks for the documents we ask for.
 */
export function PhoneNumbers({ record }: { record: KycRecord }) {
  return (
    <div>
      <p className="text-sm text-ink-muted">
        Calevate does not sell, rent or supply telephone numbers. Your calling number is
        a connection you take in your own name, on your own account with an Indian
        operator — <span className="font-medium text-ink">Exotel</span>,{" "}
        <span className="font-medium text-ink">Plivo</span> or{" "}
        <span className="font-medium text-ink">Vobiz</span>. You stay the subscriber of
        record for it, which is what keeps it yours.
      </p>
      <ul className={`mt-3 ${LIST}`}>
        <li>
          <span className={LEAD_IN}>
            Open the account and pass their <Term id="kyc" />.
          </span> They ask
          for the same business details we ask for, and the address proof normally
          has to match the city the number is issued in. Operators keep outgoing calls
          disabled until their own check clears.
        </li>
        <li>
          <span className={LEAD_IN}>Then send us two things.</span> The number, and API
          credentials for that account. We connect it to your agents with those
          credentials — and you can withdraw them at any time, from your own account.
        </li>
      </ul>
      {!record.is_verified && (
        <p className="mt-3 text-sm text-ink-muted">
          Our verification of your business, above, is a separate thing and is still
          outstanding. Numbers you already have keep working, and calls coming in are
          never affected.
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
