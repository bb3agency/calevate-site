"use client";

import type { ComponentType } from "react";
import { PhoneIncoming, PhoneOutgoing, PhoneOff, ShieldAlert, ShieldCheck } from "lucide-react";

import { Card, MonoValue, NoticeBox, ProblemNotice, Skeleton, TermGloss, formatIST } from "@/components/ui";
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
import {
  peStatusCopy,
  tmLinkCopy,
  usePeRegistration,
  type PeRegistration,
} from "@/lib/api/dltRegistration";
import type { Session } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * Business verification — the page somebody opens because their calls stopped.
 *
 * `check_dispatch` refuses a self-serve account's outbound with `kyc_missing` /
 * `kyc_not_verified`, `launch_blockers` previews the same two names, and
 * `POST /v1/numbers/purchase` refuses every tier on the same fact. Until now none of
 * those refusals had anywhere to send anyone.
 *
 * WHY THERE IS NO "BUY A NUMBER" CONTROL ON THIS PAGE, and it is a decision rather than
 * an unfinished feature: `campaigns.provisioning.PROVISIONING_IMPLEMENTED = False`, and
 * flipping it would be adopting Model A — Calevate holding connections and allocating
 * them — which `docs/legal/LEGAL-OPS-PLAYBOOK.md` refuses at `:249` for a sole proprietor
 * with no corporate veil, and again in its stop-list at items 1 and 10. The client takes
 * the connection in their own name with their own carrier and stays subscriber of record;
 * the published Terms (clause 3) and Acceptable Use (§2.1) say the same thing, so this
 * page must not imply otherwise.
 *
 * That sentence is also load-bearing for a guard. `scripts/check_docs_drift.py` §5
 * compares prose that STATES a capability constant's value against the constant itself,
 * across three prose kinds — markdown, Python docstrings, and the console's JSDoc — and
 * this file is the console's only such claim, so `tests/capability_claim_guard_test.py`
 * uses it to prove the TSX scanner still works. Deleting it does not merely lose a true
 * statement; it leaves that arm of the scanner unproven. So this screen is not a status readout;
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
 * 5. **We do not supply phone numbers, and the screen says so plainly.** Model B:
 *    the client takes the connection in their own name on their own Exotel / Plivo /
 *    Vobiz account, passes that operator's KYC, remains the subscriber of record, and
 *    issues us API credentials they can withdraw (`docs/legal/LEGAL-OPS-PLAYBOOK.md`
 *    §9; published Terms clause 3; Acceptable Use §2.1). `number_purchase_available` is
 *    false for every account in every deployment and always will be — it is false by
 *    DECISION, not because an adapter is missing — so there is no purchase form and no
 *    "we will arrange it" promise. What the card gives instead is the actual next step,
 *    because a client who is told only "not here" comes back with a support ticket.
 *
 * Read-only throughout, deliberately: `org:read` is not a mutating permission and BOTH
 * client roles hold it (core/rbac.py), so every reader of this page may read all of it
 * and there is no control to gate. It therefore keeps working inside a D-22 "view as
 * client" session — the session a support person is in exactly when this account is the
 * thing being discussed.
 *
 * Restyled to the console's design language (globals.css tokens, `Card`, the shared
 * `NOTICE_TONES` verdict palette, lucide icons as affordances) with the verdict logic
 * untouched: the icon and the colour below are both keyed on `is_verified`, so the badge
 * cannot drift from the sentence beside it. The screen's own `<h1>` is gone — the shell
 * prints "Verification" from the nav list (layout.tsx).
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

/** The lead-in of a list item: the claim, before the paragraph that qualifies it. */
const LEAD_IN = "font-semibold text-ink";
const LIST = "space-y-3 text-sm text-ink-muted";

