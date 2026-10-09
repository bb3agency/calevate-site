"use client";

/**
 * "Verify your business" (D-692): the client's half of KYC and the no-cold-calls pledge.
 *
 * Outbound calling needs both — a verified KYC record and an accepted, current pledge —
 * on every plan. The client chooses how to verify: upload documents for our review, or
 * verify the owner through DigiLocker. The business certificate is needed either way.
 *
 * What the server decides and this module never re-derives: `is_verified`,
 * `digilocker_outstanding` and the pledge's `is_current`. A screen that recomputed them
 * would disagree with the dial gate on exactly the day it matters.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, apiUpload, type Session } from "./client";
import { KYC_PATH, type KycRecord } from "./kyc";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KycDocument = Schemas["KycDocumentOut"];
export type BusinessDetailsIn = Schemas["BusinessDetailsIn"];
export type ManualSubmitIn = Schemas["ManualSubmitIn"];
export type OutboundPledge = Schemas["OutboundPledgeOut"];
export type StartVerificationOut = Schemas["StartVerificationOut"];
export type CompleteVerificationOut = Schemas["CompleteVerificationOut"];

export const PLEDGE_PATH = "/v1/compliance/outbound-pledge";

/** The certificate the numbering application accepts, in the client's words. */
export const BUSINESS_DOCUMENT_KINDS = {
  gst: "GST registration certificate",
  incorporation: "Certificate of Incorporation",
  udyam: "Udyam registration certificate",
} as const;
export type BusinessDocumentKind = keyof typeof BUSINESS_DOCUMENT_KINDS;

/** The owner IDs accepted for review. Aadhaar only as UIDAI's masked copy. */
export const OWNER_ID_KINDS = {
  aadhaar: "Aadhaar (masked copy)",
  pan_card: "PAN card",
} as const;
export type OwnerIdKind = keyof typeof OWNER_ID_KINDS;

export const MAX_DOCUMENT_BYTES = 5 * 1024 * 1024;
export const MAX_FILENAME_CHARS = 99;
const ACCEPTED_EXTENSIONS = ["pdf", "jpg", "jpeg", "png"];
export const ACCEPT_ATTRIBUTE = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/** The PAN shape the Income Tax Department issues: five letters, four digits, a letter. */
export const PAN_PATTERN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
/** A GSTIN's shape (the server checks the same pattern). */
export const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

/**
 * Why this file cannot be sent, or `null`. A PREVIEW of the server's refusal, so the
 * client learns about a 9 MB scan before it crosses their connection; the server checks
 * the same limits and also the file's bytes.
 */
export function fileProblem(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return "Choose a PDF, JPEG or PNG file.";
  }
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_DOCUMENT_BYTES) {
    return "That file is over 5 MB. Send a smaller scan or a compressed PDF.";
  }
  if (file.name.length > MAX_FILENAME_CHARS) {
    return `Shorten the filename to ${MAX_FILENAME_CHARS} characters or fewer.`;
  }
  return null;
}

/** The owner ID as the client types it: a PAN in full, or the Aadhaar's LAST FOUR only. */
export function ownerIdProblem(kind: "aadhaar" | "pan", value: string): string | null {
  const cleaned = value.trim().toUpperCase();
  if (kind === "pan") {
    return PAN_PATTERN.test(cleaned) ? null : "A PAN is five letters, four digits and a letter.";
  }
  return /^[0-9]{4}$/.test(cleaned)
    ? null
    : "Type only the last four digits of the Aadhaar — never the full number.";
}

function invalidate(client: ReturnType<typeof useQueryClient>, session: Session): void {
  void client.invalidateQueries({ queryKey: ["kyc", session.orgSlug] });
}

export function useSaveBusinessDetails(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: BusinessDetailsIn) =>
      apiRequest<KycRecord>(session, `${KYC_PATH}/details`, { method: "PUT", body }),
    onSuccess: () => invalidate(client, session),
  });
}

export function useUploadKycDocument(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ slot, kind, file }: { slot: "business" | "owner_id"; kind: string; file: File }) => {
      const form = new FormData();
      form.set("slot", slot);
      form.set("kind", kind);
      form.set("file", file);
      return apiUpload<KycDocument>(session, `${KYC_PATH}/documents`, form);
    },
    onSuccess: () => invalidate(client, session),
  });
}

