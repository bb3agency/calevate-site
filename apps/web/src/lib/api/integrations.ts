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
import type { components } from "./schema";

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
 * `GET /v1/integrations/events` — what may be subscribed to, and what may be sent where.
 *
 * The generated type, not a hand-written mirror. Two things the SERVER's shape carries
 * that a mirror would have been free to get wrong, so they are recorded here rather
 * than re-declared:
 *
 * `events` is `string[]`, deliberately, and not this build's `OutboundEvent` union. The
 * server's list is what the RUNNING deployment offers; the union is what THIS build can
 * put in a request body. They are different facts, and narrowing the response to the
 * union would make the gap unrepresentable — a deployment that adds an event would 500
 * out of response validation instead of showing up as "this account can also receive X,
 * which this console cannot subscribe to yet".
 *
 * `sheets_delivery_available` is A HINT FOR RENDERING, never the check. It is cached for
 * half an hour, so a screen can be optimistic and wrong; the route still refuses and the
 * form still renders that refusal. Same doctrine as
 * `KycRecordOut.number_purchase_available` — the server computes the predicate every
 * gate asks, and a console that re-derived it would disagree with the gate on the day it
 * mattered.
 */
export type EndpointOptions = Schemas["EndpointOptionsOut"];

/**
 * The screen's two facts about this deployment, in ONE read.
 *
 * The screen used to carry its own `ALL_EVENTS` array, which is a hand-written wire type
 * one level up: a new event type would have shipped invisible and a withdrawn one would
 * have been offered until it 422'd on submit. It also had no way to know whether Sheets
 * delivery existed, so the Sheets form discovered the refusal by ATTEMPTING the create.
 *
 * Both facts come back together on purpose (the API's own argument, and
 * `KycRecordOut`'s): a screen holding the events without the capability, or the reverse,
 * renders half a decision.
 *
 * ## What went, and what stayed, of the old guard
 *
 * `lookup(body, "events")` is GONE, and that was the actual workaround: the route
 * returned `dict[str, list[str]]`, so the generated type was an index signature, `events`
 * was not a named field, and an indexed read of it walked the prototype chain. Both reads
 * below are now named fields on a declared model and `tsc` checks them.
 *
 * The REFUSAL stayed, deliberately, and it is no longer defence in depth against a typing
 * gap — it is the §52 boundary for this screen. The hook now returns the whole body, so a
 * 200 missing `events` would reach `EventChoices` as `undefined.filter(…)`: a blank screen
 * mid-render, which is worse than both a refusal and an empty state. And a 200 missing
 * `sheets_delivery_available` would render "Sheets is not switched on for your account" —
 * our ignorance printed as one of the server's two answers, which is precisely what §52
 * forbids. One read gates every control on this screen, so it is the one worth asserting;
 * the neighbours below degrade to a visibly empty list, not to a state that lies.
 */
export function useEndpointOptions(session: Session): UseQueryResult<EndpointOptions> {
  return useQuery({
    queryKey: ["integration-options", session.orgSlug],
    queryFn: async () => {
      const body = await apiRequest<EndpointOptions>(session, "/v1/integrations/events");
      if (!Array.isArray(body?.events) || typeof body?.sheets_delivery_available !== "boolean") {
        // A 200 we cannot read is a FAILED read, not an empty catalogue and not a
        // withdrawn capability — enforced at the seam so no screen makes the call twice.
        //
        // Thrown as an `ApiProblem` rather than a bare `Error` for the reason
        // `AuthProblem` exists (client.ts): `ProblemNotice` renders a bare Error as
        // "Something went wrong" plus a connection hint, and neither is true here — we
        // reached the API and it answered. `status: 0` says no HTTP failure happened, and
        // `retryable: false` keeps a retry button off a response that will not change.
        throw new ApiProblem(0, {
          kind: "internal",
          type: "urn:calevate:browser/unreadable_endpoint_options",
          title: "The integration options could not be read",
          detail: "The list of events did not arrive in a shape we understand.",
          remediation:
            "Reload the page. If it keeps happening, tell us — this console may be out of step with the API.",
          retryable: false,
        });
      }
      return body;
    },
    // Both fields are constants of the DEPLOYMENT, not of the account: which events exist
    // and whether a Google service account is configured change when we deploy or when an
    // operator flips config, never per client action. The staleness this buys is exactly
    // why the server must keep refusing rather than trusting what we cached.
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
 * What we actually sent for one delivery — a GET WITH A SIDE EFFECT, and therefore a
 * MUTATION.
 *
 * `/v1/integrations/deliveries/{id}/payload` writes an `audit_log` row in the same
 * transaction as the read (integrations/routes.py), because the body is unredacted
 * personal data under hard rule 5. The row IS the route's purpose: "who opened this
 * customer's data, and how often" has to be answerable from `audit_log` alone.
 *
 * **This was a `useQuery`, and it was the same defect `useRawTranscript` carried** — it
 * even said so in this comment, and it was left behind when that one was fixed. No
 * staleness policy a query offers is right for a read that records itself: refetching
 * automatically forges rows naming somebody who did not ask, and the `staleTime: Infinity`
 * that stopped that meant re-opening the same delivery was served from the cache, a
 * second look that wrote no second row.
 *
 * `useMutation` is the shape that fits, and it is the shape `useRawTranscript` and
 * `useRecordingLink` use for the identical reason. One way per problem: a GET that writes
 * is asked for, never cached. The caller `reset()`s it when the panel closes, so a
 * re-open shows nothing until the NEW answer lands rather than replaying the last one —
 * which on a switch between rows would be the wrong customer's data under the new row's
 * heading.
 *
 * `retry: false`: a 403 or a "we no longer keep it" must surface once, not three times —
 * and two silent retries would each write a row for a refusal.
 */
export function useDeliveryPayload(session: Session) {
  return useMutation({
    mutationFn: (deliveryId: string) =>
      apiRequest<DeliveryPayload>(session, `/v1/integrations/deliveries/${deliveryId}/payload`),
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
 *
 * Still needed now that `EndpointOptions.sheets_delivery_available` exists, and this is
 * the point of the pair rather than a leftover. The capability decides whether the form
 * is OFFERED; this code is how the screen learns it was wrong to offer it — a stale
 * capability, or an operator turning Sheets off between the read and the submit. Deleting
 * it would make the screen's optimism the check, which is exactly what the server refuses
 * to allow (`tests/sheets_endpoint_test.py` §6).
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
