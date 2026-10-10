"use client";

/**
 * `GET /v1/ops/kb-orphans`: the account-level knowledge cross-check, run on demand.
 *
 * A mutation rather than a query because the read walks the voice platform's whole
 * account (the dearest read this product makes) and must run only when an operator asks,
 * never on mount or on a poll.
 */

import { useMutation } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

export const OPS_KB_ORPHANS_PATH = "/v1/ops/kb-orphans";

export type KbOrphanReport = components["schemas"]["KbOrphanReportOut"];
export type KbOrphanRow = components["schemas"]["KbOrphanRowOut"];

export function useKbOrphanCheck() {
  return useMutation({
    mutationFn: () => apiRequest<KbOrphanReport>(adminSession(), OPS_KB_ORPHANS_PATH),
  });
}
