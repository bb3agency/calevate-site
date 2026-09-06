"use client";

/**
 * Closing a client business, and taking it back — the console's half of D-538/D-545.
 *
 * `apps/api/admin/closure_routes.py` is the authority and argues the whole shape: why
 * closing is not a flag on the status route, why the close takes a step-up and the UNDO
 * deliberately does not, and why `restorable` is a fact about the DATA (nothing has been
 * erased) rather than about a clock.
 *
 * ## THE ONE WAY TO CLOSE A CLIENT (D-545)
 *
 * There used to be two, and the reachable one was the worse one: the Account state screen
 * offered `churned`, which wrote a status, told the client nothing, set no erasure date
 * and had no undo. `churned` is gone from that screen and from `LifecycleIn`; it remains a
 * legal STORED value, because every closed account has it and a CHECK constraint requires
 * it. This module is now the only door, and `useRestoreAccount` is the only way back.
 *
 * ## What is NOT here
 *
 * The erasure. `lib/api/erasure.ts` files the immediate, superadmin-only destruction and
 * is a different act with a different permission — the sweep behind `erase_after` calls
 * the same function on a timer, which is why there is no second eraser anywhere.
 *
 * Types come from `schema.d.ts` (`pnpm -C apps/web gen:api`), never hand-mirrored.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

/** One account's closure state — see `closure_routes.ClosureOut` for every field. */
export type Closure = components["schemas"]["ClosureOut"];

const closurePath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/closure`;

/**
 * The `X-Confirm-Action` a close demands — `closure_routes.close_account_confirmation`,
 * mirrored.
 *
 * DELIBERATELY DIFFERENT from the string the old status close used (`close_account:<id>`,
 * now deleted with it). A confirmation captured for "end this relationship" must not be
 * replayable as "and destroy their records in thirty days", and both are bound to the
 * tenant so neither replays against another client.
 */
export function closureConfirmation(tenantId: string): string {
  return `close_and_schedule_erasure:${tenantId}`;
}

export function useClosure(tenantId: string): UseQueryResult<Closure> {
  return useQuery({
    queryKey: ["admin", "closure", tenantId],
    queryFn: () => apiRequest<Closure>(adminSession(), closurePath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

/**
 * Close the account now and schedule the erasure of its records.
 *
 * `grace_days` is sent only when an operator moved it off the default, so the server's own
 * `closure.GRACE_DAYS` stays the single source of the number — a console that always sent
 * a value would be a second place the window is decided.
 */
export function useCloseAccount(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ reason, graceDays }: { reason: string; graceDays: number | null }) =>
      apiRequest<Closure>(adminSession(), closurePath(tenantId), {
        method: "POST",
        body: graceDays == null ? { reason } : { reason, grace_days: graceDays },
        confirmAction: closureConfirmation(tenantId),
      }),
    onSuccess: () => invalidate(client, tenantId),
  });
}

/**
 * Undo a close while nothing has been erased. NO confirmation header, and that asymmetry
 * is the point rather than an oversight — the route's docstring argues it: a second factor
 * on the recovery path means the operator who closed the wrong client at a coffee shop
 * cannot fix it from the same coffee shop.
 */
export function useRestoreAccount(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<Closure>(adminSession(), closurePath(tenantId), { method: "DELETE" }),
    onSuccess: () => invalidate(client, tenantId),
  });
}

function invalidate(client: ReturnType<typeof useQueryClient>, tenantId: string): void {
  void client.invalidateQueries({ queryKey: ["admin", "closure", tenantId] });
  // `status` moves in both directions, and it is printed under the client's name on the
  // detail screen, on the Account state screen and in the directory.
  void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
  void client.invalidateQueries({ queryKey: ["admin", "tenants"] });
}
