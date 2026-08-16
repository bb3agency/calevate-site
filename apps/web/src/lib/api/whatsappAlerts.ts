"use client";

/**
 * WhatsApp hot-lead alerts — the client's own opt-in, and the operator's record of one.
 *
 * FLOWS §6 promises "WhatsApp+email to owner within 2 min" on a hot lead, and the
 * WhatsApp half has never delivered for one reason: `resolve_destination` refuses without
 * a live opt-in, and there was no surface anywhere that could record one. The three
 * routes behind this module shipped complete and reachable only by curl.
 *
 * FIVE PROPERTIES OF THE API THIS MODULE KEEPS RATHER THAN SMOOTHS OVER:
 *
 * - **`messageable` is the SERVER's verdict.** It is computed from the same read the
 *   hot-lead worker runs, so a screen that recomputed "granted and not withdrawn" for
 *   itself could show a green tick over an alert that will never be sent. Same doctrine
 *   as `is_verified` in `kyc.ts` and `held` in `firstCampaign.ts`.
 * - **The wording travels with the state.** `current_notice_text` and
 *   `current_notice_version` are on every response and carry NO defaults, so the tick-box
 *   copy comes from the same place the stored `notice_version` points at. A React
 *   component holding its own sentence would make the recorded version evidence of
 *   nothing: `whatsapp_optin.ALERT_NOTICE_TEXT` is what a row's version can be resolved
 *   back to years later, and a string that lives only in a browser bundle cannot be.
 * - **A stale build is REFUSED, not recorded.** The console sends the version it showed
 *   and the API compares it with the one in force (`alert_optin_notice_out_of_date`), so
 *   a client agreeing to last quarter's wording never has this quarter's recorded against
 *   them. That is why `record` sends `notice_version` from the RESPONSE rather than from a
 *   constant here.
 * - **`delivery_available` is a different question from `messageable`.** One asks whether
 *   this deployment could send anything at all (no WABA credential exists yet — D-91,
 *   `whatsapp_delivery_status`), the other whether this person agreed. A screen that
 *   collapsed them would either hide the opt-in until the vendor account exists or
 *   promise alerts nothing can deliver.
 * - **No phone number is accepted or returned, anywhere.** The subject is the
 *   authenticated principal (client realm) or the tenant's owner (admin realm), read
 *   server-side from the row the worker would send to, so the consent key and the
 *   delivery key cannot drift.
 *
 * TWO REALMS, TWO ROUTERS, AND THEY ARE NOT INTERCHANGEABLE. The client-realm pair is the
 * owner opting THEMSELVES in — self-evidencing, and a CHECK constraint enforces that the
 * subject and the recorder are the same person. The admin pair is an operator recording
 * that the owner already agreed somewhere else, which is a claim about somebody else and
 * therefore carries a document reference. An impersonating admin can do neither: D-22
 * refuses `org:manage` inside a view-as session, which is exactly why the operator path
 * exists separately and audibly.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** State + the wording in force + what this deployment can deliver. Never a number. */
export type AlertOptIn = Schemas["AlertOptInOut"];
/** `granted` or `withdrawn`. There is no `declined`: absence is the default of the world. */
export type AlertOptInStatus = Schemas["RecordAlertOptInIn"]["status"];
/** Where the agreement is filed — a reference, never the document (the `secret_ref` rule). */
export type AlertOptInEvidence = Schemas["RecordOperatorOptInIn"]["evidence"];

export const WHATSAPP_ALERTS_PATH = "/v1/compliance/whatsapp-alerts";

export const whatsappAlertKeys = {
  mine: (org: string) => ["whatsapp-alerts", org] as const,
  tenant: (tenantId: string) => ["admin", "whatsapp-alerts", tenantId] as const,
};

const adminPath = (tenantId: string) =>
  `/v1/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp-alerts`;

/** My own opt-in state. `org:read`, so it survives a read-only view-as session. */
export function useMyAlertOptIn(session: Session): UseQueryResult<AlertOptIn> {
  return useQuery({
    queryKey: whatsappAlertKeys.mine(session.orgSlug),
    queryFn: () => apiRequest<AlertOptIn>(session, WHATSAPP_ALERTS_PATH),
  });
}

/**
 * Turn my own alerts on or off — one row appended to the ledger, never an edit.
 *
 * `notice_version` is taken from the state the screen is RENDERING, not from a constant
 * in this bundle. That is the whole point of the server's check: the version recorded
 * must be the version the person actually read, and the only build that can be sure of
 * that is the one whose text is on the screen in front of them.
 */
export function useRecordMyAlertOptIn(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ status, noticeVersion }: { status: AlertOptInStatus; noticeVersion: string }) =>
      apiRequest<AlertOptIn>(session, WHATSAPP_ALERTS_PATH, {
        method: "POST",
        body: { status, notice_version: noticeVersion },
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: whatsappAlertKeys.mine(session.orgSlug) }),
  });
}

/**
 * One client's owner, as the operator about to record for them may know it.
 *
 * The admin realm's OWN route, not the client one read through impersonation: a view-as
 * session has no `users` row, so `GET /v1/compliance/whatsapp-alerts` deliberately
 * answers with no subject state there rather than handing one human's consent record to
 * another. Without this read the operator control would be write-only.
 */
export function useTenantAlertOptIn(tenantId: string): UseQueryResult<AlertOptIn> {
  return useQuery({
    queryKey: whatsappAlertKeys.tenant(tenantId),
    queryFn: () => apiRequest<AlertOptIn>(adminSession(), adminPath(tenantId)),
  });
}

export interface OperatorOptInInput {
  status: AlertOptInStatus;
  /** Required by the service AND a CHECK for a grant; meaningless for a withdrawal. */
  evidence: AlertOptInEvidence;
}

/**
 * Record that this client's owner agreed elsewhere — onboarding, a call, a signed form.
 *
 * No step-up header, deliberately, and the asymmetry with the ops console is the point:
 * this write names ONE tenant and one owner, it is `admin:tenants` (which D-22 refuses to
 * an impersonating session), and it demands a document reference for a grant. The
 * confirmation discipline is spent where the blast radius is cross-tenant.
 */
export function useRecordTenantAlertOptIn(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ status, evidence }: OperatorOptInInput) =>
      apiRequest<AlertOptIn>(adminSession(), adminPath(tenantId), {
        method: "POST",
        body: { status, evidence },
      }),
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: whatsappAlertKeys.tenant(tenantId) }),
  });
}
