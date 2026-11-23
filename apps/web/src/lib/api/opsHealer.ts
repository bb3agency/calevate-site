"use client";

/**
 * The operator's view of the auto-healer (`/v1/ops/healer`, `ops:manage`): its playbooks
 * and kill switches, every incident, the ledger, and the three things a person may do to
 * an incident — run its next step now, resolve it, or show it on the public status page.
 *
 * The kill switches themselves are console settings (`healer_enabled`,
 * `healer_paused_playbooks`) and are changed on the configuration screen, not here, so
 * there is one writer of each.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { adminSession, confirmedAdminRequest } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type HealerOverview = Schemas["HealerOverviewOut"];
export type HealerPlaybook = Schemas["PlaybookOut"];
export type HealerIncident = Schemas["IncidentOut"];
export type HealerAction = Schemas["ActionOut"];
export type StatusComponentKey = NonNullable<HealerIncident["component"]>;

export const OPS_HEALER_PATH = "/v1/ops/healer";

export const opsHealerKeys = {
  overview: ["admin", "healer"] as const,
  incidents: ["admin", "healer", "incidents"] as const,
  actions: (incidentId: string | null) => ["admin", "healer", "actions", incidentId] as const,
};

/** The step-up words the API requires (`apps/api/healer/routes.py`). */
export function resolveConfirmation(incidentId: string): string {
  return `resolve_heal_incident:${incidentId}`;
}

export function statusConfirmation(incidentId: string | null): string {
  return incidentId === null ? "post_status" : `post_status:${incidentId}`;
}

export function useHealerOverview(): UseQueryResult<HealerOverview> {
  return useQuery({
    queryKey: opsHealerKeys.overview,
    queryFn: () => apiRequest<HealerOverview>(adminSession(), OPS_HEALER_PATH),
  });
}

/** How many incidents or actions a list shows. */
export const HEALER_LIST_LIMIT = 50;

/** A list cut at `HEALER_LIST_LIMIT`, and whether more exist beyond it. */
export interface HealerPage<T> {
  items: T[];
  more: boolean;
}

/** One more row than is shown is asked for, so a full page says whether it is the whole. */
function pageOf<T>(items: T[]): HealerPage<T> {
  return { items: items.slice(0, HEALER_LIST_LIMIT), more: items.length > HEALER_LIST_LIMIT };
}

export function useHealerIncidents(): UseQueryResult<HealerPage<HealerIncident>> {
  return useQuery({
    queryKey: opsHealerKeys.incidents,
    queryFn: async () =>
      pageOf(
        (
          await apiRequest<Schemas["IncidentsOut"]>(
            adminSession(),
            `${OPS_HEALER_PATH}/incidents?days=7&limit=${HEALER_LIST_LIMIT + 1}`,
          )
        ).items,
      ),
  });
}

export function useHealerActions(incidentId: string | null): UseQueryResult<HealerPage<HealerAction>> {
  const limit = HEALER_LIST_LIMIT + 1;
  return useQuery({
    queryKey: opsHealerKeys.actions(incidentId),
    queryFn: async () =>
      pageOf(
        (
          await apiRequest<Schemas["ActionsOut"]>(
            adminSession(),
            incidentId === null
              ? `${OPS_HEALER_PATH}/actions?limit=${limit}`
              : `${OPS_HEALER_PATH}/actions?limit=${limit}&incident_id=${encodeURIComponent(incidentId)}`,
          )
        ).items,
      ),
  });
}

function useInvalidateHealer() {
  const client = useQueryClient();
  return () => void client.invalidateQueries({ queryKey: opsHealerKeys.overview });
}

export function useRetryIncident() {
  const invalidate = useInvalidateHealer();
  return useMutation({
    mutationFn: (incidentId: string) =>
      apiRequest<HealerIncident>(
        adminSession(),
        `${OPS_HEALER_PATH}/incidents/${encodeURIComponent(incidentId)}/retry`,
        { method: "POST" },
      ),
    onSuccess: invalidate,
  });
}

export function useResolveIncident() {
  const invalidate = useInvalidateHealer();
  return useMutation({
    mutationFn: (incidentId: string) =>
      confirmedAdminRequest<HealerIncident>(
        `${OPS_HEALER_PATH}/incidents/${encodeURIComponent(incidentId)}/resolve`,
        { method: "POST", confirmAction: resolveConfirmation(incidentId) },
        "Marking this problem handled.",
      ),
    onSuccess: invalidate,
  });
}

export function usePostStatus() {
  const invalidate = useInvalidateHealer();
  return useMutation({
    mutationFn: ({
      incidentId,
      title,
      component,
    }: {
      incidentId: string | null;
      title: string | null;
      component: StatusComponentKey;
    }) =>
      incidentId === null
        ? confirmedAdminRequest<HealerIncident>(
            `${OPS_HEALER_PATH}/status-posts`,
            { method: "POST", body: { title, component }, confirmAction: statusConfirmation(null) },
            "Posting a notice on the public status page.",
          )
        : confirmedAdminRequest<HealerIncident>(
            `${OPS_HEALER_PATH}/incidents/${encodeURIComponent(incidentId)}/status`,
            {
              method: "PUT",
              body: { title, component },
              confirmAction: statusConfirmation(incidentId),
            },
            "Changing this problem's notice on the public status page.",
          ),
    onSuccess: invalidate,
  });
}
