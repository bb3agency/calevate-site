"use client";

/**
 * Calevate's filing of the calling numbers clients authorise us to register (D-941,
 * amended 30 Oct 2026). The board is `org:read`; marking filed is `admin:tenants` and
 * audited server-side. The client's calls never wait for this; the client-health board
 * raises `calling_numbers_unfiled` when we are late.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import { CLIENT_HEALTH_QUERY_KEY } from "./clientHealth";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type FilingBoard = Schemas["FilingBoardOut"];
export type ClientFiling = Schemas["ClientFilingOut"];
export type MarkFiledIn = Schemas["MarkFiledIn"];

export const FILING_BOARD_PATH = "/v1/admin/calling-number-filings";
export const FILING_BOARD_KEY = ["admin", "calling-number-filings"] as const;

export function markFiledPath(tenantId: string): string {
  return `/v1/admin/tenants/${tenantId}/calling-number-filings`;
}

export function useFilingBoard(): UseQueryResult<FilingBoard> {
  return useQuery({
    queryKey: FILING_BOARD_KEY,
    queryFn: () => apiRequest<FilingBoard>(adminSession(), FILING_BOARD_PATH),
  });
}

export function useMarkFiled(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: MarkFiledIn) =>
      apiRequest<ClientFiling>(adminSession(), markFiledPath(tenantId), { method: "POST", body }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: FILING_BOARD_KEY });
      void client.invalidateQueries({ queryKey: CLIENT_HEALTH_QUERY_KEY });
    },
  });
}
