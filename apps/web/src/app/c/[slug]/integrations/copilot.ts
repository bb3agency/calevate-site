"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import type { WriteAccess } from "@/lib/api/hooks";
import type {
  useDeliveries,
  useEndpointOptions,
  useEndpoints,
} from "@/lib/api/integrations";

/*
 * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
 *
 * ## The endpoint URLs are not sent, and neither is a delivered body
 *
 * A delivery payload is a lead — a name, a number, the captured details — which is why
 * opening one is gated on `calls:read_raw` and writes an audit row. It does not go to a
 * model. The endpoint URL is not personal, but it is a client's own private address and
 * it is the thing a mis-typed fill would silently break, so what is declared is the
 * SHAPE of the integration: how many endpoints, of what kind, subscribed to what,
 * carrying which content, and how the recent deliveries went.
 *
 * That is the vocabulary of the question this screen exists to answer — "did my CRM get
 * it?" — and the copilot can answer it without seeing one lead.
 *
 * ## Nothing is writable
 *
 * Registering an endpoint mints a signing secret the API cannot reissue, and turning one
 * off has no re-activate route (see `stopping` above). Neither is an act to hand to an
 * assistant, and the create form's own fields are consequently not declared at all.
 */
export function useIntegrationsCopilot({
  endpoints,
  deliveries,
  options,
  write,
  mayReadPayload,
}: {
  endpoints: ReturnType<typeof useEndpoints>;
  deliveries: ReturnType<typeof useDeliveries>;
  options: ReturnType<typeof useEndpointOptions>;
  write: WriteAccess;
  mayReadPayload: boolean;
}) {
  useCopilotSurface({
    route: "/c/{slug}/integrations",
    title: "Where your leads are sent",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: endpoints.data
          ? "the endpoints below have loaded"
          : endpoints.error
            ? "the endpoints failed to load, so none is listed"
            : "still loading",
      },
      ...(endpoints.data
        ? [
            { key: "endpoints_total", label: "Destinations registered", value: String(endpoints.data.length) },
            {
              key: "endpoints_active",
              label: "Of those, still receiving",
              value: String(endpoints.data.filter((endpoint) => endpoint.active).length),
            },
            {
              key: "endpoint_kinds",
              label: "What kind each destination is",
              value:
                endpoints.data.map((endpoint) => endpoint.kind).join(", ") || "none registered",
            },
            {
              key: "endpoint_events",
              label: "Events subscribed to across all destinations",
              value:
                [...new Set(endpoints.data.flatMap((endpoint) => endpoint.events))].join(", ") ||
                "none",
            },
            {
              key: "endpoint_content",
              label: "How many destinations are sent a transcript, a raw transcript, or a recording link",
              value: `transcript: ${endpoints.data.filter((e) => e.include_transcript).length}, raw transcript: ${endpoints.data.filter((e) => e.include_raw_transcript).length}, recording link: ${endpoints.data.filter((e) => e.include_recording_url).length}`,
            },
          ]
        : []),
      {
        key: "deliveries_state",
        label: "Have the recent deliveries loaded?",
        value: deliveries.data ? "yes" : deliveries.error ? "no — they failed to load" : "still loading",
      },
      ...(deliveries.data
        ? [
            { key: "deliveries_listed", label: "Recent deliveries listed", value: String(deliveries.data.length) },
            {
              key: "deliveries_by_status",
              label: "How those deliveries ended",
              value:
                [...new Set(deliveries.data.map((delivery) => delivery.status ?? "unknown"))]
                  .map(
                    (status) =>
                      `${status}: ${deliveries.data.filter((delivery) => (delivery.status ?? "unknown") === status).length}`,
                  )
                  .join(", ") || "no deliveries yet",
            },
            {
              key: "deliveries_retried",
              label: "Deliveries that needed more than one attempt",
              value: String(deliveries.data.filter((delivery) => delivery.attempts > 1).length),
            },
          ]
        : []),
      ...(options.data
        ? [
            { key: "events_available", label: "Events this platform can send", value: options.data.events.join(", ") },
            {
              key: "sheets_available",
              label: "Can this deployment deliver into a Google Sheet?",
              value: options.data.sheets_delivery_available ? "yes" : "no",
            },
          ]
        : []),
      {
        key: "may_change",
        label: "May this session change where events are sent?",
        value: write.allowed ? "yes" : `no — ${write.reason ?? "no reason given"}`,
      },
      {
        key: "may_open_payload",
        label: "May this session open a delivered body?",
        value: mayReadPayload ? "yes — opening one writes an audit record" : "no",
      },
    ],
    apply: noFill,
  });
}
