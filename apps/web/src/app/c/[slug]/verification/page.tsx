"use client";

import { useKycRecord } from "@/lib/api/kyc";
import { usePeRegistration } from "@/lib/api/dltRegistration";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { Term } from "@/lib/glossary";

import { DltRegistration } from "./DltRegistration";
import { SubscriberVerification } from "./SubscriberVerification";

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
 * uses it to prove the TSX scanner still works, BY THIS EXACT PATH. Deleting it does not
 * merely lose a true statement; it leaves that arm of the scanner unproven, and moving it
 * to a sibling module fails that test. So this screen is not a status readout;
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
 * thing being discussed. `tests/readiness_copy_actionability_test.py` asserts that
 * read-only-ness over this whole directory, which is what lets `readiness.ROW_COPY` go
 * on telling a client to SEND us something rather than to type it here.
 *
 * The screen itself is the two sibling modules below (UX-DOCTRINE §6): this route keeps
 * the intro, the assistant declaration and nothing else.
 */
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
        <Term id="dlt" /> registrar to
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