export default function VerificationPage() {
  const session = useClientSession();
  /*
   * THE SAME TWO READS THE SECTIONS BELOW MAKE, and not a third round trip: TanStack
   * dedupes by query key, so calling the hooks here shares the sections' own answers.
   * Declaring the surface in the page rather than inside the two children is what keeps
   * the launcher on screen while they are loading and after either has failed — the
   * child effects commit first, so a child declaration would also shadow the other's.
   */
  const kyc = useKycRecord(session);
  const dlt = usePeRegistration(session);

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * READ-ONLY: nothing on this screen is editable by anyone in the client realm — both
   * verdicts are recorded by Calevate, which is the point of them.
   *
   * `signatory_name` and `document_ref` are on the payload and are NOT declared: the
   * first names a human being and the second identifies their identity document, which
   * is the densest personal data this account holds about its own owner. The STATUS of
   * each is what a person on this screen is asking about, and it identifies nobody.
   */
  useCopilotSurface({
    route: "/c/{slug}/verification",
    title: "Verification",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "kyc_state",
        label: "Has the business-verification record loaded?",
        value: kyc.data ? "yes" : kyc.error ? "no — it failed to load" : "still loading",
      },
      ...(kyc.data
        ? [
            {
              key: "kyc_verified",
              label: "Is the business behind this account verified?",
              value: kyc.data.is_verified ? "yes" : "no",
            },
            { key: "kyc_status", label: "Verification status", value: kyc.data.status ?? "nothing submitted" },
            { key: "kyc_entity_type", label: "Kind of business recorded", value: kyc.data.entity_type ?? "none recorded" },
            { key: "kyc_document_kind", label: "Kind of document on file", value: kyc.data.document_kind ?? "none" },
            { key: "kyc_submitted_at", label: "Submitted (UTC)", value: kyc.data.submitted_at ?? "never" },
            { key: "kyc_verified_at", label: "Verified (UTC)", value: kyc.data.verified_at ?? "not verified" },
            {
              key: "kyc_rejection_reason",
              label: "Why it was rejected, if it was",
              value: kyc.data.rejection_reason ?? "not rejected",
            },
            {
              key: "number_purchase_available",
              label: "May this account be given a phone number yet?",
              value: kyc.data.number_purchase_available ? "yes" : "no",
            },
          ]
        : []),
      {
        key: "dlt_state",
        label: "Has the DLT registration record loaded?",
        value: dlt.data ? "yes" : dlt.error ? "no — it failed to load" : "still loading",
      },
      ...(dlt.data
        ? [
            {
              key: "dlt_recorded",
              label: "Is a DLT registration on file?",
              value: dlt.data.recorded ? "yes" : "no",
            },
            { key: "dlt_active", label: "Is it active?", value: dlt.data.is_active ? "yes" : "no" },
            { key: "dlt_status", label: "Registration status", value: dlt.data.status ?? "none" },
            {
              key: "dlt_tm_link_status",
              label: "Is Calevate linked as the telemarketer on it?",
              value: dlt.data.tm_link_status ?? "not stated",
            },
            { key: "dlt_registered_at", label: "Registered (UTC)", value: dlt.data.registered_at ?? "never" },
            { key: "dlt_verified_at", label: "Verified (UTC)", value: dlt.data.verified_at ?? "not verified" },
          ]
        : []),
    ],
    apply: noFill,
  });

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Indian telecom rules require two separate things of a business before it may place
        calls: that the business behind the connection is identified, and that it is
        registered with the{" "}
        <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss> registrar to
        run campaigns. Both are below. Either one outstanding stops outgoing calls; neither
        one affects the calls coming in.
      </p>

      {/* Two independent reads, two independent sections. Composed rather than nested so
          a failure of one is never allowed to blank the other: a client whose KYC read
          503s is very often the same client trying to find out why their campaigns are
          refused, and the answer to that question lives in the second section. */}
      <SubscriberVerification session={session} />
      <DltRegistration session={session} />
    </div>
  );
}

