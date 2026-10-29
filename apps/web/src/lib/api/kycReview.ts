"use client";

/**
 * The operator's side of KYC (D-692): the review queue, one client's record and files,
 * approve/reject, and the "require DigiLocker" override. All admin-realm, `admin:tenants`,
 * and every write audited server-side.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import {
  adminSession,
  clearDigiLockerConfirmation,
  confirmedAdminRequest,
  kycReviewConfirmation,
} from "./admin";
import { apiRequest } from "./client";
import { openProtectedFile } from "./protectedFile";
import { CLIENT_HEALTH_QUERY_KEY } from "./clientHealth";
import { HOLDS_QUERY_KEY } from "./holds";
import { livePoll } from "@/lib/live/liveStatus";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KycReviewItem = Schemas["KycReviewItem"];
export type AdminKyc = Schemas["AdminKycOut"];
export type KycReviewIn = Schemas["KycReviewIn"];

export const KYC_REVIEWS_PATH = "/v1/admin/kyc/reviews";

const QUEUE_KEY = ["admin", "kyc-reviews"] as const;

/**
 * Clients whose identity check waits for a reviewer. Polled like the hold queue, because the
 * header's bell counts it too. `enabled` is false for an operator without `admin:tenants`,
 * whose request could only be refused.
 */
export function useKycReviewQueue(options: { enabled?: boolean } = {}): UseQueryResult<KycReviewItem[]> {
  return useQuery({
    queryKey: QUEUE_KEY,
    queryFn: () => apiRequest<KycReviewItem[]>(adminSession(), KYC_REVIEWS_PATH),
    enabled: options.enabled ?? true,
    refetchInterval: livePoll(60_000),
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
      // An unverified identity is one of `outbound_blocked`'s causes on the health board.
      client.invalidateQueries({ queryKey: CLIENT_HEALTH_QUERY_KEY }),
      // The overview's readiness rows and account facts read the same record.
      client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] }),
    ]);
  };
}

/** Approve or reject. Step-up: the decision deletes the owner's ID file and, on approval,
 * opens outbound calling, so it is confirmed like recording KYC by hand. */
export function useReviewKyc(tenantId: string) {
  const refresh = useRefresh(tenantId);
  return useMutation({
    mutationFn: (body: KycReviewIn) =>
      confirmedAdminRequest<AdminKyc>(
        `/v1/admin/tenants/${tenantId}/kyc/review`,
        { method: "POST", body, confirmAction: kycReviewConfirmation(tenantId, body.decision) },
        body.decision === "approve" ? "Approving this verification." : "Rejecting this verification.",
      ),
    onSuccess: refresh,
  });
}

/** Requiring DigiLocker only blocks, so it is a plain write; clearing lifts an outbound
 * block and is confirmed with a code. */
export function useSetDigiLockerRequirement(tenantId: string) {
  const refresh = useRefresh(tenantId);
  return useMutation({
    mutationFn: (body: { required: boolean; reason: string | null }) => {
      const path = `/v1/admin/tenants/${tenantId}/kyc/digilocker-requirement`;
      return body.required
        ? apiRequest<AdminKyc>(adminSession(), path, { method: "POST", body })
        : confirmedAdminRequest<AdminKyc>(
            path,
            { method: "POST", body, confirmAction: clearDigiLockerConfirmation(tenantId) },
            "Lifting the DigiLocker requirement.",
          );
    },
    onSuccess: refresh,
  });
}

/** The browser refused to open a tab for the document, so nothing was shown. */
export { ViewerBlockedError as KycViewerBlockedError } from "./protectedFile";

/**
 * Open one KYC file for review. The server decrypts it and audits the view; the bytes are
 * shown from memory and never cached or saved to disk.
 */
export function openKycDocument(tenantId: string, documentId: string): Promise<void> {
  return openProtectedFile(adminSession(), `/v1/admin/tenants/${tenantId}/kyc/documents/${documentId}`);
}
