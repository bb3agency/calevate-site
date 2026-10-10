"use client";

/**
 * The monthly platform fee (D-707): the client's card and Pay, and the operator's panel.
 *
 * One pricing model for every client: prepaid credits, plus an optional platform-wide
 * monthly fee the operator switches on in the ops console. The fee is a SEPARATE payment —
 * it never comes out of calling credit — and while it is unpaid past its grace period the
 * client's OUTBOUND calls pause. Incoming calls are never affected.
 *
 * Every figure and every status is the server's (`billing/platform_fee.py`): the screen
 * never decides whether a fee is due, overdue or waived, it prints the word it was sent.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

export type PlatformFee = Schemas["PlatformFeeOut"];
export type PlatformFeeCharge = Schemas["FeeChargeOut"];
export type FeeOrder = Schemas["FeeOrderOut"];
export type AdminPlatformFee = Schemas["AdminPlatformFeeOut"];
export type FeePayment = Schemas["FeePaymentOut"];
export type FeeStatus = PlatformFeeCharge["status"];

export const PLATFORM_FEE_PATH = "/v1/billing/platform-fee";

export function platformFeeKey(slug: string): readonly unknown[] {
  return ["platform-fee", slug];
}

export function adminPlatformFeePath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/platform-fee`;
}

export interface FeeStatusCopy {
  label: string;
  tone: "ok" | "warn" | "stop" | "neutral";
}

export const FEE_STATUS_COPY: Record<FeeStatus, FeeStatusCopy> = {
  paid: { label: "Paid", tone: "ok" },
  due: { label: "Due", tone: "warn" },
  overdue: { label: "Overdue — outgoing calls paused", tone: "stop" },
  waived: { label: "Not charged", tone: "neutral" },
};

/** Fails to a neutral word rather than to "Paid": an unknown status must not read as settled. */
export function feeStatusCopy(status: string): FeeStatusCopy {
  return lookup(FEE_STATUS_COPY, status) ?? { label: status, tone: "neutral" };
}

/** The fee a client still owes, oldest first — the one pausing their calls, if any. */
export function oldestUnpaid(fee: PlatformFee): PlatformFeeCharge | null {
  const open = fee.charges.filter((charge) => charge.status === "due" || charge.status === "overdue");
  return open.length ? open[open.length - 1] : null;
}

/** "October 2026" from "2026-10". */
export function feeMonth(period: string): string {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return period;
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function usePlatformFee(session: Session): UseQueryResult<PlatformFee> {
  return useQuery({
    queryKey: platformFeeKey(session.orgSlug),
    queryFn: () => apiRequest<PlatformFee>(session, PLATFORM_FEE_PATH),
  });
}

export function useFeeOrder(session: Session) {
  return useMutation({
    mutationFn: (chargeId: string) =>
      apiRequest<FeeOrder>(session, `${PLATFORM_FEE_PATH}/${chargeId}/order`, {
        method: "POST",
      }),
  });
}

export function useAdminPlatformFee(
  session: Session,
  tenantId: string,
): UseQueryResult<AdminPlatformFee> {
  return useQuery({
    queryKey: ["admin", "platform-fee", tenantId],
    queryFn: () => apiRequest<AdminPlatformFee>(session, adminPlatformFeePath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

export function useSetFeeWaiver(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (reason: string | null) =>
      reason === null
        ? apiRequest<AdminPlatformFee>(session, `${adminPlatformFeePath(tenantId)}/waiver`, {
            method: "DELETE",
          })
        : apiRequest<AdminPlatformFee>(session, `${adminPlatformFeePath(tenantId)}/waiver`, {
            method: "PUT",
            body: { reason },
          }),
    onSuccess: (data) => client.setQueryData(["admin", "platform-fee", tenantId], data),
  });
}

export function useRecordFeePayment(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ chargeId, reference }: { chargeId: string; reference: string }) =>
      apiRequest<FeePayment>(session, `${adminPlatformFeePath(tenantId)}/${chargeId}/payments`, {
        method: "POST",
        body: { reference },
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ["admin", "platform-fee", tenantId] }),
  });
}
