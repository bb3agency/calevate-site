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

export function useTenant(tenantId: string): UseQueryResult<TenantSummary> {
  return useQuery({
    queryKey: ["admin", "tenant", tenantId],
    queryFn: () => apiRequest<TenantSummary>(adminSession(), `/v1/admin/tenants/${tenantId}`),
    enabled: Boolean(tenantId),
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

/**
 * Campaign prerequisites — the two things every client campaign stalls on until an
 * operator does them (SEC-COMP §3). Read through impersonation, written through the
 * admin surface: same D-22 split as the KB queue, for the same reason.
 */
export function useTenantNumbers(slug: string) {
  return useQuery({
    queryKey: ["admin", "numbers", slug],
    queryFn: () =>
      apiRequest<components["schemas"]["NumberOut"][]>(
        viewAsSession(slug),
        "/v1/campaigns/numbers",
      ),
    enabled: Boolean(slug),
  });
}

export function useTenantTemplates(slug: string) {
  return useQuery({
    queryKey: ["admin", "templates", slug],
    queryFn: () =>
      apiRequest<components["schemas"]["TemplateOut"][]>(
        viewAsSession(slug),
        "/v1/campaigns/templates",
      ),
    enabled: Boolean(slug),
  });
}

export function useProvisionNumber(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { e164: string; series: "140" | "160" | "standard" }) =>
      apiRequest<components["schemas"]["NumberCreatedOut"]>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/numbers`,
        { method: "POST", body: payload },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "numbers"] }),
  });
}

export function useSetNumberDltStatus(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      numberId,
      dltStatus,
    }: {
      numberId: string;
      dltStatus: "pending" | "registered" | "blocked";
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/numbers/${numberId}/dlt-status`,
        { method: "POST", body: { dlt_status: dltStatus } },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "numbers"] }),
  });
}

export function useRegisterTemplate(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      classification: "promotional" | "transactional" | "service";
      body: string;
      dlt_ref?: string | null;
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/dlt-templates`,
        { method: "POST", body: payload },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "templates"] }),
  });
}

export function useSetTemplateStatus(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      templateId,
      status,
      dltRef,
    }: {
      templateId: string;
      status: "approved" | "rejected" | "submitted";
      dltRef?: string;
    }) =>
      apiRequest<Record<string, string>>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/dlt-templates/${templateId}/status`,
        { method: "POST", body: { status, ...(dltRef ? { dlt_ref: dltRef } : {}) } },
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["admin", "templates"] }),
  });
}

/**
 * Per-client margin (D-12). Admin realm only — `unit_cost_paid` is our supplier
 * pricing, and the client-facing usage panel deliberately does not carry it.
 */
export interface Margin {
  month: string;
  minutes_used: string;
  calls: number;
  revenue_inr: string;
  cost_inr: string;
  margin_inr: string;
  margin_pct: string | null;
}

export function useMargin(tenantId: string): UseQueryResult<Margin> {
  return useQuery({
    queryKey: ["admin", "margin", tenantId],
    queryFn: () => apiRequest<Margin>(adminSession(), `/v1/admin/tenants/${tenantId}/margin`),
    enabled: Boolean(tenantId),
  });
}
