"use client";

/**
 * One client account, as an OPERATOR reads it: what is holding them up, and what has been
 * done to them.
 *
 *     GET /v1/admin/tenants/{id}/readiness   `org:read`, admin realm
 *     GET /v1/admin/tenants/{id}/activity    `org:read`, admin realm
 *
 * `apps/api/admin/account_routes.py` argues both designs — why they are `org:read` rather
 * than `admin:tenants`, why each writes an `admin.tenant_read` row, and why the activity
 * trail carries no personal data. What lives here is the console's half: the cache keys,
 * the paging state, and the two rules about what may be rendered.
 *
 * **NOTHING HERE POLLS.** Every read of either route writes an audit row (coalesced per
 * operator per window, but still). A `refetchInterval` would fill the ledger with reads
 * nobody performed — the argument `useTenant` already makes for the detail record, and it
 * is stronger here: a readiness answer changes when a HUMAN acts on a gate, and an
 * activity trail changes when a human acts at all.
 *
 * **THE SERVER'S WORDS, NOT OURS.** `title`, `reason` and `next_step` arrive written. A
 * readiness screen that paraphrased them would be a second opinion about a compliance
 * verdict held in the place least able to defend it, and it would drift the day a gate's
 * sentence changes. The only copy in this file is the ACTOR column — `client` /
 * `calevate` — which is an operator's word for whose move it is.
 *
 * ⚠ THE RESPONSE TYPES ARE HAND-WRITTEN AND MUST BECOME GENERATED ONES. Every other
 * module here reads `Schemas[...]` from `./schema`, which is generated from the OpenAPI
 * document; these three routes are newer than the checked-in snapshot and regenerating it
 * is a separate step (it is one artefact several changes land in at once). The shapes
 * below mirror `TenantReadinessOut`, `ActivityEntryOut` and `TenantActivityOut` field for
 * field. Replace them with `Schemas["TenantReadinessOut"]` and the two others the moment
 * the snapshot is regenerated — a hand-written response type is exactly the drift the
 * generated client exists to stop.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

/** Whose move a readiness row is. Two values and no third (`legal/readiness.py`). */
export type ReadinessActor = "client" | "calevate";

/** One condition standing between this account and its first call. */
export interface ReadinessRow {
  /** The gate's own machine name, e.g. `agreements_not_accepted`. */
  rule: string;
  title: string;
  /** The gate's refusal sentence, verbatim — the same one the client is shown. */
  reason: string;
  actor: ReadinessActor;
  next_step: string;
}

export interface TenantReadiness {
  tenant_id: string;
  may_operate: boolean;
  blocked_on_calevate: number;
  rows: ReadinessRow[];
}

/** Who acted: one of ours, somebody at the client, or the platform itself. */
export type ActorType = "admin" | "user" | "system";

export interface ActivityEntry {
  id: string;
  at: string;
  /** The dotted action name as `write_audit` recorded it. */
  action: string;
  object_type: string | null;
  object_id: string | null;
  actor_type: ActorType;
  actor_id: string | null;
  /** The operator's name, when one of ours acted. Null for a client or system actor. */
  actor_label: string | null;
  /** Set when the act came through a view-as session (D-587). */
  via_grant_id: string | null;
}

export interface TenantActivityPage {
  tenant_id: string;
  entries: ActivityEntry[];
  total: number;
  limit: number;
  offset: number;
}

/** How many entries one page of the trail holds. The server's own bound is 200. */
export const ACTIVITY_PAGE_SIZE = 25;

export function readinessKey(tenantId: string) {
  return ["admin", "tenant", tenantId, "readiness"] as const;
}

export function activityKey(tenantId: string, offset: number, actorType: ActorType | "all") {
  return ["admin", "tenant", tenantId, "activity", offset, actorType] as const;
}

export function useTenantReadiness(tenantId: string): UseQueryResult<TenantReadiness> {
  return useQuery({
    queryKey: readinessKey(tenantId),
    queryFn: () =>
      apiRequest<TenantReadiness>(adminSession(), `/v1/admin/tenants/${tenantId}/readiness`),
    enabled: Boolean(tenantId),
  });
}

export function useTenantActivity(
  tenantId: string,
  { offset = 0, actorType = "all" }: { offset?: number; actorType?: ActorType | "all" } = {},
): UseQueryResult<TenantActivityPage> {
  const search = new URLSearchParams({
    limit: String(ACTIVITY_PAGE_SIZE),
    offset: String(offset),
  });
  if (actorType !== "all") search.set("actor_type", actorType);
  return useQuery({
    queryKey: activityKey(tenantId, offset, actorType),
    queryFn: () =>
      apiRequest<TenantActivityPage>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/activity?${search.toString()}`,
      ),
    enabled: Boolean(tenantId),
    // The page an operator is reading does not move under them while they page back
    // through it; a refetch on focus would renumber the offsets mid-read.
    refetchOnWindowFocus: false,
  });
}

/**
 * What an operator calls an actor. The `admin` case is deliberately not "Calevate" —
 * the operator's own NAME is on the row when we have it, and this label is what fills
 * the gap for a pre-D-171 account with no name recorded.
 */
export const ACTOR_LABELS: Record<ActorType, string> = {
  admin: "Calevate operator",
  user: "Someone at this client",
  system: "Automatic",
};