/** The KYC half: who this business is, as we verified it. */
function SubscriberVerification({ session }: { session: Session }) {
  const record = useKycRecord(session);

  if (record.isLoading) return <Skeleton rows={6} />;

  /**
   * A refusal we received, or an answer that never arrived — one branch, because to the
   * client they are the same sentence and it is not "you are cleared".
   *
   * The second half used to `return null`. `isLoading` is false whenever the query is
   * pending but not FETCHING — which is what TanStack Query does while the browser is
   * offline (`fetchStatus: "paused"`) — so a client on a train got a blank page where
   * the state of their verification should be. There is no `ApiProblem` to render in
   * that case, and `ProblemNotice` says exactly the right thing for it.
   */
  if (record.error || !record.data) {
    return (
      <ProblemNotice
        error={record.error ?? new Error("The verification record did not load.")}
        onRetry={() => void record.refetch()}
      />
    );
  }

  const kyc = record.data;

  return (
    <div className="space-y-5">
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
            {/* This bullet used to end "your campaign screen names the DLT ones
                separately" — true while the DLT state had no page. It is on this one
                now, so the sentence points down the page instead of away from it. */}
            <span className={LEAD_IN}>
              This is separate from your{" "}
              <TermGloss term="DLT">India&apos;s telecom message registry</TermGloss>{" "}
              registration.
            </span>{" "}
            The two overlap in the documents they rest on, but they are held by different
            people for different purposes, and neither one clears the other. Your campaign
            registration is the next section.
          </li>
        </ul>
      </Card>
    </div>
  );
}

/**
 * The DLT half: whether the registrar has this business as a Principal Entity, and
 * whether that entity authorises Calevate to dial for it.
 *
 * This is the fact behind `pe_registration_missing` / `pe_registration_not_active` /
 * `tm_link_not_active` — three of the launch gate's refusals — and it had no screen. A
 * client whose campaign button was disabled could read the blocker and could not read the
 * registration it was about.
 *
 * §52 in three branches, and the middle one is the point: a read that FAILED must not
 * render as "nothing filed yet". `recorded: false` and "we could not ask" are opposite
 * facts that would produce the same card, and the first sends a client to their account
 * manager over a registration that may be perfectly active.
 *
 * Read-only with no control anywhere, and that is not an omission — see the module
 * docstring on `lib/api/dltRegistration.ts`. The write is operator-only because a client
 * who could set these two statuses would be clearing their own compliance gate. So there
 * is nothing here for `useWriteAccess` to gate, and no `RestrictionNote`: `org:read` is
 * held by every client role and survives a D-22 read-only session.
 */
function DltRegistration({ session }: { session: Session }) {
  const registration = usePeRegistration(session);

  if (registration.isLoading) {
    return (
      <Card title="Campaign registration (DLT)">
        <Skeleton rows={4} />
      </Card>
    );
  }

  if (registration.error || !registration.data) {
    return (
      <Card title="Campaign registration (DLT)">
        <ProblemNotice
          error={
            registration.error ??
            new Error("Your DLT registration did not load, so we cannot say where it stands.")
          }
          onRetry={() => void registration.refetch()}
        />
      </Card>
    );
  }

  const pe = registration.data;
  return (
    <Card title="Campaign registration (DLT)">
      <DltVerdict registration={pe} />
      <DltStatuses registration={pe} />
      {pe.recorded && <DltOnFile registration={pe} />}
      <p className="mt-3 text-xs text-ink-faint">
        We record this against the registrar on your behalf and cannot change what it says
        — there is no control here that sets your own status, for the same reason there is
        none above.
      </p>
    </Card>
  );
}

/**
 * Cleared or not, in one box — off `is_active`, never off `status`.
 *
 * The same doctrine as `Verdict` above: the server computes the predicate the launch gate
 * asks (`PeRegistration.is_active` = both statuses active), so a screen that recombined
 * the two statuses itself would eventually disagree with the gate that actually refuses
 * the campaign. The icon is keyed on the same boolean as the sentence.
 */
