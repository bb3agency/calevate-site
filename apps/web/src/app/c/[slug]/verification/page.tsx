"use client";

import { Card, NOTICE_TONES, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  DOCUMENT_KINDS,
  KYC_STATUS_COPY,
  documentKindLabel,
  entityTypeLabel,
  isKnownKycStatus,
  useKycRecord,
  type KycRecord,
  type KycStatusCopy,
} from "@/lib/api/kyc";
import { useClientSession } from "@/lib/api/session";

/**
 * Business verification — the page somebody opens because their calls stopped.
 *
 * `check_dispatch` refuses a self-serve account's outbound with `kyc_missing` /
 * `kyc_not_verified`, `launch_blockers` previews the same two names, and
 * `POST /v1/numbers/purchase` refuses every tier on the same fact. Until now none of
 * those refusals had anywhere to send anyone. So this screen is not a status readout;
 * it is the answer to "what do I do now", and it is written for the worst moment to
 * arrive with no page.
 *
 * Five things it has to get right, each of them a decision the API already made:
 *
 * 1. **Inbound is unaffected, and it is said before anything else.** The gate lives in
 *    `compliance.service.check_dispatch`, which an inbound call never enters (D-38 makes
 *    the receptionist the headline product). A client reading "verification required"
 *    will otherwise assume their receptionist is down. It is not, and that distinction
 *    is the entire reason the gate is outbound-only.
 * 2. **The client cannot self-verify, and nothing here pretends otherwise.** There is no
 *    client-realm write: Indian telecom rules make the subscriber's identity something
 *    the provider verifies, never something the subscriber asserts (Telecom Act 2023
 *    s.3(7)). What they CAN do is send us what we need, so that is the call to action.
 * 3. **No upload control, ever.** The API stores a public business-registry identifier
 *    and a filing reference — never a document — and a CHECK refuses a bare twelve-digit
 *    value so an Aadhaar cannot be pasted into a business field. A file input here would
 *    invite exactly the thing the schema exists to refuse, so the screen says out loud
 *    that there is nothing to upload.
 * 4. **The green state comes from `is_verified`, never from `status`.** Same doctrine as
 *    `messageable` on the consent screen: the server computes the predicate every gate
 *    asks, and a screen that re-derived it would disagree with the gate on the day it
 *    matters.
 * 5. **Buying a number is stated, not offered.** `number_purchase_available` is false in
 *    this deployment for every account (no telephony provider, no adapter —
 *    `PROVISIONING_IMPLEMENTED = False`), so there is no purchase form. A "Buy a number"
 *    button that always answers with a refusal is worse than no button: it costs the
 *    client a support ticket to learn what one sentence could have told them. The form
 *    goes here the day the capability turns true.
 *
 * Read-only throughout, deliberately: `org:read` is not a mutating permission, so this
 * page keeps working inside a D-22 "view as client" session — the session a support
 * person is in exactly when this account is the thing being discussed. There is no
 * `useWriteAccess` here because there is no control to gate.
 */

/**
 * What the client is told, which is everything in the shared table except the label an
 * operator picks from a dropdown — no realm renders the other's words.
 */
type VerdictCopy = Pick<KycStatusCopy, "label" | "headline" | "next" | "tone">;

/** The state of a business that has never been filed — no row, which is a 200. */
const NOT_RECORDED: VerdictCopy = {
  label: "Not on file",
  headline: "We have not verified your business yet.",
  next: "Send us your business registration details and we will verify the account.",
  tone: "neutral",
};

