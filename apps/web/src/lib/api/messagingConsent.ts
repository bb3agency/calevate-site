"use client";

/**
 * Messaging consent — may we send this person a business-initiated message?
 * (SEC-COMP §4; `apps/api/compliance/consent.py`; migration c2f7a91b4e63.)
 *
 * Both endpoints shipped without a screen, which left every campaign WhatsApp
 * escalation refused `recipient_not_opted_in` with no way for a human to record the
 * opt-in that would fix it. This module is the client half, and it keeps four API
 * decisions intact rather than smoothing them into something more convenient:
 *
 * - **Both calls are POST, and BOTH are mutations here — including the lookup.** The
 *   phone number IS the personal data, so it never goes in a URL (hard rule 6). A
 *   `useQuery` would undo half of that by writing the number into a cache key that
 *   outlives the answer on screen, so the lookup is a mutation whose result the screen
 *   holds only while it is looking at it. Same reasoning, same shape, as
 *   `useCheckDncNumber` in `dnc.ts`.
 * - **`messageable` is the server's answer and is never re-derived.** It is
 *   "granted AND not stale", both halves, computed by the same code the campaign
 *   worker reads. A screen that recomputed it from `status` would disagree with the
 *   worker on exactly the day it matters — the day the opt-in expires.
 * - **Consent must be EVIDENCED, and the evidence differs by source.** That is why
 *   `CONSENT_SOURCES` below is a table rather than a list of strings: each source
 *   names the fields that can evidence it, so the form changes shape with the source
 *   instead of offering one free-text box. There is no `assumed` and no `implied`
 *   member, here or in the database.
 * - **`staff_recorded_request` cannot GRANT.** A CHECK constraint bars it, and
 *   `canGrant` mirrors that so the source never appears while recording a yes. A
 *   client employee may record that somebody asked to stop, never that somebody
 *   agreed to start — that asymmetry is the whole point of the member.
 *
 * There is no DELETE endpoint and no delete hook. A consent record is append-only
 * (hard rule 4); the way to say "no longer" is a new row with `status: "withdrawn"`.
 */

import { useMutation } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/** Never carries the number back — a status, a source and two timestamps. */
export type MessagingConsent = Schemas["MessagingConsentOut"];
export type RecordConsentBody = Schemas["RecordConsentIn"];
export type ConsentSource = RecordConsentBody["source"];
export type ConsentStatus = RecordConsentBody["status"];

/**
 * Mirrors `consent.MESSAGING_CONSENT_VALIDITY_DAYS`. Used for COPY only — how long an
 * opt-in stays current, said on screen before someone captures one. Whether a
 * particular row is still current is `messageable`, which the server computes; this
 * constant must never be used to decide that.
 */
export const CONSENT_VALIDITY_DAYS = 365;

export interface EvidenceField {
  /** The key written into `evidence` — matches what the migration docstring names. */
  key: string;
  label: string;
  hint: string;
  placeholder: string;
}

export interface ConsentSourceSpec {
  label: string;
  /** What the person actually did, in the client's words. */
  hint: string;
  /**
   * Whether this source may carry a `granted` row.
   * `false` mirrors `WITHDRAWAL_ONLY_CONSENT_SOURCES` and the CHECK
   * `ck_consent_ledger_granted_consent_carries_evidence`.
   */
  canGrant: boolean;
  /** `inbound_call_verbal` grants must name the call they were spoken on. */
  requiresCallId: boolean;
  /** What can evidence this source. Required for a grant, optional for a refusal. */
  evidence: EvidenceField[];
}

/**
 * The five sources, as a `Record` over the GENERATED union rather than a plain object.
 *
 * That is deliberate: if the API ever adds or renames a source, this file stops
 * compiling instead of silently rendering a shorter menu than the schema permits. The
 * evidence keys are the ones migration c2f7a91b4e63's docstring names for each member.
 */
