"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

/**
 * THE BUSINESS TYPES, as every picker names them, read from the server
 * (`GET /v1/public/business-types`, built from `calevate_shared/verticals.json`). The web
 * keeps no copy: adding a type is an edit to that file, and every picker, label and example
 * follows. The order is the server's, and it does not start with a clinic because no trade
 * is anybody's default.
 *
 * `hint` says what choosing the type DOES: it picks the details every lead of that
 * business captures on top of the ones every business gets.
 */
export type BusinessTypes = components["schemas"]["BusinessTypesOut"];
export type BusinessTypeOption = components["schemas"]["BusinessTypeOptionOut"];
/** A type's key: any value the server's list holds. */
export type BusinessType = BusinessTypeOption["value"];

export const BUSINESS_TYPES_PATH = "/v1/public/business-types";
export const BUSINESS_TYPES_QUERY_KEY = ["public", "business-types"] as const;

/** The route reads nothing about its caller, so it is asked as nobody. */
const NOBODY: Session = { orgSlug: "" };

export function useBusinessTypes(): UseQueryResult<BusinessTypes> {
  return useQuery({
    queryKey: BUSINESS_TYPES_QUERY_KEY,
    queryFn: () => apiRequest<BusinessTypes>(NOBODY, BUSINESS_TYPES_PATH),
    // The list changes only with a deploy; the server caches it for five minutes too.
    staleTime: 5 * 60_000,
  });
}

/** The option for a stored type; an absent or unknown one is the list's `custom`. */
export function businessTypeOption(
  types: BusinessTypes | undefined,
  value: string | null | undefined,
): BusinessTypeOption | undefined {
  if (!types) return undefined;
  return (
    types.choices.find((option) => option.value === value) ??
    types.choices.find((option) => option.value === types.custom)
  );
}

/** How a stored type reads, or "" while the list is loading. */
export function businessTypeLabel(
  types: BusinessTypes | undefined,
  value: string | null | undefined,
): string {
  return businessTypeOption(types, value)?.label ?? "";
}

/** `businessTypeLabel` bound to the loaded list, for screens that name several types. */
export function useBusinessTypeLabel(): (value: string | null | undefined) => string {
  const types = useBusinessTypes().data;
  return (value) => businessTypeLabel(types, value);
}
