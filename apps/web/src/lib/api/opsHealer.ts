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

import { adminSession } from "./admin";
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

export function useHealerIncidents(): UseQueryResult<{ items: HealerIncident[] }> {
  return useQuery({
    queryKey: opsHealerKeys.incidents,
    queryFn: () =>
      apiRequest<{ items: HealerIncident[] }>(
        adminSession(),
        `${OPS_HEALER_PATH}/incidents?days=7&limit=50`,
      ),
  });
}

export function useHealerActions(incidentId: string | null): UseQueryResult<{ items: HealerAction[] }> {
  return useQuery({
    queryKey: opsHealerKeys.actions(incidentId),
    queryFn: () =>
      apiRequest<{ items: HealerAction[] }>(
        adminSession(),
        incidentId === null
          ? `${OPS_HEALER_PATH}/actions?limit=50`
          : `${OPS_HEALER_PATH}/actions?limit=50&incident_id=${encodeURIComponent(incidentId)}`,
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
      apiRequest<HealerIncident>(
        adminSession(),
        `${OPS_HEALER_PATH}/incidents/${encodeURIComponent(incidentId)}/resolve`,
        { method: "POST", confirmAction: resolveConfirmation(incidentId) },
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
        ? apiRequest<HealerIncident>(adminSession(), `${OPS_HEALER_PATH}/status-posts`, {
            method: "POST",
            body: { title, component },
            confirmAction: statusConfirmation(null),
          })
        : apiRequest<HealerIncident>(
            adminSession(),
            `${OPS_HEALER_PATH}/incidents/${encodeURIComponent(incidentId)}/status`,
            {
              method: "PUT",
              body: { title, component },
              confirmAction: statusConfirmation(incidentId),
            },
          ),
    onSuccess: invalidate,
  });
}
