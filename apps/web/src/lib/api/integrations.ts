"use client";

/**
 * Integration hooks (D-23, SURFACES §2b).
 *
 * The delivery list is the reason this exists as a screen rather than a settings
 * field: "did my CRM get it?" is the question integrations generate, and answering it
 * with a support ticket costs more than answering it with a table.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { lookup } from "@/lib/lookup";

import { ApiProblem, apiRequest, type Session } from "./client";
import type { components, operations } from "./schema";

type Schemas = components["schemas"];

export type Endpoint = Schemas["EndpointOut"];
export type NewEndpointResult = Schemas["CreateEndpointOut"];
export type Delivery = Schemas["DeliveryOut"];
export type DeliveryPayload = Schemas["DeliveryPayloadOut"];
/** A Google Sheets endpoint, as the create route reports it back (D-23's second kind). */
export type NewSheetEndpointResult = Schemas["SheetEndpointOut"];
export type NewSheetEndpoint = Schemas["CreateSheetEndpointIn"];

/**
 * The events an endpoint may subscribe to.
 *
 * Read off the GENERATED request body rather than spelled out here, which is the point of
 * the change: this union used to be four hand-written string literals, so an event the
 * API added or removed changed nothing in this build until somebody noticed. Both create
 * routes take the identical `EventName` literal, so either one would do as the source.
 */
export type OutboundEvent = NewSheetEndpoint["events"][number];

export const EVENT_LABELS: Record<OutboundEvent, string> = {
  "lead.created": "A new lead arrives",
  "lead.updated": "A lead's details change",
  "call.completed": "A call finishes",
  "campaign.completed": "A campaign finishes",
};

/**
 * A wire event name, if it is one this build has copy for.
 *
 * `lookup`, not `EVENT_LABELS[name]`: the catalogue below is the SERVER's list, so the
 * strings come off the wire and an indexed read walks the prototype chain (lib/lookup.ts).
 * A name we cannot label is still rendered — as itself — because hiding an event the
 * server offers would silently narrow the subscription the client can build.
 */
export function eventLabel(name: string): string | null {
  return lookup(EVENT_LABELS, name) ?? null;
}

/**
 * `GET /v1/integrations/events` — the catalogue, from the server rather than from here.
 *
 * The screen used to carry its own `ALL_EVENTS` array, which is the same defect as a
 * hand-written wire type one level up: the checkbox list was a copy of a server list that
 * nothing kept in step, so a new event type would have shipped invisible and a withdrawn
 * one would have been offered until it 422'd on submit.
 *
 * ⚠ The route is declared `-> dict[str, list[str]]`, so the generated type is an index
 * signature and `events` is not a NAMED field — this is the one read in the module whose
 * shape `tsc` cannot check for us. Reported, not worked around: modelling the response
 * (`EventCatalogueOut`) is a backend change and this slice does not make backend changes.
 * `lookup` guards the read in the meantime, and a response without the key is treated as
 * an answer we cannot use rather than as an empty catalogue.
 */
type EventCatalogueBody =
  operations["list_event_types_v1_integrations_events_get"]["responses"][200]["content"]["application/json"];

export function useEventCatalogue(session: Session): UseQueryResult<string[]> {
  return useQuery({
    queryKey: ["integration-events", session.orgSlug],
    queryFn: async () => {
      const body = await apiRequest<EventCatalogueBody>(session, "/v1/integrations/events");
      const events = lookup(body, "events");
      if (!events) {
        // A 200 whose body we cannot read is a FAILED read, not an empty catalogue —
        // §52's distinction, enforced at the seam so no screen has to make it twice.
        //
        // Thrown as an `ApiProblem` rather than a bare `Error` for the reason
        // `AuthProblem` exists (client.ts): `ProblemNotice` renders a bare Error as
        // "Something went wrong" plus a connection hint, and neither is true here — we
        // reached the API and it answered. `status: 0` says no HTTP failure happened, and
        // `retryable: false` keeps a retry button off a response that will not change.
        throw new ApiProblem(0, {
          kind: "internal",
          type: "urn:calevate:browser/unreadable_event_catalogue",
          title: "The list of events could not be read",
          detail: "The list of events did not arrive in a shape we understand.",
          remediation:
            "Reload the page. If it keeps happening, tell us — this console may be out of step with the API.",
          retryable: false,
        });
      }
      return events;
    },
    // The catalogue is a constant of the deployment, not of the account.
    staleTime: 30 * 60_000,
  });
}

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

/**
 * The refusal a deployment with no Google service account answers with.
 *
 * `create_sheets_endpoint` checks `sheets_delivery_available()` BEFORE it writes anything,
 * and that is a FOUNDER/OPS decision (no `GOOGLE_SHEETS_PROVIDER`), not a fault: the
 * route's own argument is that offering a transport that cannot deliver recreates the
 * "silently never delivers" defect the sheets work existed to remove. The screen therefore
 * recognises this one code by name and renders the server's own words as a STATE, while
 * every other refusal goes through `ProblemNotice` like any other error.
 */
export const SHEETS_UNAVAILABLE_CODE = "sheets_delivery_unavailable";

/**
 * `outbound_webhooks.kind` for a Google Sheets endpoint (`service.SHEET_KIND`).
 *
 * `EndpointOut.kind` is a bare `str` on the wire — the column holds `webhook` or
 * `google_sheets` and the response model does not narrow it — so the constant lives here
 * rather than being spelled at each comparison in a screen.
 */
export const SHEET_KIND = "google_sheets";

/**
 * `POST /v1/integrations/endpoints/sheets` — D-23's other kind, from a screen at last.
 *
 * No credential field, and there is no way to add one: `secret_ref` is an `sm://` pointer
 * into OUR secrets manager, so accepting one from a client would be a tenancy hole wearing
 * a config field's clothes. Attaching it is an operator action, which is why the response
 * carries `credential_attached` and the screen prints it rather than implying the sheet is
 * ready.
 */
export function useCreateSheetsEndpoint(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: NewSheetEndpoint) =>
      apiRequest<NewSheetEndpointResult>(session, "/v1/integrations/endpoints/sheets", {
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
