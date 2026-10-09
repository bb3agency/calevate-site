"use client";

/**
 * The operator's list of unfinished onboardings — `GET /v1/admin/onboarding/unfinished`.
 *
 * An account is unfinished while nobody has accepted an invitation, or while its business
 * profile still lacks what an agent needs to go live. The row carries both facts, so the
 * operator can tell "invite the owner" from "chase their setup".
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

export type UnfinishedOnboarding = components["schemas"]["UnfinishedOnboardingOut"];

export const unfinishedOnboardingsKey = ["admin", "onboarding", "unfinished"] as const;
export const UNFINISHED_ONBOARDINGS_PATH = "/v1/admin/onboarding/unfinished";

export function useUnfinishedOnboardings(): UseQueryResult<UnfinishedOnboarding[]> {
  return useQuery({
    queryKey: unfinishedOnboardingsKey,
    queryFn: () =>
      apiRequest<UnfinishedOnboarding[]>(adminSession(), UNFINISHED_ONBOARDINGS_PATH),
  });
}

export type OwnerStatus = components["schemas"]["OwnerStatusOut"];

/** Under the invitations key, so sending or cancelling an invite refreshes it too. */
export const ownerStatusKey = (tenantId: string) =>
  ["admin", "invitations", tenantId, "owner-status"] as const;

/** Has anybody joined this account, and is an invitation still out? */
export function useOwnerStatus(tenantId: string): UseQueryResult<OwnerStatus> {
  return useQuery({
    queryKey: ownerStatusKey(tenantId),
    queryFn: () =>
      apiRequest<OwnerStatus>(
        adminSession(),
        `/v1/admin/tenants/${encodeURIComponent(tenantId)}/owner-status`,
      ),
    enabled: Boolean(tenantId),
  });
}
