"use client";

/**
 * The operator's payments page (D-699): Razorpay mode and credentials (set or not, never
 * the values), the webhook to register, payment alarms, live recent payments, the
 * reconciliation, and disputes with contest and accept.
 *
 * Accept and contest each need `X-Confirm-Action: dispute_<act>:<dispute id>` and a fresh
 * second factor (`payment_admin_routes.dispute_confirmation`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { needsReauthentication } from "@/lib/authn/problems";
import { withActionCode } from "@/lib/authn/stepUpPrompt";

import { adminSession, confirmedAdminRequest, RECONCILE_PAYMENTS_CONFIRMATION } from "./admin";
import { apiRequest, apiUpload } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type PaymentStatus = Schemas["PaymentStatusOut"];
export type RecentPayment = Schemas["RecentPaymentOut"];
export type Dispute = Schemas["DisputeOut"];
export type ReconcileReport = Schemas["ReconcileOut"];

const BASE = "/v1/admin/payments";

export const paymentKeys = {
  status: ["admin-payments", "status"] as const,
  recent: ["admin-payments", "recent"] as const,
  disputes: (closed: boolean) => ["admin-payments", "disputes", closed] as const,
};

export function usePaymentStatus(enabled = true) {
  return useQuery({
    queryKey: paymentKeys.status,
    queryFn: () => apiRequest<PaymentStatus>(adminSession(), `${BASE}/status`),
    enabled,
  });
}

/**
 * How many rows each list asks for. Neither route pages, so a list that comes back this
 * long is the newest slice, not everything, and the screen says so.
 */
export const RECENT_PAYMENTS_LIMIT = 50;
export const DISPUTES_LIMIT = 200;

export function useRecentPayments(enabled: boolean) {
  return useQuery({
    queryKey: paymentKeys.recent,
    queryFn: () =>
      apiRequest<RecentPayment[]>(adminSession(), `${BASE}/recent?limit=${RECENT_PAYMENTS_LIMIT}`),
    enabled,
  });
}

export function useDisputes(includeClosed: boolean, enabled = true) {
  return useQuery({
    queryKey: paymentKeys.disputes(includeClosed),
    queryFn: () =>
      apiRequest<Dispute[]>(
        adminSession(),
        `${BASE}/disputes?limit=${DISPUTES_LIMIT}&include_closed=${includeClosed ? "true" : "false"}`,
      ),
    enabled,
  });
}

export function useRunReconciliation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      confirmedAdminRequest<ReconcileReport>(
        `${BASE}/reconcile`,
        { method: "POST", confirmAction: RECONCILE_PAYMENTS_CONFIRMATION },
        "Running the payment reconciliation.",
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: paymentKeys.status }),
  });
}

export function disputeConfirmation(disputeId: string, act: "accept" | "contest"): string {
  return `dispute_${act}:${disputeId}`;
}

export function useAcceptDispute() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (disputeId: string) =>
      confirmedAdminRequest<Schemas["DisputeActionOut"]>(
        `${BASE}/disputes/${encodeURIComponent(disputeId)}/accept`,
        { method: "POST", confirmAction: disputeConfirmation(disputeId, "accept") },
        "Accepting this dispute and refunding the customer.",
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin-payments", "disputes"] }),
  });
}

export interface ContestDraft {
  disputeId: string;
  summary: string;
  evidenceKind: string;
  files: File[];
  /** Blank = the whole disputed amount; otherwise DIGITS, never parsed here. */
  amountInr: string;
}

export function useContestDispute() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: ContestDraft) => {
      const form = new FormData();
      form.append("summary", draft.summary.trim());
      form.append("evidence_kind", draft.evidenceKind);
      if (draft.amountInr.trim()) form.append("amount_inr", draft.amountInr.trim());
      for (const file of draft.files) form.append("files", file);
      // The upload is retried with the same body after a code: the gate refuses before
      // it acts on the files, so the first attempt sent nothing to the bank.
      const confirmAction = disputeConfirmation(draft.disputeId, "contest");
      return withActionCode(
        confirmAction,
        "Sending this dispute's evidence to the bank.",
        () =>
          apiUpload<Schemas["DisputeActionOut"]>(
            adminSession(),
            `${BASE}/disputes/${encodeURIComponent(draft.disputeId)}/contest`,
            form,
            { confirmAction },
          ),
        needsReauthentication,
      );
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin-payments", "disputes"] }),
  });
}

export const EVIDENCE_KINDS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "billing_proof", label: "Receipt or bill" },
  { value: "proof_of_service", label: "Proof of service (call records)" },
  { value: "explanation_letter", label: "Explanation letter" },
  { value: "access_activity_log", label: "Account activity log" },
  { value: "refund_cancellation_policy", label: "Refund policy shown to the client" },
  { value: "term_and_conditions", label: "Terms shown to the client" },
  { value: "customer_communication", label: "Messages from the client" },
];
