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
export type DeliveryPayload = Schemas["DeliveryPayloadOut"];
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

/**
 * What we actually sent for one delivery — a GET WITH A SIDE EFFECT, and treated as one.
 *
 * `/v1/integrations/deliveries/{id}/payload` writes an `audit_log` row in the same
 * transaction as the read (integrations/routes.py), because the body is unredacted
 * personal data under hard rule 5. So every automatic refetch would both re-expose a
 * customer's details and forge an audit entry naming someone who did not ask for them:
 * all of the library's implicit refetching is off, and the request happens when someone
 * presses the button and at no other moment. Same shape, same reasoning, as
 * `useRawTranscript` on the call detail screen.
 *
 * `retry: false`: a 403 or a "we no longer keep it" must surface once, not three times.
 */
export function useDeliveryPayload(
  session: Session,
  deliveryId: string | null,
): UseQueryResult<DeliveryPayload> {
  return useQuery({
    queryKey: ["delivery-payload", session.orgSlug, deliveryId],
    queryFn: () =>
      apiRequest<DeliveryPayload>(session, `/v1/integrations/deliveries/${deliveryId}/payload`),
    enabled: deliveryId !== null,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
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