export default function VerificationPage() {
  const session = useClientSession();
  const record = useKycRecord(session);

  if (record.isLoading) return <Skeleton rows={6} />;
  if (record.error)
    return <ProblemNotice error={record.error} onRetry={() => record.refetch()} />;
  if (!record.data) return null;

  const kyc = record.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">
          Business verification
        </h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Indian telecom rules require the business behind a phone connection to be
          identified before it can place calls. This is where yours stands, and what we
          need if it is outstanding.
        </p>
      </div>

      <Verdict record={kyc} />

      {!kyc.is_verified && (
        <>
          <WhatItAffects />
          <WhatWeNeed />
        </>
      )}

      <PhoneNumbers record={kyc} />

      {kyc.recorded && <OnFile record={kyc} />}

      <Card title="What we keep, and what we never ask for">
        <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              There is nothing to upload here, on purpose.
            </span>{" "}
            We record your business&apos;s public registration number — the one anyone can
            look up on the government register — and a reference to where our paperwork
            is filed. No scan, no photograph and no copy of any document is stored.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              Never send an Aadhaar or an individual&apos;s PAN.
            </span>{" "}
            We do not ask for one, we have nowhere to put one, and a value shaped like an
            Aadhaar is refused by the system rather than merely discouraged. What we need
            identifies the business, not a person.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              Verification is ours to do, not yours to declare.
            </span>{" "}
            There is no control on this page that sets your own status — the rules make
            identifying a subscriber the provider&apos;s job, so a business marking itself
            verified would be worth nothing to anyone.
          </li>
          <li>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              This is separate from your DLT registration.
            </span>{" "}
            The two overlap in the documents they rest on, but they are held by different
            people for different purposes, and neither one clears the other. Your campaign
            screen names the DLT ones separately when they are what is blocking a launch.
          </li>
        </ul>
      </Card>
    </div>
  );
}

/**
 * Where the account stands, in one box.
 *
 * `is_verified` decides the green path — never `status === "verified"` — so a status
 * this build has never heard of cannot be rendered as cleared. An unknown status falls
 * back to "not verified yet, ask us where it stands", which is vaguer than we would
 * like and still the only answer that cannot be wrong.
 */
function Verdict({ record }: { record: KycRecord }) {
  const copy = verdictCopy(record);
  return (
    <div className={`rounded-lg border p-4 text-sm ${NOTICE_TONES[copy.tone]}`}>
      <p className="text-base font-medium">{copy.headline}</p>
      {record.is_verified ? (
        <p className="mt-1">
          {describeVerification(record)} {copy.next}
        </p>
      ) : (
        <p className="mt-1">{copy.next}</p>
      )}
      {/* Guaranteed non-null when the status is `rejected`
          (`ck_kyc_records_rejected_names_its_reason`), so a client is never told
          "rejected" with no reason. Shown on any state that is not yet cleared, because
          a reason left over from an earlier refusal is still the last thing we told
          them and still the thing they are answering — but never under a verified
          record, where it would explain a decision that has since been reversed. */}
      {!record.is_verified && record.rejection_reason && (
        <p className="mt-2 rounded-md bg-white/60 p-2 dark:bg-black/20">
          <span className="font-medium">What we said:</span> {record.rejection_reason}
        </p>
      )}
      {!record.is_verified && (
        <p className="mt-2 font-medium">
          Calls coming IN are unaffected — your agent keeps answering the phone.
        </p>
      )}
    </div>
  );
}

function verdictCopy(record: KycRecord): VerdictCopy {
  if (!record.recorded) return NOT_RECORDED;
  const status = record.status;
  if (status !== null && isKnownKycStatus(status)) return KYC_STATUS_COPY[status];
  return {
    ...NOT_RECORDED,
    headline: "Your business is not verified yet.",
    next: "Ask your account manager where your verification stands.",
  };
}

