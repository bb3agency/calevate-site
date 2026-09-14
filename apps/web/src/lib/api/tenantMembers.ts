"use client";

/**
 * Who holds a key to a client's account, from the operator console (D-602).
 *
 * `apps/api/admin/members_routes.py` is the authority and argues the whole shape: why the
 * roster had to exist at all (the invitation list stops at the inbox, and view-as could
 * READ the team but is withheld the membership surface), why the read is `org:read` and
 * both writes are `admin:tenants`, and why the removal takes a confirmation and the role
 * change deliberately does not.
 *
 * ## What this module keeps rather than smooths away
 *
 * - **A role change carries the role the screen was SHOWING.** `expected_role` is a
 *   compare-and-swap: the client's own owners press their own buttons, so a change made in
 *   the intervening seconds is reported as a 409 rather than overwritten. The mutation
 *   therefore takes the value the ROW rendered, never one re-read from the cache at submit
 *   time.
 * - **The removal's confirmation is built from the same rule the API applies**, so a drift
 *   between console and server is a visible 403 (`ConfirmedWriteFailure` explains it as a
 *   version skew) rather than a silent bypass.
 * - **Addresses come back in full and are not reconstructed here.** The server decides
 *   what it discloses; this module never derives, masks or re-joins one.
 *
 * ## What is NOT here
 *
 * Inviting somebody. That is `useInvite` in `./admin`, it has its own screen, and a
 * membership minted without a redeemed invitation would be an access grant with nothing
 * behind it.
 *
 * Types come from `schema.d.ts` (`pnpm -C apps/web gen:api`), never hand-mirrored.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** One person who can sign in to this client's account right now. */
export type TenantMember = Schemas["TeamMemberOut"];
export type TenantMemberRemoved = Schemas["TeamMemberRemovedOut"];
export type TenantMemberRole = Schemas["TeamMemberRoleIn"]["role"];

const membersPath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/members`;
const memberPath = (tenantId: string, userId: string) =>
  `${membersPath(tenantId)}/${encodeURIComponent(userId)}`;

export const tenantMemberKeys = {
  all: (tenantId: string) => ["admin", "tenant-members", tenantId] as const,
};

/**
 * The `X-Confirm-Action` a removal demands — `members_routes.remove_member_confirmation`,
 * mirrored.
 *
 * It carries BOTH ids. The tenant alone would let a confirmation captured while looking at
 * the departed receptionist be replayed against the owner listed above them, which on this
 * screen is one row's distance.
 */
export function removeMemberConfirmation(tenantId: string, userId: string): string {
  return `remove_member_access:${tenantId}:${userId}`;
}

export function useTenantMembers(tenantId: string): UseQueryResult<TenantMember[]> {
  return useQuery({
    queryKey: tenantMemberKeys.all(tenantId),
    queryFn: () => apiRequest<TenantMember[]>(adminSession(), membersPath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

/**
 * Move somebody between owner and staff.
 *
 * NO confirmation header, matching the API and for the reason its docstring gives: this is
 * undone by the same operator on the same screen in one click, and ceremony on a reversible
 * act teaches an operator to type past ceremony on the route where it matters.
 */
export function useSetTenantMemberRole(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      role,
      expectedRole,
    }: {
      userId: string;
      role: TenantMemberRole;
      /** What the row was showing when the control was used — the CAS guard. */
      expectedRole: TenantMemberRole;
    }) =>
      apiRequest<TenantMember>(adminSession(), memberPath(tenantId, userId), {
        method: "PATCH",
        body: { role, expected_role: expectedRole },
      }),
    onSuccess: () => invalidate(client, tenantId),
  });
}

/** Take somebody's access away. Confirmed, and with no undo on our side. */
export function useRemoveTenantMember(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiRequest<TenantMemberRemoved>(adminSession(), memberPath(tenantId, userId), {
        method: "DELETE",
        confirmAction: removeMemberConfirmation(tenantId, userId),
      }),
    onSuccess: () => invalidate(client, tenantId),
  });
}

function invalidate(client: ReturnType<typeof useQueryClient>, tenantId: string): void {
  void client.invalidateQueries({ queryKey: tenantMemberKeys.all(tenantId) });
  // The invitation list moves with it in one direction: `create_invitation` refuses an
  // address that is already on the team, so an operator who has just removed somebody is
  // very often about to invite them back.
  void client.invalidateQueries({ queryKey: ["admin", "invitations", tenantId] });
}