function DltVerdict({ registration }: { registration: PeRegistration }) {
  const Icon = registration.is_active ? ShieldCheck : ShieldAlert;
  return (
    <NoticeBox
      tone={registration.is_active ? "ok" : registration.recorded ? "warn" : "neutral"}
      icon={<Icon className="h-5 w-5" />}
      title={
        registration.is_active
          ? "Your business is registered to run campaigns."
          : registration.recorded
            ? "Your DLT registration is not active yet."
            : "We have not filed a DLT registration for your business."
      }
    >
      <div className="min-w-0">
        <p className="mt-1">
          {registration.is_active
            ? "Nothing on the DLT side is holding up a campaign launch."
            : "Outbound campaigns cannot launch until both lines below are active."}
        </p>
        {!registration.is_active && (
          <p className="mt-2 font-semibold">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>
    </NoticeBox>
  );
}

/**
 * The two statuses, side by side, because they fail separately and to different desks.
 *
 * The registrar approves the entity; YOU authorise Calevate as your telemarketer on the
 * registrar's portal. Collapsing them into one verdict would send half the clients who
 * read this to the wrong place — which is exactly why the API emits
 * `pe_registration_not_active` and `tm_link_not_active` as different blockers.
 *
 * A status this build cannot name prints the raw word from the wire with a sentence that
 * claims nothing about it. Vaguer than the table, and it cannot be wrong.
 */
function DltStatuses({ registration }: { registration: PeRegistration }) {
  const entity = peStatusCopy(registration.status);
  const link = tmLinkCopy(registration.tm_link_status);
  return (
    <dl className="mt-4 space-y-3 text-sm">
      <div>
        <dt className="font-semibold text-ink">
          Your business as a{" "}
          <TermGloss term="Principal Entity">the business the registrar recognises as responsible for these campaigns</TermGloss>
          : {entity?.label ?? registration.status ?? "not filed"}
        </dt>
        <dd className="text-ink-muted">
          {entity?.next ??
            (registration.recorded
              ? "Ask your account manager what this state means for your campaigns."
              : "Nothing has been filed with the registrar for your business yet. Ask your account manager to start it.")}
        </dd>
      </div>
      <div>
        <dt className="font-semibold text-ink">
          Calevate authorised to dial for you:{" "}
          {link?.label ?? registration.tm_link_status ?? "not filed"}
        </dt>
        <dd className="text-ink-muted">
          {link?.next ??
            (registration.recorded
              ? "Ask your account manager where this authorisation stands."
              : "This authorisation follows the registration above; there is nothing to authorise until that exists.")}
        </dd>
      </div>
    </dl>
  );
}

/**
 * What is on file, shown to the business it is about.
 *
 * `verified_at` is when WE last checked this against the registrar, not when we last
 * hoped — the route's docstring is explicit — so it is labelled that way. A row with no
 * value is dropped rather than dashed, the same rule `OnFile` follows above.
 */
function DltOnFile({ registration }: { registration: PeRegistration }) {
  const rows: { label: string; value: string | null; mono?: boolean }[] = [
    { label: "Registered business name", value: registration.entity_name },
    { label: "Principal Entity ID", value: registration.pe_id, mono: true },
    {
      label: "Registered with the registrar",
      value: registration.registered_at ? formatIST(registration.registered_at) : null,
    },
    {
      label: "We last checked",
      value: registration.verified_at ? formatIST(registration.verified_at) : null,
    },
  ];
  const present = rows.filter((row) => row.value !== null && row.value !== "");
  if (present.length === 0) return null;

  return (
    <dl className="mt-4 divide-y divide-line">
      {present.map((row) => (
        <div
          key={row.label}
          className="flex flex-wrap justify-between gap-2 py-2 text-sm first:pt-0 last:pb-0"
        >
          <dt className="text-ink-muted">{row.label}</dt>
          <dd className="font-semibold text-ink">
            {row.mono ? <MonoValue>{row.value}</MonoValue> : row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Where the account stands, in one box.
 *
 * `is_verified` decides the green path — never `status === "verified"` — so a status
 * this build has never heard of cannot be rendered as cleared. An unknown status falls
 * back to "not verified yet, ask us where it stands", which is vaguer than we would
 * like and still the only answer that cannot be wrong.
 *
 * The ICON is keyed on the same boolean rather than on the tone, for the same reason:
 * a shield with a tick is the most-read pixel in the box, and it must be answering the
 * gate's question and not a copy table's mood.
 */
function Verdict({ record }: { record: KycRecord }) {
  const copy = verdictCopy(record);
  const Icon = record.is_verified ? ShieldCheck : ShieldAlert;
  return (
    <NoticeBox tone={copy.tone} icon={<Icon className="h-5 w-5" />} title={copy.headline}>
      <div className="min-w-0">
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
            <span className="font-semibold">What we said:</span> {record.rejection_reason}
          </p>
        )}
        {!record.is_verified && (
          <p className="mt-2 font-semibold">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>
    </NoticeBox>
  );
}

/** What we can say about a record whose status this build cannot name. */
const UNNAMED_STATUS: VerdictCopy = {
  ...NOT_RECORDED,
  headline: "Your business is not verified yet.",
  next: "Ask your account manager where your verification stands.",
};

/**
 * The words for this state — with `is_verified` choosing the DIRECTION and `status`
 * only choosing the wording within it.
 *
 * This used to be `KYC_STATUS_COPY[status]` outright, which handed the headline and the
 * tone to the status label alone. That is the re-derivation this module's docstring
 * forbids, and it fails in the expensive direction: a record still labelled `verified`
 * whose `is_verified` has gone false rendered a GREEN box saying "Your business is
 * verified. Nothing here is holding up your calls." while `check_dispatch` refused every
 * outbound call on the same account. The remediation cards below already keyed on the
 * boolean, so the screen contradicted itself in the same scroll.
 *
 * `is_verified` is today `status == "verified"` (`compliance/kyc.py`), so the two cannot
 * yet disagree — which is exactly why this is worth pinning now rather than after an
 * expiry clause lands in that property and a client is told they are cleared for a week.
 *
 * Both directions are covered on purpose: a status we cannot name under a TRUE
 * `is_verified` gets the cleared copy, because refusing to say "you are verified" when
 * the gate says so sends a client chasing a block that does not exist.
 */
function verdictCopy(record: KycRecord): VerdictCopy {
  if (!record.recorded) return NOT_RECORDED;
  const status = record.status;
  const named = status !== null && isKnownKycStatus(status) ? KYC_STATUS_COPY[status] : null;
  if (record.is_verified) return named?.tone === "ok" ? named : KYC_STATUS_COPY.verified;
  return named !== null && named.tone !== "ok" ? named : UNNAMED_STATUS;
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
 *
 * The icons carry the direction of the call, which is the whole distinction the list is
 * making and the one a worried client skims for.
 */
function WhatItAffects() {
  return (
    <Card title="What this affects while it is outstanding">
      <ul className="space-y-3 text-sm text-ink-muted">
        <Affected icon={PhoneIncoming} tone="ok" claim="Incoming calls: unaffected, on every plan.">
          Your agent answers the phone exactly as before. Nothing on this page can stop
          it — the check only ever runs before we dial OUT, and somebody who rang you
          started that call themselves.
        </Affected>
        <Affected
          icon={PhoneOutgoing}
          claim="Outgoing calls: stopped on self-serve and trial accounts."
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
    </Card>
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
    </Card>
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
function PhoneNumbers({ record }: { record: KycRecord }) {
  return (
    <Card title="Where your calling number comes from">
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
          <span className={LEAD_IN}>Open the account and pass their KYC.</span> They ask
          for the same business details we ask for below, and the address proof normally
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
    <Card title="What we hold about your business">
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