export function useSubmitForReview(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ManualSubmitIn) =>
      apiRequest<KycRecord>(session, `${KYC_PATH}/submit`, { method: "POST", body }),
    onSuccess: () => invalidate(client, session),
  });
}

export function useStartDigiLocker(session: Session) {
  return useMutation({
    mutationFn: (body: { entity_type: string; id_document: "aadhaar" | "pan" }) =>
      apiRequest<StartVerificationOut>(session, `${KYC_PATH}/verification`, {
        method: "POST",
        body,
      }),
  });
}

export function useCompleteDigiLocker(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (providerRef: string) =>
      apiRequest<CompleteVerificationOut>(session, `${KYC_PATH}/verification/complete`, {
        method: "POST",
        body: { provider_ref: providerRef },
      }),
    onSuccess: () => invalidate(client, session),
  });
}

export function useOutboundPledge(session: Session): UseQueryResult<OutboundPledge> {
  return useQuery({
    queryKey: ["outbound-pledge", session.orgSlug],
    queryFn: () => apiRequest<OutboundPledge>(session, PLEDGE_PATH),
  });
}

export function useAcceptPledge(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (pledge: Pick<OutboundPledge, "version" | "text_sha256">) =>
      apiRequest<OutboundPledge>(session, PLEDGE_PATH, {
        method: "POST",
        body: { version: pledge.version, text_sha256: pledge.text_sha256 },
      }),
    onSuccess: (fresh) => client.setQueryData(["outbound-pledge", session.orgSlug], fresh),
  });
}

/** What still stands between this account and outbound calls, in the order to fix it. */
export function outboundSteps(record: KycRecord, pledge: OutboundPledge | undefined): string[] {
  const steps: string[] = [];
  if (!record.is_verified) {
    steps.push(
      record.status === "submitted" || record.status === "in_review"
        ? "Your documents are with our review team."
        : "Verify your business.",
    );
  } else if (record.digilocker_outstanding) {
    steps.push("Complete the DigiLocker verification we asked for.");
  }
  if (pledge && !pledge.is_current) {
    steps.push(
      pledge.accepted_version === null
        ? "Accept the no-cold-calls pledge."
        : "Accept the updated no-cold-calls pledge.",
    );
  }
  return steps;
}

/**
 * A started DigiLocker run's reference, kept while the client is at DigiLocker so the page
 * can finish it on return. Keyed by account: one tab can hold two accounts' consoles, and
 * an unscoped key once finished one account's run on another's page. Storage can be
 * unavailable (a private window, blocked site data), so every access is guarded and a
 * missing value falls back to the `provider_ref` the return URL carries.
 */
const PENDING_RUN_PREFIX = "calevate.kyc.pendingRun";

export function pendingRunKey(orgSlug: string): string {
  return `${PENDING_RUN_PREFIX}:${orgSlug}`;
}

export function rememberPendingRun(orgSlug: string, providerRef: string): void {
  try {
    window.sessionStorage.setItem(pendingRunKey(orgSlug), providerRef);
  } catch {
    // The return URL still carries the reference.
  }
}

export function readPendingRun(orgSlug: string): string | null {
  try {
    return window.sessionStorage.getItem(pendingRunKey(orgSlug));
  } catch {
    return null;
  }
}

/** Forget the run once it has an outcome, so a reload does not ask about it again. */
export function forgetPendingRun(orgSlug: string): void {
  try {
    window.sessionStorage.removeItem(pendingRunKey(orgSlug));
    // The unscoped key an earlier build wrote; it named no account, so it is never read.
    window.sessionStorage.removeItem(PENDING_RUN_PREFIX);
  } catch {
    // Nothing to clean up.
  }
}

/** What a finished DigiLocker run means for the client, where the record alone does not say. */
export const DIGILOCKER_OUTCOME: Readonly<Record<string, { tone: "warn" | "neutral"; title: string; body: string }>> = {
  expired: {
    tone: "warn",
    title: "That DigiLocker visit expired",
    body: "It was not finished in time, so nothing was recorded. Start DigiLocker again below.",
  },
  replay: {
    tone: "neutral",
    title: "That DigiLocker visit was already recorded",
    body: "Nothing changed. What it found is shown on this page.",
  },
};
