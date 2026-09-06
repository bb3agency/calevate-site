"use client";

/**
 * A client's own business record — reading it, and correcting it (D-545).
 *
 * The founder opened a client in the console and found no way to fix a typo in their
 * name. `PATCH /v1/admin/tenants/{id}` had shipped with D-538 and NOTHING CALLED IT: the
 * route, its audit rows and its notice to the replaced address were all reachable by curl
 * and by nothing an operator could press. This module is that form's client.
 *
 * ## Three things this module keeps rather than smooths over
 *
 * - **The read is its own endpoint.** `GET /v1/admin/tenants/{id}` is the DIRECTORY row
 *   and carries no `billing_email`, deliberately — a roster that lists every client's
 *   contact address discloses one whenever anybody opens it. `/profile` is one tenant, one
 *   read, and the API records it as an impersonation read (D-482 L-1).
 * - **The address change sends a confirmation header and the other fields do not.** The
 *   server demands `change_notice_address:<id>` for `billing_email` alone, so attaching it
 *   to every save would be a confirmation of nothing (`useSetTenantStatus`'s old comment
 *   made the same argument about the close it used to guard).
 * - **`pending_notices_retargeted` is rendered, not swallowed.** The API resolves a
 *   notice's recipients when it DELIVERS, so notices already queued when the address moves
 *   go to the new one. The screen says how many. See the route's docstring for why that
 *   behaviour is kept rather than changed.
 *
 * Types come from `schema.d.ts` (`pnpm -C apps/web gen:api`), never hand-mirrored.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** The business record as the form reads it back. */
export type TenantProfile = Schemas["TenantProfileOut"];
/** What an operator submits — every field optional, at least one required by the server. */
export type EditTenantIn = Schemas["EditTenantIn"];
export type EditTenantOut = Schemas["EditTenantOut"];

const profilePath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/profile`;
const editPath = (tenantId: string) => `/v1/admin/tenants/${encodeURIComponent(tenantId)}`;

/**
 * The `X-Confirm-Action` value a NOTICE-ADDRESS change demands — the server's
 * `admin/routes.notice_address_confirmation`, mirrored.
 *
 * Bound to the tenant so a confirmation captured while correcting one client's address
 * cannot be replayed against the next one in the directory, and built here from the same
 * rule the API applies so a drift is a visible 403 rather than a silent bypass.
 */
export function noticeAddressConfirmation(tenantId: string): string {
  return `change_notice_address:${tenantId}`;
}

/** How each editable field reads to an operator, and what changing it costs. */
export interface FieldCopy {
  label: string;
  /** What this field DOES, said before it is changed. */
  hint: string;
}

/**
 * A `Record` over the field names the API accepts, so a field added to `EditTenantIn`
 * stops this file compiling rather than rendering an unlabelled input (the device
 * `TERMS_STATE_COPY` uses).
 */
export const EDIT_FIELD_COPY: Record<keyof EditTenantIn, FieldCopy> = {
  name: {
    label: "Business name",
    hint: "What this client is called on invoices, in notices and across this console. Their web address does not change with it.",
  },
  billing_email: {
    label: "Where this account's notices go",
    hint: "The invoice, the hot-lead alert and the closure notice are all addressed from here. It is NOT a sign-in address — nobody gains or loses access by changing it — but it does move a channel, so it takes a confirmation and the address being replaced is told.",
  },
  vertical_template: {
    label: "Vertical",
    hint: "Picks the extraction schema a NEW agent starts from, and decides whether subscriber verification and the first-campaign hold apply. Agents that already exist keep the fields they are collecting into.",
  },
};

export function useTenantProfile(tenantId: string): UseQueryResult<TenantProfile> {
  return useQuery({
    queryKey: ["admin", "tenant-profile", tenantId],
    queryFn: () => apiRequest<TenantProfile>(adminSession(), profilePath(tenantId)),
    enabled: Boolean(tenantId),
  });
}

export function useEditTenant(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: EditTenantIn) =>
      apiRequest<EditTenantOut>(adminSession(), editPath(tenantId), {
        method: "PATCH",
        body: changes,
        // ONLY when the address moves. The server demands it for that field alone, and a
        // header on every save trains an operator to clear a prompt without reading it.
        ...(changes.billing_email != null
          ? { confirmAction: noticeAddressConfirmation(tenantId) }
          : {}),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["admin", "tenant-profile", tenantId] });
      // The name and the vertical are printed under the client's heading on the detail
      // screen and in the directory; a stale one there is the console telling an operator
      // the correction did not take.
      void client.invalidateQueries({ queryKey: ["admin", "tenant", tenantId] });
      void client.invalidateQueries({ queryKey: ["admin", "tenants"] });
    },
  });
}
