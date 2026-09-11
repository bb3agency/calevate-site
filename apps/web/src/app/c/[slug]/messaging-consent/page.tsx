"use client";

import { RestrictionNote } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import { CONSENT_SOURCES } from "@/lib/api/messagingConsent";

import { ConsentLookup } from "./ConsentLookup";
import { HowItWorks } from "./HowItWorks";
import { RecordConsent } from "./RecordConsent";
import { NO_STATUSES, STATUS_COPY } from "./statusCopy";
import { useConsentForm } from "./consentForm";

/**
 * Messaging consent (SEC-COMP §4) — the record of who said we may message them.
 *
 * `POST /v1/compliance/messaging-consent` shipped with no screen, so nobody could record
 * an opt-in and every campaign WhatsApp follow-up was refused `recipient_not_opted_in`.
 * This is the way in, and it is four sibling modules (UX-DOCTRINE §6):
 *
 * - `consentForm.ts` — everything the screen HOLDS, and the rules about what may be
 *   recorded, away from the JSX.
 * - `ConsentLookup.tsx` — "can we message this number?", answerable by every session.
 * - `RecordConsent.tsx` — the append-only write, and the four schema rules it must keep.
 * - `HowItWorks.tsx` — the five rules that govern the record, including the two this
 *   screen may never blur.
 *
 * ## THIS IS NOT CONSENT TO BE CALLED, and the screen may never blur the two
 *
 * SEC-COMP §4 is explicit: a campaign's `consent_source` provenance and a `callback`
 * ledger row "never satisfy it, and nothing backfills it". They are different purposes
 * under DPDP §6, they are refused by different gates, and a follow-up message still has
 * to pass `check_dispatch` — the do-not-call read — before this record is even consulted.
 * So every sentence here that could be read as clearance for a CALL is either absent or
 * says which gate it belongs to.
 *
 * **Expired is not green.** A year-old opt-in still has `status: "granted"`, so the
 * verdict renders `messageable` — the server's own "granted AND not stale" — and an
 * expired grant reads as not messageable with the date it lapsed.
 */
export default function MessagingConsentPage() {
  const session = useClientSession();
  const form = useConsentForm(session);

  /**
   * Recording is `leads:dispatch` — the same authority that lets someone cause a
   * person to be contacted, because an opt-in is exactly that decision: it is what
   * turns an exhausted campaign contact into a message. The LOOKUP is `leads:read`
   * and is deliberately not gated here: reading whether somebody may be messaged is
   * not changing it, which is the whole reason the API put it on a read permission.
   *
   * ⚠ THIS SAID the lookup "stays available inside a read-only view as client session
   * (D-22)" — true, but the contrast it drew is gone: D-587 makes `leads:dispatch`
   * writable in a view-as session too, so an operator on a support call gets both halves
   * of this screen and each record is attributed to them. The gate stays for `staff`,
   * who hold neither.
   */
  const write = useWriteAccess(
    session,
    "leads:dispatch",
    "record what a customer said about being messaged",
  );

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * ## The two phone boxes leave as placeholders, and neither is writable
   *
   * Both hold a customer's number (D-127 G-2), so both are `personal: "phone"`. Neither
   * is fillable, and here that is the compliance rule rather than caution: recording a
   * consent is a statement that a NAMED PERSON said something, and an assistant that
   * could put a number in that box could manufacture an opt-in against somebody who
   * never gave one. The same argument bars the CALL ID, which is the evidence tying the
   * statement to the conversation it was made in.
   *
   * ## What IS fillable is the shape of the answer
   *
   * Yes-or-no, which source, and — on a "no" — which withdrawal status. Those are three
   * enums describing an answer a person in front of the form already has, they are the
   * part people get wrong, and none of them is a record until Save is pressed. The source
   * list offered is `form.sourceOptions`, the SAME narrowing the form renders from, so the
   * assistant cannot pick a source that cannot carry the answer being given.
   *
   * The EVIDENCE fields are not declared at all: they are per-source free text ("where in
   * the call", "document reference") and are exactly the place a caller's own words would
   * land.
   *
   * Declared HERE and not inside the record card, which is rendered only for a session
   * that may write: a declaration in there would take the assistant off the screen for
   * every read-only reader.
   */
  useCopilotSurface({
    route: "/c/{slug}/messaging-consent",
    title: "Messaging consent",
    realm: "client",
    fields: [
      {
        id: "consent-lookup-phone",
        label: "Number being looked up",
        type: "text",
        value: form.lookupPhone,
        writable: false,
        personal: "phone",
        help: "Typed by the reader; the assistant is told whether the box is filled in, never what is in it.",
      },
      {
        id: "consent-phone",
        label: "Number the answer is being recorded against",
        type: "text",
        value: form.phone,
        writable: false,
        personal: "phone",
      },
      {
        id: "consent-answer",
        label: "Did the customer agree to be messaged?",
        type: "select",
        value: form.answer,
        options: [
          { value: "yes", label: "Yes — they agreed" },
          { value: "no", label: "No — they did not, or they withdrew" },
        ],
      },
      {
        id: "consent-status",
        label: "How the consent ended, when the answer is no",
        type: "select",
        value: form.status,
        options: NO_STATUSES.map((value) => ({ value, label: STATUS_COPY[value].label })),
        help: "Ignored while the answer is yes — a yes is always recorded as granted.",
      },
      {
        id: "consent-source",
        label: "How they said it",
        type: "select",
        value: form.source,
        options: form.sourceOptions.map((value) => ({ value, label: CONSENT_SOURCES[value].label })),
      },
      {
        id: "consent-call-id",
        label: "Call the statement was made on",
        type: "text",
        value: form.callId,
        writable: false,
        help: "The evidence tying the consent to the conversation. A person supplies it, from the call log.",
      },
    ],
    facts: [
      {
        key: "status_to_be_recorded",
        label: "What pressing Save would record",
        value: form.effectiveStatus,
      },
      {
        key: "call_id_required",
        label: "Does the chosen source need a call id?",
        value: form.spec.requiresCallId ? "yes" : "no",
      },
      {
        key: "blocked",
        label: "Is anything stopping this being recorded as a yes?",
        value: form.blocked ?? "no",
      },
      {
        key: "lookup_answered",
        label: "Is there a lookup verdict on screen?",
        value: form.lookup.data ? "yes — the reader can see it" : "no",
      },
      {
        key: "may_record",
        label: "May this session record what a customer said?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
    ],
    apply: (items) => {
      for (const item of items) {
        const value = asText(item.value);
        if (item.field_id === "consent-answer" && (value === "yes" || value === "no")) {
          form.chooseAnswer(value);
        } else if (item.field_id === "consent-source") {
          const next = form.sourceOptions.find((option) => option === value);
          if (next !== undefined) form.chooseSource(next);
        } else if (item.field_id === "consent-status") {
          const next = NO_STATUSES.find((option) => option === value);
          if (next !== undefined) form.setStatus(next);
        }
      }
    },
  });

  return (
    <div className="space-y-5 pb-12">
      <p className="text-sm text-ink-muted">
        Who has agreed to receive WhatsApp messages from you. Campaign follow-ups are
        only sent to people recorded here — and this is a separate permission from
        calling, which is governed by the do-not-call list.
      </p>

      <RestrictionNote reason={write.reason} />

      {/* The question people actually arrive with, and the one thing everyone with
          access to the account may do. */}
      <ConsentLookup form={form} />

      {write.allowed && <RecordConsent form={form} />}

      <HowItWorks />
    </div>
  );
}