export const CONSENT_SOURCES: Record<ConsentSource, ConsentSourceSpec> = {
  inbound_call_verbal: {
    label: "They said so on a call",
    hint: "The agent asked whether to message them, and they agreed on the call.",
    canGrant: true,
    requiresCallId: true,
    evidence: [
      {
        key: "transcript_span",
        label: "Where in the call",
        hint: "The moment they agreed — e.g. a timestamp range or the line they said it in.",
        placeholder: "02:14–02:21",
      },
    ],
  },
  web_form_optin: {
    label: "They ticked a box on your website",
    hint: "An unticked box they chose to tick — never a pre-ticked one.",
    canGrant: true,
    requiresCallId: false,
    evidence: [
      {
        key: "form_reference",
        label: "Which form",
        hint: "The form they filled in, so it can be produced if the number is challenged.",
        placeholder: "enquiry-form",
      },
      {
        key: "notice_version",
        label: "Wording version shown",
        hint: "The version of the opt-in wording that was on screen when they ticked it.",
        placeholder: "v3 · 2026-04",
      },
    ],
  },
  offline_form_optin: {
    label: "They signed a form in person",
    hint: "Paper or in-store — a form you can produce later.",
    canGrant: true,
    requiresCallId: false,
    evidence: [
      {
        key: "document_reference",
        label: "Document reference",
        hint: "How you would find that form again — a file number, batch or slip number.",
        placeholder: "REG-2026-0481",
      },
    ],
  },
  whatsapp_inbound_message: {
    label: "They messaged you on WhatsApp",
    hint: "They started the conversation, or replied agreeing to be messaged.",
    canGrant: true,
    requiresCallId: false,
    evidence: [
      {
        key: "message_id",
        label: "Message ID",
        hint: "The WhatsApp message their agreement came in.",
        placeholder: "wamid.HBgM…",
      },
    ],
  },
  staff_recorded_request: {
    label: "Someone here recorded their request",
    hint: "A person on your team noting what the customer asked for.",
    // Barred from `granted` by a CHECK: staff asserting an opt-in on a consumer's
    // behalf is "implied consent" wearing a different name.
    canGrant: false,
    requiresCallId: false,
    evidence: [],
  },
};

/** The four sources that may carry a yes. Derived, so it cannot drift from the table. */
export const GRANT_CAPABLE_SOURCES = (Object.keys(CONSENT_SOURCES) as ConsentSource[]).filter(
  (source) => CONSENT_SOURCES[source].canGrant,
);

/**
 * Whatever was typed, trimmed — or `null` when nothing was.
 *
 * A refusal keeps whatever the person recording it could give and demands nothing:
 * consent must be evidenced, a refusal must never be obstructed. Whether a GRANT has
 * enough is `grantBlockReason` below, not this.
 */
export function collectEvidence(
  spec: ConsentSourceSpec,
  values: Record<string, string>,
): Record<string, string> | null {
  const evidence: Record<string, string> = {};
  for (const field of spec.evidence) {
    const value = (values[field.key] ?? "").trim();
    if (value) evidence[field.key] = value;
  }
  return Object.keys(evidence).length > 0 ? evidence : null;
}

/**
 * Why this opt-in cannot be recorded yet, or `null` when it can.
 *
 * The three rules of `_assert_grant_is_evidenced`, said BEFORE the round-trip instead
 * of arriving as a 422 — the same doctrine `useWriteAccess` follows for permissions.
 * The server still enforces all three, and the CHECK constraint enforces them again
 * beneath that; this is a preview of the refusal, never a substitute for it.
 *
 * It exists so the screen cannot grow the thing this whole slice is built to prevent:
 * a submit button that sends a grant with an empty evidence object.
 */
export function grantBlockReason(
  source: ConsentSource,
  values: Record<string, string>,
  callId: string,
): string | null {
  const spec = CONSENT_SOURCES[source];
  if (!spec.canGrant) {
    return "Your team cannot record an opt-in on a customer's behalf — only an opt-out.";
  }
  const missing = spec.evidence.filter((field) => !(values[field.key] ?? "").trim());
  if (missing.length > 0) {
    return `An opt-in has to record what it rests on. Fill in ${missing
      .map((field) => field.label.toLowerCase())
      .join(" and ")}.`;
  }
  if (spec.requiresCallId && !callId.trim()) {
    return "A spoken opt-in has to name the call it was spoken on.";
  }
  return null;
}

/**
 * "May we message this number?" as a POST with the number in the BODY.
 *
 * A mutation, not a query — see the module note. The verdict is returned to the caller
 * and deliberately not cached against the number that produced it.
 */
export function useLookupMessagingConsent(session: Session) {
  return useMutation({
    mutationFn: (phone: string) =>
      apiRequest<MessagingConsent>(session, "/v1/compliance/messaging-consent/lookup", {
        method: "POST",
        body: { phone },
      }),
  });
}

/**
 * Append one row to the consent ledger. Never an update, never a delete.
 *
 * No cache invalidation: there is no list endpoint to invalidate, and the response is
 * the new current state for that number. The screen resets any lookup verdict it is
 * showing instead, because a verdict rendered before this write may now be wrong.
 */
export function useRecordMessagingConsent(session: Session) {
  return useMutation({
    mutationFn: (body: RecordConsentBody) =>
      apiRequest<MessagingConsent>(session, "/v1/compliance/messaging-consent", {
        method: "POST",
        body,
      }),
  });
}
