"use client";

/**
 * Integration hooks (D-23, SURFACES §2b).
 *
 * The delivery list is the reason this exists as a screen rather than a settings
 * field: "did my CRM get it?" is the question integrations generate, and answering it
 * with a support ticket costs more than answering it with a table.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Endpoint = Schemas["EndpointOut"];
export type NewEndpointResult = Schemas["CreateEndpointOut"];
export type Delivery = Schemas["DeliveryOut"];
export type OutboundEvent =
  | "lead.created"
  | "lead.updated"
  | "call.completed"
  | "campaign.completed";

export const EVENT_LABELS: Record<OutboundEvent, string> = {
  "lead.created": "A new lead arrives",
  "lead.updated": "A lead's details change",
  "call.completed": "A call finishes",
  "campaign.completed": "A campaign finishes",
};

export function useEndpoints(session: Session): UseQueryResult<Endpoint[]> {
  return useQuery({
    queryKey: ["endpoints", session.orgSlug],
    queryFn: () => apiRequest<Endpoint[]>(session, "/v1/integrations/endpoints"),
  });
}

export function useDeliveries(session: Session): UseQueryResult<Delivery[]> {
  return useQuery({
    queryKey: ["deliveries", session.orgSlug],
    queryFn: () => apiRequest<Delivery[]>(session, "/v1/integrations/deliveries"),
    // Deliveries move on the outbox's schedule (seconds), and this screen is usually
    // open precisely because someone is watching one land.
    refetchInterval: 20_000,
  });
}

export function useCreateEndpoint(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: { url: string; events: OutboundEvent[] }) =>
      apiRequest<NewEndpointResult>(session, "/v1/integrations/endpoints", {
        method: "POST",
        body: payload,
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["endpoints", session.orgSlug] }),
  });
}

export function useDeactivateEndpoint(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (endpointId: string) =>
      apiRequest<void>(session, `/v1/integrations/endpoints/${endpointId}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["endpoints", session.orgSlug] }),
  });
}