function describeVerification(record: KycRecord): string {
  const kind = documentKindLabel(record.document_kind);
  const when = record.verified_at ? formatIST(record.verified_at) : null;
  if (kind && when) return `We checked your ${kind} on ${when}.`;
  if (when) return `Verified on ${when}.`;
  return "";
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
 */
function WhatItAffects() {
  return (
    <Card title="What this affects while it is outstanding">
      <ul className="space-y-3 text-sm text-slate-600 dark:text-slate-400">
        <li>
          <span className="font-medium text-emerald-700 dark:text-emerald-400">
            Incoming calls: unaffected, on every plan.
          </span>{" "}
          Your agent answers the phone exactly as before. Nothing on this page can stop
          it — the check only ever runs before we dial OUT, and somebody who rang you
          started that call themselves.
        </li>
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            Outgoing calls: stopped on self-serve and trial accounts.
          </span>{" "}
          Campaigns will not launch and one-off outbound calls are refused, naming this
          verification as the reason. Accounts we set up and manage for you are not
          gated here — their identity was verified with us before the number was bought.
        </li>
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            A new phone number: blocked on every account, without exception.
          </span>{" "}
          The obligation attaches to the connection itself, so it applies whoever you
          are and whatever you pay us. Numbers you already have keep working.
        </li>
      </ul>
    </Card>
  );
}

/**
 * The call to action — the one thing the client can actually do.
 *
 * The document list is the one DoT's business-connection instructions ask a licensee
 * for (entity registration, address, GST where applicable, the authorised signatory),
 * which is why the address requirement mentions the city: the operator will not issue a
 * number against an address in a different one.
 */
function WhatWeNeed() {
  return (
    <Card title="What to send us">
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Send these to your account manager and we will verify the account. We only need
        the numbers below — not copies of anything.
      </p>
      <ul className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-400">
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            Your registered business name and what kind of business it is
          </span>{" "}
          — company, LLP, partnership, sole proprietorship, trust or HUF.
        </li>
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            One registration number for the business.
          </span>{" "}
          Any one of: {Object.values(DOCUMENT_KINDS).map((spec) => spec.label).join(", ")}.
        </li>
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            The registered address of the business.
          </span>{" "}
          It has to match the city a number is issued in, so a mismatch is the most
          common reason one gets held up.
        </li>
        <li>
          <span className="font-medium text-slate-800 dark:text-slate-200">
            The name of the person authorised to sign for the business.
          </span>{" "}
          A name only — we do not record their identity document.
        </li>
      </ul>
    </Card>
  );
}

/**
 * The number-purchase capability, stated rather than offered.
 *
 * `number_purchase_available` is the server's own selector — the SAME one
 * `POST /v1/numbers/purchase` asks — so this card cannot promise something the route
 * would refuse. It is two facts joined: this account being verified, AND this
 * deployment having a telephony provider with an adapter behind it. Today the second
 * is false everywhere, so the card explains which half is missing instead of rendering
 * a control whose only possible outcome is an error message.
 */
function PhoneNumbers({ record }: { record: KycRecord }) {
  return (
    <Card title="Buying a phone number">
      {record.number_purchase_available ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Your account can be issued a new number. Ask your account manager and we will
          set it up.
        </p>
      ) : record.is_verified ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Your verification is not what is holding this up — buying a number from this
          screen is not available in Calevate yet. We buy and register numbers for you
          today, so ask your account manager and we will do it. Numbers you already have
          are unaffected.
        </p>
      ) : (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          A new number cannot be issued until your business is verified, on any plan —
          the rule attaches to the connection, not to your plan. Numbers you already have
          keep working. Once this clears, ask your account manager and we will arrange
          it.
        </p>
      )}
    </Card>
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
 */
function OnFile({ record }: { record: KycRecord }) {
  const rows: { label: string; value: string | null }[] = [
    { label: "State", value: stateLabel(record) },
    { label: "Kind of business", value: entityTypeLabel(record.entity_type) },
    {
      label: "Checked against",
      value: joinDocument(documentKindLabel(record.document_kind), record.document_ref),
    },
    { label: "Signed for the business by", value: record.signatory_name },
    { label: "Received", value: record.submitted_at ? formatIST(record.submitted_at) : null },
    { label: "Verified", value: record.verified_at ? formatIST(record.verified_at) : null },
    { label: "Our file reference", value: record.evidence_ref },
  ];
  const present = rows.filter((row) => row.value !== null && row.value !== "");

  return (
    <Card title="What we hold about your business">
      <dl className="space-y-2">
        {present.map((row) => (
          <div key={row.label} className="flex flex-wrap justify-between gap-2 text-sm">
            <dt className="text-slate-500">{row.label}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-200">{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-slate-500">
        That is the whole record — there is nothing else stored about your identity.
      </p>
    </Card>
  );
}

function stateLabel(record: KycRecord): string {
  const status = record.status;
  if (status !== null && isKnownKycStatus(status)) return KYC_STATUS_COPY[status].label;
  return status ?? NOT_RECORDED.label;
}

function joinDocument(kind: string | null, ref: string | null): string | null {
  if (kind && ref) return `${kind} ${ref}`;
  return kind ?? ref;
}
