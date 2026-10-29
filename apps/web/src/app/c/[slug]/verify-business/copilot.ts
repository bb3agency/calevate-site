"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { CallingNumberDeclaration } from "@/lib/api/autodialerNotice";
import type { PeRegistration } from "@/lib/api/dltRegistration";
import type { KycRecord } from "@/lib/api/kyc";
import type { OutboundPledge } from "@/lib/api/verifyBusiness";
import { formatISTStamp } from "@/components/ui";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill, type CopilotFact } from "@/lib/copilot/types";

/**
 * Verify your business, declared to the assistant (`lib/copilot/registry.ts`).
 *
 * No fields: the forms here are the owner's own acts (uploads, the pledge), and the
 * verdicts are recorded by Calevate, which is the point of them. `signatory_name`,
 * `document_ref`, `gstin` and the masked owner ID are NOT declared: the first names a
 * person and the others identify a document. The STATUS is what a reader asks about, and
 * it identifies nobody. The calling-numbers form declares its own fields while it is open
 * (`CallingNumbers`), carrying these facts with it; declaring stays the owner's press.
 */
export function useVerifyBusinessCopilot(
  kyc: UseQueryResult<KycRecord>,
  pledge: UseQueryResult<OutboundPledge>,
  dlt: UseQueryResult<PeRegistration>,
  outgoingOpen: boolean | null,
  declaration: UseQueryResult<CallingNumberDeclaration>,
): CopilotFact[] {
  const facts = verifyBusinessFacts(kyc, pledge, dlt, outgoingOpen, declaration);
  useCopilotSurface({
    route: "/c/{slug}/verify-business",
    title: "Verify your business",
    realm: "client",
    fields: [],
    facts,
    apply: noFill,
  });
  return facts;
}

function verifyBusinessFacts(
  kyc: UseQueryResult<KycRecord>,
  pledge: UseQueryResult<OutboundPledge>,
  dlt: UseQueryResult<PeRegistration>,
  outgoingOpen: boolean | null,
  declaration: UseQueryResult<CallingNumberDeclaration>,
): CopilotFact[] {
  return [
      {
        key: "outgoing_open",
        label: "Are outgoing calls open for this account?",
        value: outgoingOpen === null ? "not known — a record did not load" : outgoingOpen ? "yes" : "no",
      },
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
            { key: "kyc_path", label: "How the owner is being verified", value: kyc.data.kyc_path ?? "not chosen" },
            { key: "kyc_document_kind", label: "Kind of document on file", value: kyc.data.document_kind ?? "none" },
            {
              key: "kyc_business_certificate",
              label: "Is a business certificate uploaded?",
              value: kyc.data.documents.some((document) => document.slot === "business") ? "yes" : "no",
            },
            {
              key: "kyc_digilocker_outstanding",
              label: "Have we asked for a DigiLocker check that is not done yet?",
              value: kyc.data.digilocker_outstanding ? "yes" : "no",
            },
            { key: "kyc_submitted_at", label: "Submitted (IST)", value: formatISTStamp(kyc.data.submitted_at, "never") },
            { key: "kyc_verified_at", label: "Verified (IST)", value: formatISTStamp(kyc.data.verified_at, "not verified") },
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
        key: "pledge_state",
        label: "Has the no-cold-calls pledge loaded?",
        value: pledge.data ? "yes" : pledge.error ? "no — it failed to load" : "still loading",
      },
      ...(pledge.data
        ? [
            {
              key: "pledge_current",
              label: "Is the current no-cold-calls pledge accepted?",
              value: pledge.data.is_current ? "yes" : pledge.data.accepted_version === null ? "no, never accepted" : "no, an older version was",
            },
            { key: "pledge_accepted_at", label: "Pledge accepted (IST)", value: formatISTStamp(pledge.data.accepted_at, "never") },
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
            { key: "dlt_registered_at", label: "Registered (IST)", value: formatISTStamp(dlt.data.registered_at, "never") },
            { key: "dlt_verified_at", label: "Verified (IST)", value: formatISTStamp(dlt.data.verified_at, "not verified") },
          ]
        : []),
    ...callingNumberFacts(declaration),
  ];
}

function callingNumberFacts(declaration: UseQueryResult<CallingNumberDeclaration>): CopilotFact[] {
  const data = declaration.data;
  if (!data) {
    return [
      {
        key: "calling_numbers_state",
        label: "Has the calling-numbers declaration loaded?",
        value: declaration.error ? "no — it failed to load" : "still loading",
      },
    ];
  }
  return [
    {
      key: "calling_numbers_applies",
      label: "Does an agent on this account place calls (so numbers need declaring)?",
      value: data.applies ? "yes" : "no",
    },
    {
      key: "calling_numbers_declared",
      label: "Are the calling numbers declared and in effect?",
      value: data.effective && data.blocker === null ? "yes" : "no",
    },
    {
      key: "calling_numbers_check",
      label: "What the call check says about them",
      value: data.blocker?.reason ?? "nothing: they are covered",
    },
    {
      key: "calling_numbers_enforced_from",
      label: "From which day calls from undeclared numbers are refused",
      value: data.enforced_from,
    },
    { key: "calling_numbers_enforced", label: "Has that day come?", value: data.enforced ? "yes" : "no" },
    {
      key: "calling_numbers_undeclared",
      label: "Agent numbers not yet declared",
      value: String(data.undeclared_clis.length),
    },
    {
      key: "calling_numbers_where",
      label: "Where they are declared",
      value: "the Calling numbers card on this screen; only someone at the business can press Declare numbers",
    },
  ];
}
