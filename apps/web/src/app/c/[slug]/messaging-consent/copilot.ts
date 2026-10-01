"use client";

import { CONSENT_SOURCES } from "@/lib/api/messagingConsent";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { type ConsentForm } from "./consentForm";
import { NO_STATUSES, STATUS_COPY } from "./statusCopy";

/**
 * The messaging-consent screen, declared to the assistant (`lib/copilot/registry.ts`).
 * Declared from the page, not the record drawer, so a read-only reader keeps it.
 */
export function useConsentCopilot(form: ConsentForm, write: { allowed: boolean; reason: string | null | undefined }) {
  // Both phone boxes hold a customer's number (D-127 G-2), so they are `personal` and
  // neither is writable: an assistant that could fill one could manufacture an opt-in
  // against somebody who never gave one. The call id is barred for the same reason, and
  // the per-source evidence text is not declared at all. What IS fillable is the shape of
  // the answer (yes/no, source, kind of no), offered from the same `form.sourceOptions`
  // the form renders, so no source can be picked that cannot carry the answer.
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
}
