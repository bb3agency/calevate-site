"use client";

/**
 * Admin-realm client and hooks — a SEPARATE session from the client realm.
 *
 * TRD §11 and D-37: two Clerk applications, two session cookies, no shared session
 * logic. That separation is why this file exists at all rather than a `realm` flag on
 * the client-realm session: a flag is one bad conditional away from an admin token
 * being used on a client surface, and vice versa.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type TenantSummary = Schemas["TenantSummary"];
export type CreateOrgIn = Schemas["CreateOrgIn"];
export type CreateOrgOut = Schemas["CreateOrgOut"];
export type InviteOut = Schemas["InviteOut"];
export type PlatformState = Schemas["PlatformStateOut"];
export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];

/**
 * Local development only, and only where Clerk is absent — the API enforces both
 * conditions (`core/auth.py`). The admin realm carries `dev:admin:` so a client token
 * can never be pasted into an admin surface by accident.
 */
export function adminSession(orgSlug = ""): Session {
  const user = process.env.NEXT_PUBLIC_DEV_ADMIN ?? "admin_local";
  return { token: `dev:admin:${user}`, orgSlug };
}

/** Impersonation is READ-ONLY (D-22): this adds the header, it mints no credential. */
export function viewAsSession(slug: string): Session {
  return { ...adminSession(slug), orgSlug: slug, impersonateOrg: slug };
}

export function useTenants(): UseQueryResult<TenantSummary[]> {
  return useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: () => apiRequest<TenantSummary[]>(adminSession(), "/v1/admin/tenants"),
    refetchInterval: 60_000,
  });
}

export function useCreateTenant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateOrgIn) =>
      apiRequest<CreateOrgOut>(adminSession(), "/v1/admin/tenants", {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "tenants"] }),
  });
}

export function useInvite() {
  return useMutation({
    mutationFn: ({ tenantId, email, role }: { tenantId: string; email: string; role: string }) =>
      apiRequest<InviteOut>(adminSession(), `/v1/admin/tenants/${tenantId}/invitations`, {
        method: "POST",
        body: { email, role },
      }),
  });
}

export function usePlatformState(): UseQueryResult<PlatformState> {
  return useQuery({
    queryKey: ["admin", "platform"],
    queryFn: () => apiRequest<PlatformState>(adminSession(), "/v1/ops/platform"),
    refetchInterval: 30_000,
  });
}

export function useSetPlatformState() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      outboundHalted,
      reason,
    }: {
      outboundHalted: boolean;
      reason: string;
    }) => {
      const session = adminSession();
      // Step-up confirmation (BACKEND-PATTERNS §7): the header must echo the action.
      // It is not a second factor and does not pretend to be — it stops the accidental
      // and the drive-by, and Clerk re-auth replaces it when admin MFA lands.
      const action = outboundHalted ? "halt_outbound" : "set_platform_state";
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/v1/ops/platform`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${session.token}`,
            "Content-Type": "application/json",
            "X-Confirm-Action": action,
          },
          body: JSON.stringify({ outbound_halted: outboundHalted, reason }),
        },
      );
      if (!response.ok) throw new Error(await response.text());
      return (await response.json()) as PlatformState;
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "platform"] }),
  });
}

/**
 * The queue is READ through impersonation (allowed, audited) and DECIDED through the
 * admin surface (D-22: no acting-as). Two different sessions is the decision, not an
 * inconsistency — an approve call made with the impersonation session would be
 * correctly refused.
 */
export function useTenantKbQueue(slug: string, status = "pending_approval") {
  return useQuery({
    queryKey: ["admin", "kb", slug, status],
    queryFn: () =>
      apiRequest<KbSource[]>(viewAsSession(slug), `/v1/kb/sources?status=${status}`),
    enabled: Boolean(slug),
  });
}

export function useKbPreview(slug: string, sourceId: string | null) {
  return useQuery({
    queryKey: ["admin", "kb-preview", slug, sourceId],
    queryFn: () =>
      apiRequest<KbChunk[]>(viewAsSession(slug), `/v1/kb/sources/${sourceId}/preview`),
    enabled: Boolean(sourceId),
  });
}

export function useKbDecision(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceId,
      decision,
      reason,
    }: {
      sourceId: string;
      decision: "approve" | "reject" | "publish";
      reason?: string;
    }) =>
      apiRequest<Record<string, unknown>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/kb/${sourceId}/${decision}`,
        {
          method: "POST",
          body: decision === "reject" ? { reason: reason ?? "Not suitable" } : undefined,
        },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "kb"] }),
  });
}
