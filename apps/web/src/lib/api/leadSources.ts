"use client";

/**
 * Lead-source (inbound ingest) hooks — SURFACES §2b.
 *
 * These two endpoints answer the two questions webhook ingest generates:
 * "did my form's submission arrive?" (activity) and "would it have triggered a
 * call?" (dry-run test). The dry-run consults the compliance gate without acting
 * on it — see apps/api/ingest/routes.py `test_webhook` for why that is not a
 * gate bypass.
 *
 * The ACTIVITY shapes are aliased from the generated schema. The DRY-RUN shapes
 * below still are not: `POST /v1/lead-sources/{id}/test` returns a plain dict, so
 * there is nothing generated to alias yet — swap them the day it grows a response
 * model, the way the activity types just were.
 */

import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * One inbound source's rolled-up delivery record from the durable inbox.
 *
 * Two things the hand-written interface this replaces got wrong, both now fixed by
 * the server's own model: `event` is NULLABLE (a vendor that posts without an event
 * name is a delivery we still record, and the old type made it unrepresentable), and
 * `first_at` / `last_at` are NOT NULL — an inbox row cannot exist without the
 * timestamps that created and last touched it.
 *
 * `outcome` is the three words the SURFACES spec uses, not the internal inbox enum;
 * `deduplicated` counts vendor retries we absorbed without ringing the customer twice.
 */
export type IngestActivityItem = Schemas["IngestActivityItemOut"];

export type IngestActivity = Schemas["IngestActivityOut"];

/** One decision the real ingest path would have made, reported instead of acted on. */
export interface TestWebhookStep {
  step: string;
  ok: boolean;
  detail: string;
  /** Present on the compliance_gate step: which rule allowed/refused the dial. */
  rule?: string | null;
  /** Present on the field_mapping step: which configured fields the sample hit. */
  mapped_fields?: string[];
}

export interface TestWebhookResult {
  would_call: boolean;
  steps: TestWebhookStep[];
}

export function useIngestActivity(session: Session): UseQueryResult<IngestActivity> {
  return useQuery({
    queryKey: ["ingest-activity", session.orgSlug],
    queryFn: () => apiRequest<IngestActivity>(session, "/v1/lead-sources/activity"),
    // Deliveries land on the form vendor's schedule, and this screen is usually
    // open precisely because someone just submitted a test form and is waiting
    // to see it appear. 30s keeps that loop tight without hammering the inbox.
    refetchInterval: 30_000,
  });
}

export function useTestWebhook(session: Session) {
  return useMutation({
    // No cache invalidation on success: the dry-run writes nothing server-side
    // (no lead row, no inbox row), so there is nothing stale to refetch.
    mutationFn: ({ webhookId, payload }: { webhookId: string; payload: object }) =>
      apiRequest<TestWebhookResult>(session, `/v1/lead-sources/${webhookId}/test`, {
        method: "POST",
        body: { payload },
      }),
  });
}
