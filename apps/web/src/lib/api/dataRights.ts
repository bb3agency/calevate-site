"use client";

/**
 * DPDP data-principal rights — the client realm's half (SEC-COMP §4).
 *
 * Three endpoints, built and audited long before anything called them: a subject access
 * export, an erasure request, and the status read that eventually carries the proof
 * certificate. Until this module existed a client honouring a data principal's rights did
 * it by curl or by emailing us, which is not a workflow — it is an obligation with a
 * statutory clock running on it and no surface.
 *
 * Four API decisions this module carries through rather than smooths over:
 *
 * - **Both requests are POSTs, and the number lives in the BODY.** The identifier IS the
 *   personal data; a GET writes it into access logs, proxies, referrers and browser
 *   history (hard rule 6). The export is therefore a MUTATION in TanStack terms even
 *   though it reads — the same reasoning `dnc.useCheckDncNumber` gives — and the extra
 *   benefit is that the answer is never cached against a key made out of a phone number.
 * - **The status read is keyed by an opaque `request_id`**, never by the number, which is
 *   why it can be a `useQuery` at all.
 * - **A duplicate erasure is a 200 with `already_open: true`, not a 409.** The caller's
 *   intent is already satisfied, so the screen has to be able to say "one is already
 *   running" without reading the status line — hence the flag on the body.
 * - **The export response has NO response model on the server**, so the generated schema
 *   types it as `{ [key: string]: unknown }`. That type is taken from the generated
 *   `paths` table rather than hand-written here: an invented interface would be a wire
 *   shape nothing checks, on the one endpoint whose payload is a named human being's
 *   entire file. The consequence for the screen is stated where it bites — we can hand
 *   the document over, and we cannot state what is in it.
 */

import { useMutation, useQuery, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];

export type DeletionRequest = Schemas["DeletionRequestOut"];
export type DeletionRequestAccepted = Schemas["DeletionRequestAcceptedOut"];
export type ErasureProof = Schemas["ErasureProofOut"];
export type ErasureLimitation = Schemas["ErasureLimitationOut"];

/**
 * The subject access document, exactly as the generated client describes it.
 *
 * `subject_export` returns `dict[str, Any]` from FastAPI, so openapi-typescript can only
 * say "a JSON object". Aliased from `paths` rather than declared, so the day the endpoint
 * grows a response model this alias tightens by itself instead of quietly disagreeing
 * with the wire.
 */
export type SubjectExportDocument =
  paths["/v1/compliance/subject-export"]["post"]["responses"][200]["content"]["application/json"];

export const dataRightsKeys = {
  deletionRequest: (org: string, requestId: string) =>
    ["deletion-request", org, requestId] as const,
};

/** A queued erasure is executed by a worker; this is how often we ask whether it has. */
const ERASURE_POLL_MS = 15_000;

/**
 * Build the subject access document for one number.
 *
 * A mutation, not a query, for the reason in the module note: the number may not become
 * a cache key. `retry` is left at the provider default of off for mutations — this
 * request writes an `audit_log` row on the server (`export_routes.py`), so a silent
 * retry would forge a second disclosure record for one disclosure.
 */
export function useSubjectExport(session: Session) {
  return useMutation({
    mutationFn: (phone: string) =>
      apiRequest<SubjectExportDocument>(session, "/v1/compliance/subject-export", {
        method: "POST",
        body: { phone },
      }),
  });
}

/**
 * File an erasure request. Irreversible on the server, so idempotent on the wire.
 *
 * The `Idempotency-Key` is per attempt (`useCallLead`'s reasoning): a double-click must
 * not file two requests for one person. The server also deduplicates by open request, so
 * this is belt and braces on an action nobody can take back.
 */
export function useFileErasure(session: Session) {
  return useMutation({
    mutationFn: (phone: string) =>
      apiRequest<DeletionRequestAccepted>(session, "/v1/compliance/deletion-requests", {
        method: "POST",
        body: { phone },
        idempotencyKey: crypto.randomUUID(),
      }),
  });
}

/**
 * Has this erasure been executed, and what does the certificate say?
 *
 * Polls only while the answer can still change. A completed request is a durable
 * artifact — the proof does not move once written — so the interval stops rather than
 * asking a question with a settled answer forever.
 */
export function useDeletionRequest(
  session: Session,
  requestId: string,
): UseQueryResult<DeletionRequest> {
  return useQuery({
    queryKey: dataRightsKeys.deletionRequest(session.orgSlug, requestId),
    queryFn: () =>
      apiRequest<DeletionRequest>(session, `/v1/compliance/deletion-requests/${requestId}`),
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? ERASURE_POLL_MS : false,
    refetchOnWindowFocus: true,
  });
}

/**
 * A request id, as the client may type it back in.
 *
 * There is no list endpoint — a filed request is reachable only by its id — so the screen
 * lets someone paste one in to pick a request back up after closing the tab. Validated
 * here rather than at the API so a typo answers instantly instead of as a 422, and
 * because a malformed id in the URL is a request worth not making at all.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isRequestId(value: string): boolean {
  return UUID_RE.test(value.trim());
}

/**
 * Hand a JSON document to the browser as a file.
 *
 * The same blob dance `useExportLeads` performs, and for the same reason it cannot be an
 * `<a href>`: these documents come from authenticated POSTs, so there is no URL a
 * navigation could fetch. Kept here rather than in the screen so the two documents this
 * surface produces — the subject's file and the erasure certificate — are saved the same
 * way.
 */
export function downloadJson(payload: unknown, filename: string): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  // In the document and revoked a tick later: a detached anchor is a no-op in some
  // browsers, and revoking synchronously can cancel the save.
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
