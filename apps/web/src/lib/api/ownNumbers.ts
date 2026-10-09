"use client";

/**
 * Phone numbers rented in the client's OWN calling account, in the business's own name
 * (D-693).
 *
 * The journey is three steps, and the server decides which one the account is on
 * (`status.step`): verify the business, have the business details approved for phone
 * numbers, then buy. Nothing here re-derives that order — a screen that recomputed it would
 * disagree with the purchase gate on exactly the day it matters.
 *
 * Client-facing words name no vendor, plan or vendor price: `inr_per_month` is OUR price.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type OwnNumbersStatus = Schemas["OwnNumbersStatusOut"];
export type OwnNumberCity = Schemas["CityOut"];
export type OwnAvailableNumber = Schemas["AvailableOwnNumberOut"];
export type OwnAvailableNumbers = Schemas["AvailableOwnNumbersOut"];
export type PurchaseOwnNumberIn = Schemas["PurchaseOwnNumberIn"];
export type PurchasedOwnNumber = Schemas["PurchasedOwnNumberOut"];
export type ReleasedOwnNumber = Schemas["ReleasedOwnNumberOut"];
export type BusinessDetailsSent = Schemas["BusinessDetailsSentOut"];
export type FirstPeriod = PurchasedOwnNumber["first_period"];
export type OwnNumberDirection = PurchaseOwnNumberIn["direction"];

const BASE = "/v1/numbers/own";

/** The number search takes up to ten digits and nothing else (`^\d{1,10}$` on the server,
 * client and admin alike), so the field keeps only those and no search is refused for it. */
export const SEARCH_DIGITS_MAX = 10;

export function searchDigits(value: string): string {
  return value.replace(/\D/g, "").slice(0, SEARCH_DIGITS_MAX);
}

export const OWN_NUMBERS_PATHS = {
  status: `${BASE}/status`,
  businessDetails: `${BASE}/business-details`,
  cities: `${BASE}/cities`,
  purchase: `${BASE}/purchase`,
  release: (numberId: string) => `${BASE}/${numberId}/release`,
  available: (city: string, pattern: string, cursor: string | null) => {
    const query = new URLSearchParams({ city });
    if (pattern) query.set("pattern", pattern);
    if (cursor) query.set("cursor", cursor);
    return `${BASE}/available?${query.toString()}`;
  },
} as const;

export const ownNumberKeys = {
  status: (org: string) => ["own-numbers", org, "status"] as const,
  cities: (org: string) => ["own-numbers", org, "cities"] as const,
  available: (org: string, city: string, pattern: string) =>
    ["own-numbers", org, "available", city, pattern] as const,
};

export function useOwnNumbersStatus(session: Session): UseQueryResult<OwnNumbersStatus> {
  return useQuery({
    queryKey: ownNumberKeys.status(session.orgSlug),
    queryFn: () => apiRequest<OwnNumbersStatus>(session, OWN_NUMBERS_PATHS.status),
  });
}

export function useSendOwnBusinessDetails(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<BusinessDetailsSent>(session, OWN_NUMBERS_PATHS.businessDetails, {
        method: "POST",
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: ownNumberKeys.status(session.orgSlug) }),
  });
}

export function useOwnNumberCities(session: Session, enabled: boolean): UseQueryResult<OwnNumberCity[]> {
  return useQuery({
    queryKey: ownNumberKeys.cities(session.orgSlug),
    queryFn: () => apiRequest<OwnNumberCity[]>(session, OWN_NUMBERS_PATHS.cities),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** Numbers on offer in one city, a page at a time; the next page is asked for by cursor. */
export function useOwnAvailableNumbers(
  session: Session,
  search: { city: string; pattern: string } | null,
) {
  return useInfiniteQuery({
    queryKey: ownNumberKeys.available(session.orgSlug, search?.city ?? "", search?.pattern ?? ""),
    queryFn: ({ pageParam }) =>
      apiRequest<OwnAvailableNumbers>(
        session,
        OWN_NUMBERS_PATHS.available(search?.city ?? "", search?.pattern ?? "", pageParam),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: OwnAvailableNumbers) => last.next_cursor,
    enabled: search !== null,
    // A search is a round trip to a rate-limited inventory; the list is a minute's truth.
    staleTime: 60_000,
    retry: false,
  });
}

/**
 * A request key for one press of Buy: 8-100 characters of `[A-Za-z0-9_-]`.
 *
 * The caller mints it when the confirmation opens and REUSES it on every retry of that
 * purchase, so a double press or a "press Buy again" after an unconfirmed purchase finishes
 * the same request instead of renting a second number.
 */
export function newRequestKey(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID().replace(/-/g, "");
  return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

/** **Spends money on a recurring commitment.** `retry: false`: a framework retry with a
 *  fresh body is the caller's key decision, never the library's. */
export function usePurchaseOwnNumber(session: Session) {
  const client = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: (body: PurchaseOwnNumberIn) =>
      apiRequest<PurchasedOwnNumber>(session, OWN_NUMBERS_PATHS.purchase, {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["own-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["wallet", session.orgSlug] });
    },
  });
}

export function useReleaseOwnNumber(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (numberId: string) =>
      apiRequest<ReleasedOwnNumber>(session, OWN_NUMBERS_PATHS.release(numberId), {
        method: "POST",
        body: { confirm: true },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["own-numbers", session.orgSlug] });
      void client.invalidateQueries({ queryKey: ["campaign-numbers", session.orgSlug] });
    },
  });
}
