"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { PeRegistration } from "@/lib/api/dltRegistration";
import type { KycRecord } from "@/lib/api/kyc";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * The verification screen, declared to the assistant (`lib/copilot/registry.ts`).
 *
 * Read-only: both verdicts are recorded by Calevate, which is the point of them.
 * `signatory_name` and `document_ref` are NOT declared: the first names a person and the
 * second identifies their document. The STATUS is what a reader asks about, and it
 * identifies nobody.
 */
export function useVerificationCopilot(
  kyc: UseQueryResult<KycRecord>,
  dlt: UseQueryResult<PeRegistration>,
) {
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
}
