"use client";

/**
 * Per-tenant feature flags — types, paths and the hooks the admin screen uses.
 *
 * Types are aliased from the GENERATED `schema.d.ts`, like every other module here.
 *
 * The fields worth knowing before reading the screen: `declared` is false for a stored
 * row whose flag this build no longer declares (shown rather than hidden, because a
 * hidden leftover is how a retired flag becomes permanent); `consumed_by` names the
 * module that actually READS the flag, or null while nothing does, and the screen prints
 * that beside the switch so an operator never flips a control believing it does
 * something; and `override: null` means this tenant has no row at all, which is the
 * normal state — absence IS the platform default, and nothing seeds a row for anyone.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type FeatureFlag = Schemas["FeatureFlagOut"];
export type FeatureFlags = Schemas["FeatureFlagsOut"];
export type FeatureFlagIn = Schemas["FeatureFlagIn"];
export type FeatureFlagChange = Schemas["FeatureFlagChangeOut"];
export type FlagState = Schemas["FlagStateOut"];
/** Derived from the field that carries it, so the vocabulary has one definition. */
export type FlagSource = FlagState["source"];

export const REASON_MAX = 500;
export const REASON_MIN = 3;

export function featureFlagsPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/feature-flags`;
}

export function featureFlagPath(tenantId: string, flag: string): string {
  return `${featureFlagsPath(tenantId)}/${flag}`;
}

export function featureFlagsQueryKey(tenantId: string): [string, string, string] {
  return ["admin", "feature-flags", tenantId];
}

/**
 * What this client is on, and where each answer comes from.
 *
 * `adminSession()` with the tenant in the PATH, not `viewAsSession(slug)`: a flag is our
 * operational decision ABOUT a client rather than a document the client holds, so there
 * is no client-realm endpoint to impersonate into. That also means this screen needs no
 * slug and can render before the tenant read lands.
 *
 * No `refetchInterval`. Flags do not move on their own — the only thing that changes one
 * is a write from this screen or a colleague's, and the mutation invalidates this key.
 * Polling would re-fetch a form the operator is halfway through filling in.
 */
export function useFeatureFlags(tenantId: string): UseQueryResult<FeatureFlags> {
  return useQuery({
    queryKey: featureFlagsQueryKey(tenantId),
    queryFn: () => apiRequest<FeatureFlags>(adminSession(), featureFlagsPath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

/**
 * Set this client's position on one flag, or clear it.
 *
 * `adminSession()` with the tenant in the PATH: `admin:tenants` is in
 * `MUTATING_PERMISSIONS`, so the same call sent through an impersonating session would be
 * correctly refused by `core/auth.py` (D-22).
 *
 * **No `X-Confirm-Action`, because the route asks for none** — the argument is in
 * `apps/api/flags/routes.py` and it is not an oversight: step-up is bound to actions a
 * replayed live session must not be able to perform, and the neighbouring per-tenant
 * compliance writes take none either. No `Idempotency-Key`: the write is an upsert of one
 * row, and sending it twice records the same position and returns `changed: false` the
 * second time.
 *
 * The screen re-reads the list afterwards rather than patching it from this response:
 * `FeatureFlagChange` says what moved, and who set it and when is the SERVER's answer.
 */
export function useSetFeatureFlag(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ flag, ...body }: FeatureFlagIn & { flag: string }) =>
      apiRequest<FeatureFlagChange>(adminSession(), featureFlagPath(tenantId, flag), {
        method: "PUT",
        body,
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: featureFlagsQueryKey(tenantId) }),
  });
}

/**
 * Why this draft cannot be sent yet, or null when it can — the refusal given BEFORE the
 * click rather than as a 422 from the route.
 *
 * Every rule here is enforced again by the route (problem+json naming the field) and
 * again by `ck_tenant_feature_flags_reason_says_why` underneath it. This is the preview
 * of the refusal, never the enforcement.
 */
export function flagBlockReason(draft: FeatureFlagIn, current: FeatureFlag): string | null {
  if (draft.reason.trim().length < REASON_MIN) {
    return "Say why — it goes in the audit entry, and in the row while the override stands.";
  }
  if (draft.reason.length > REASON_MAX) {
    return `Keep the reason under ${REASON_MAX} characters.`;
  }
  if (draft.enabled === null && current.override === null) {
    return "This client has no override to clear — they already follow the platform default.";
  }
  if (draft.enabled !== null && !current.declared) {
    return "This build does not declare this flag, so setting it would change nothing. Clear it instead.";
  }
  if (
    draft.enabled !== null &&
    current.override === draft.enabled &&
    draft.reason.trim() === (current.reason ?? "").trim()
  ) {
    return "That is already what is on file, with the same reason — nothing would change.";
  }
  return null;
}

/**
 * What the effective answer WILL be if this draft is sent — computed from the same three
 * facts the server resolves from, so the preview cannot claim an outcome the API will not
 * produce.
 *
 * `platform_default` is null only for a retired flag, which has no behaviour to fall back
 * to; the caller renders that case as "nothing reads this" rather than as `false`.
 */
export function projectedState(
  draft: FeatureFlagIn,
  current: FeatureFlag,
): { enabled: boolean | null; source: FlagSource } {
  // ABSENT AND NULL BOTH CLEAR THE OVERRIDE, and the generated type is what made the
  // difference visible: `FeatureFlagIn.enabled` is OPTIONAL on the wire, so the server
  // reads an omitted field exactly as it reads an explicit null — follow the platform
  // default. Testing only `=== null` would have sent an omitted field down the
  // tenant-override branch and previewed a state the write does not produce.
  if ((draft.enabled ?? null) === null) {
    return { enabled: current.platform_default, source: "platform_default" };
  }
  return { enabled: draft.enabled as boolean, source: "tenant_override" };
}
