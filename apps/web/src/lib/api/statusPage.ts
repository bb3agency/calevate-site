/**
 * The public status page's one read (`GET /v1/public/status`). Unauthenticated, cached for
 * thirty seconds at the edge, and naming no account: the server returns only what an
 * operator or the outage playbook chose to post.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type StatusPage = Schemas["StatusPageOut"];
export type StatusComponent = Schemas["StatusComponentOut"];
export type StatusIncident = Schemas["StatusIncidentOut"];

export const PUBLIC_STATUS_PATH = "/v1/public/status";

/** No session: the read is the world's. */
const NOBODY: Session = { orgSlug: "" };

export function usePublicStatus(): UseQueryResult<StatusPage> {
  return useQuery({
    queryKey: ["public", "status"],
    queryFn: () => apiRequest<StatusPage>(NOBODY, PUBLIC_STATUS_PATH),
    refetchInterval: 60_000,
  });
}

export const COMPONENT_STATE_WORDS: Record<StatusComponent["state"], string> = {
  operational: "Working normally",
  degraded: "Some problems",
  outage: "Not working",
};
