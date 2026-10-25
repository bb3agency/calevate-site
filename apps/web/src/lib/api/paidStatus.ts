"use client";

/**
 * Whether a client account is paid, and the super admin's act that makes it so with no
 * payment behind it (D-890).
 *
 * `GET|POST /v1/admin/tenants/{tenant_id}/paid` (`apps/api/billing/comp_routes.py`). The
 * read is `billing:read`; the write is `billing:comp`, a super admin's permission. Making
 * an account paid unlocks exactly what a first top-up unlocks — any running trial is
 * converted, its scheduled erasure is cleared and its customer workspace is queued — and
 * is recorded as `complimentary` with the super admin's reason, so it is never confused
 * with money that arrived.
 *
 * Credit may be given in the same step. It is posted as an ordinary grant, under the
 * same step-up, which is why the confirmation string carries the amount.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { needsReauthentication } from "@/lib/authn/problems";
import { withActionCode } from "@/lib/authn/stepUpPrompt";

import { apiRequest, type Session } from "./client";
import { creditsKey, toTwoDecimals } from "./credits";
import { trialKey } from "./trials";

import type { components } from "./schema";

type Schemas = components["schemas"];

export type PaidStatus = Schemas["PaidStatusOut"];
export type MakePaidIn = Schemas["MakePaidIn"];
export type MakePaidResult = Schemas["MakePaidOut"];

export function paidPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/paid`;
}

export function paidKey(tenantId: string): readonly unknown[] {
  return ["admin", "paid", tenantId];
}

/**
 * The step-up string, copied from `comp_routes.make_paid_confirmation`: bound to the
 * client and to the credit given with it (`0.00` when none), so a confirmation for one
 * account or one amount cannot be replayed for another.
 */
export function makePaidConfirmation(tenantId: string, grantInr: string | null): string {
  return `convert_to_paid:${tenantId}:${grantInr === null ? "0.00" : toTwoDecimals(grantInr)}`;
}

export function usePaidStatus(session: Session, tenantId: string) {
  return useQuery({
    queryKey: paidKey(tenantId),
    queryFn: () => apiRequest<PaidStatus>(session, paidPath(tenantId)),
  });
}

export interface MakePaidDraft {
  reason: string;
  /** Credit given in the same step, or `null` for none. */
  grant: { amountInr: string; amountConfirmation: string; grantRef: string } | null;
}

export function useMakePaid(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ reason, grant }: MakePaidDraft) => {
      const body: MakePaidIn = {
        reason: reason.trim(),
        grant:
          grant === null
            ? null
            : {
                // Strings, always (hard rule 7).
                amount_inr: grant.amountInr.trim(),
                amount_confirmation: grant.amountConfirmation.trim(),
                grant_ref: grant.grantRef,
                reason: reason.trim(),
              },
      };
      const confirmAction = makePaidConfirmation(tenantId, grant?.amountInr.trim() ?? null);
      return withActionCode(
        confirmAction,
        "Making this client account paid.",
        () =>
          apiRequest<MakePaidResult>(session, paidPath(tenantId), {
            method: "POST",
            body,
            confirmAction,
          }),
        needsReauthentication,
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: paidKey(tenantId) });
      void client.invalidateQueries({ queryKey: trialKey(tenantId) });
      void client.invalidateQueries({ queryKey: creditsKey(tenantId) });
    },
  });
}
