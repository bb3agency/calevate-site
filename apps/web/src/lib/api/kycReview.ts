"use client";

/**
 * The operator's side of KYC (D-692): the review queue, one client's record and files,
 * approve/reject, and the "require DigiLocker" override. All admin-realm, `admin:tenants`,
 * and every write audited server-side.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import { HOLDS_QUERY_KEY } from "./holds";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KycReviewItem = Schemas["KycReviewItem"];
export type AdminKyc = Schemas["AdminKycOut"];
export type KycReviewIn = Schemas["KycReviewIn"];

const QUEUE_KEY = ["admin", "kyc-reviews"] as const;

export function useKycReviewQueue(): UseQueryResult<KycReviewItem[]> {
  return useQuery({
    queryKey: QUEUE_KEY,
    queryFn: () => apiRequest<KycReviewItem[]>(adminSession(), "/v1/admin/kyc/reviews"),
  });
}

export function useAdminTenantKyc(tenantId: string): UseQueryResult<AdminKyc> {
  return useQuery({
    queryKey: ["admin", "tenant-kyc", tenantId],
    queryFn: () => apiRequest<AdminKyc>(adminSession(), `/v1/admin/tenants/${tenantId}/kyc`),
    enabled: Boolean(tenantId),
  });
}

function useRefresh(tenantId: string) {
  const client = useQueryClient();
  return (fresh: AdminKyc) => {
    client.setQueryData(["admin", "tenant-kyc", tenantId], fresh);
    void Promise.all([
      client.invalidateQueries({ queryKey: QUEUE_KEY }),
      client.invalidateQueries({ queryKey: ["admin", "kyc"] }),
      client.invalidateQueries({ queryKey: HOLDS_QUERY_KEY }),
    ]);
  };
}

export function useReviewKyc(tenantId: string) {
  const refresh = useRefresh(tenantId);
  return useMutation({
    mutationFn: (body: KycReviewIn) =>
      apiRequest<AdminKyc>(adminSession(), `/v1/admin/tenants/${tenantId}/kyc/review`, {
        method: "POST",
        body,
      }),
    onSuccess: refresh,
  });
}

export function useSetDigiLockerRequirement(tenantId: string) {
  const refresh = useRefresh(tenantId);
  return useMutation({
    mutationFn: (body: { required: boolean; reason: string | null }) =>
      apiRequest<AdminKyc>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/kyc/digilocker-requirement`,
        { method: "POST", body },
      ),
    onSuccess: refresh,
  });
}

/**
 * Open one KYC file for review. The server decrypts it and audits the view; the bytes are
 * shown from memory and never cached.
 */
export async function openKycDocument(tenantId: string, documentId: string): Promise<void> {
  const blob = await apiRequest<Blob>(
    adminSession(),
    `/v1/admin/tenants/${tenantId}/kyc/documents/${documentId}`,
    { responseType: "blob" },
  );
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
