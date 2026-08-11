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
 * Response shapes are defined locally rather than aliased from the generated
 * schema: the ingest routes return plain dicts today, so the generated types
 * for them are untyped `Record<string, never>`-ish blobs. When the API grows
 * typed response models, replace these with `components["schemas"][...]`.
 */

import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";

/** One inbound source's rolled-up delivery record from the durable inbox. */
export interface IngestActivityItem {
  source: string;
  event: string;
  /** The three words the SURFACES spec uses, not the internal inbox enum. */
  outcome: "accepted" | "rejected" | "processing";
  /** Vendor retries we absorbed without ringing the customer twice. */
  deduplicated: number;
  error: string | null;
  first_at: string | null;
  last_at: string | null;
}

export interface IngestActivity {
  items: IngestActivityItem[];
}

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
