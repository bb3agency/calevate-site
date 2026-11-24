"use client";

/**
 * Tenant erasure — the admin console's half of FLOWS §9's last step (D-122).
 *
 * The API surface is `/v1/admin/tenants/{id}/erasure` and it is the only thing in the
 * product that writes `organizations.deleted_at`. Read
 * `apps/api/compliance/tenant_erasure.py` before changing anything here: it argues the
 * state model (three states, no fourth), why this is not a `deletion_requests` row, and
 * why the write needs a superadmin AND a confirmation header.
 *
 * TWO THINGS THIS MODULE KEEPS RATHER THAN SMOOTHS OVER
 *
 * - **The confirmation string is the SERVER'S, echoed.** `X-Confirm-Action` must equal
 *   `erase_tenant_data:<tenant_id>` exactly. It is built here from the same rule the API
 *   applies, and it is not a client-side dialog: a confirm() that only exists in the
 *   browser is absent from curl, and the point of the header is that a request cannot be
 *   sent by a screen that did not mean to send it.
 * - **No optimistic anything.** The mutation invalidates the tenant read and the
 *   directory, because after it completes the client is gone from both — a stale row
 *   showing an erased client as live is the console telling an operator the erasure did
 *   not take.
 *
 * Types come from `schema.d.ts` (`pnpm -C apps/web gen:api`), never hand-mirrored.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { confirmedRequest } from "./admin";
import { apiRequest, type Session } from "./client";
import { untilRefused } from "./queryRetry";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One filed erasure and, once the worker has run, its certificate. */
export type TenantErasure = Schemas["TenantErasureOut"];
export type TenantErasureAccepted = Schemas["TenantErasureAcceptedOut"];

const erasurePath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/erasure`;

/**
 * The `X-Confirm-Action` value this tenant's erasure demands.
 *
 * Bound to the tenant id so a confirmation captured for one client cannot be replayed
 * against the next one in the list — `tenant_erasure.tenant_erasure_confirmation` is the
 * authority, and the API refuses anything else with `step_up_required` naming the exact
 * header, so a drift here is a visible 403 rather than a silent bypass.
 */
export function erasureConfirmation(tenantId: string): string {
  return `erase_tenant_data:${tenantId}`;
}

export function useTenantErasures(
  session: Session,
  tenantId: string,
): UseQueryResult<TenantErasure[]> {
  const client = useQueryClient();
  const read = useQuery<TenantErasure[]>({
    queryKey: ["admin", "tenant-erasure", tenantId],
    queryFn: () => apiRequest<TenantErasure[]>(session, erasurePath(tenantId)),
    // An erasure runs in the background; read again until none is pending.
    refetchInterval: untilRefused((query) =>
      query.state.data?.some((erasure) => erasure.status === "pending") ? ERASURE_POLL_MS : false),
  });
  // The worker, not the POST, sets `deleted_at` and `erased_at`. When the poll sees the
  // erasure finish, the closure, the client and the directory are read again; otherwise the
  // Closing screen keeps offering "Reopen the account" for a client whose records are gone.
  const pending = read.data?.some((erasure) => erasure.status === "pending");
  const wasPending = useRef(false);
  useEffect(() => {
    if (pending === undefined) return;
    if (wasPending.current && !pending) invalidateErasedClient(client, tenantId);
    wasPending.current = pending;
  }, [pending, client, tenantId]);
  return read;
}

function invalidateErasedClient(client: QueryClient, tenantId: string): void {
  void client.invalidateQueries({ queryKey: ["admin", "closure", tenantId] });
  void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
  void client.invalidateQueries({ queryKey: ["admin", "tenants"] });
}

const ERASURE_POLL_MS = 10_000;

export function useEraseTenant(session: Session, tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ reason }: { reason: string }) =>
      confirmedRequest<TenantErasureAccepted>(
        session,
        erasurePath(tenantId),
        { method: "POST", body: { reason }, confirmAction: erasureConfirmation(tenantId) },
        "Erasing this client's records.",
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "tenant-erasure", tenantId] });
      // The client leaves the directory and the detail screen the moment this completes.
      void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
      void client.invalidateQueries({ queryKey: ["admin", "tenants"] });
    },
  });
}
