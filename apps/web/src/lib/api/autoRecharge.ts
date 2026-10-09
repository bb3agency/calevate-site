"use client";

/**
 * Auto-recharge (D-699): the client's threshold, recharge amount and monthly limit, and
 * the UPI Autopay or card approval behind them. The rules live in
 * `apps/api/billing/auto_recharge.py`; this module only carries them.
 *
 * Money is a decimal STRING end to end (hard rule 7): nothing here parses a rupee figure.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type AutoRecharge = Schemas["AutoRechargeOut"];
export type AutoRechargeIn = Schemas["AutoRechargeIn"];
export type MandateCheckout = Schemas["MandateCheckoutOut"];
export type MandateMethod = Schemas["MandateIn"]["method"];
export type RechargeCharge = Schemas["ChargeOut"];

export const AUTO_RECHARGE_PATH = "/v1/billing/auto-recharge";

export function autoRechargeKey(orgSlug: string) {
  return ["billing-auto-recharge", orgSlug] as const;
}

export function useAutoRecharge(session: Session) {
  return useQuery({
    queryKey: autoRechargeKey(session.orgSlug),
    queryFn: () => apiRequest<AutoRecharge>(session, AUTO_RECHARGE_PATH),
  });
}

export function useRechargeCharges(session: Session) {
  return useQuery({
    queryKey: [...autoRechargeKey(session.orgSlug), "charges"],
    queryFn: () =>
      apiRequest<RechargeCharge[]>(session, `${AUTO_RECHARGE_PATH}/charges?limit=20`),
  });
}

export function useSaveAutoRecharge(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AutoRechargeIn) =>
      apiRequest<AutoRecharge>(session, AUTO_RECHARGE_PATH, { method: "PUT", body }),
    onSuccess: (data) => client.setQueryData(autoRechargeKey(session.orgSlug), data),
  });
}

export function useStartMandate(session: Session) {
  return useMutation({
    mutationFn: (body: { method: MandateMethod; max_debit_inr: string }) =>
      apiRequest<MandateCheckout>(session, `${AUTO_RECHARGE_PATH}/mandate`, {
        method: "POST",
        body,
      }),
  });
}

export function useConfirmMandate(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    }) =>
      apiRequest<AutoRecharge>(session, `${AUTO_RECHARGE_PATH}/mandate/confirm`, {
        method: "POST",
        body,
      }),
    onSuccess: (data) => client.setQueryData(autoRechargeKey(session.orgSlug), data),
  });
}

export function useWithdrawMandate(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<AutoRecharge>(session, `${AUTO_RECHARGE_PATH}/mandate`, { method: "DELETE" }),
    onSuccess: (data) => client.setQueryData(autoRechargeKey(session.orgSlug), data),
  });
}

/** What the client reads for each mandate state, in their words. */
export const MANDATE_STATUS_TEXT: Readonly<Record<string, string>> = {
  none: "No automatic payment method yet.",
  pending: "Waiting for your bank or UPI app to confirm the approval.",
  confirmed: "Approved for automatic top-ups.",
  rejected: "Your bank or UPI app did not approve it. Try again or use another method.",
  cancelled: "The approval was withdrawn. Set it up again to use auto-recharge.",
  paused: "Paused in your UPI app. Resume it there to use auto-recharge again.",
};
