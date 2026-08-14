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
 * - **The list is the register, the detail read is the certificate.** `GET
 *   /v1/compliance/deletion-requests` returns hashes, statuses and timestamps for every
 *   request the account has filed — never a phone number, and never the proof. The proof
 *   is fetched per request by the panel that renders it, so opening the screen does not
 *   pull every certificate on the account across the wire.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type DeletionRequest = Schemas["DeletionRequestOut"];
export type DeletionRequestAccepted = Schemas["DeletionRequestAcceptedOut"];
export type ErasureProof = Schemas["ErasureProofOut"];
export type ErasureLimitation = Schemas["ErasureLimitationOut"];

/**
 * The subject access document, and one row of the erasure register.
 *
 * Both are the GENERATED types now (`Schemas[...]`), not hand-mirrored shapes: the
 * endpoints carry real response models, so `schema.d.ts` is the one description of the
 * wire and there is nothing here for it to drift against. That mattered most for the
 * export — it is the one payload in this product that is an entire named human being,
 * and until it had a model it was invisible to `check_redaction_exposure`, which
 * inspects response MODELS. A hand-written mirror would have re-created exactly that
 * blind spot in the client.
 *
 * What `DeletionRequestSummary` does NOT carry is the point of the endpoint: no phone
 * number, and no certificate.
 */
export type SubjectExportDocument = Schemas["SubjectExportOut"];

export type DeletionRequestSummary = Schemas["DeletionRequestSummaryOut"];

export const dataRightsKeys = {
  deletionRequests: (org: string) => ["deletion-requests", org] as const,
  deletionRequest: (org: string, requestId: string) =>
    ["deletion-request", org, requestId] as const,
};

/**
 * Mirrors `deletion.MAX_LIST`'s role at the caller: a CEILING, not a page size. The
 * endpoint clamps and offers no offset, so a response this long may be a truncation
 * rather than the whole register — and the screen has to be able to say which, on a
 * surface where "these are all the erasures you owe" is a statement with legal weight.
 */
export const DELETION_REQUEST_LIST_LIMIT = 100;

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
  const client = useQueryClient();
  return useMutation({
    mutationFn: (phone: string) =>
      apiRequest<DeletionRequestAccepted>(session, "/v1/compliance/deletion-requests", {
        method: "POST",
        body: { phone },
        idempotencyKey: crypto.randomUUID(),
      }),
    // The register is the screen's memory now, so a filed request has to appear in it —
    // including the deduplicated case, where the answer is a request that was already
    // there and may already have moved on.
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: dataRightsKeys.deletionRequests(session.orgSlug) }),
  });
}

/**
 * Every erasure request this account has filed.
 *
 * The register that makes a filed request survive closing the tab: before it existed the
 * screen kept ids in component state and said so on screen, which is a scratchpad, not a
 * record of an obligation with a statutory clock on it.
 *
 * Polled on the same interval as a pending request, and only while one IS pending: the
 * list is how the screen learns that a worker finished, and a settled register does not
 * change until somebody files something (which invalidates this key anyway).
 */
export function useDeletionRequests(
  session: Session,
): UseQueryResult<DeletionRequestSummary[]> {
  return useQuery({
    queryKey: dataRightsKeys.deletionRequests(session.orgSlug),
    queryFn: () =>
      apiRequest<DeletionRequestSummary[]>(
        session,
        `/v1/compliance/deletion-requests?limit=${DELETION_REQUEST_LIST_LIMIT}`,
      ),
    refetchInterval: (query) =>
      query.state.data?.some((request) => request.status === "pending")
        ? ERASURE_POLL_MS
        : false,
    refetchOnWindowFocus: true,
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

/*
 * `isRequestId` used to live here, validating a request id pasted back in by hand. It was
 * a workaround for the missing list endpoint — the only way to pick a request back up
 * after closing the tab — and it is deleted rather than kept beside the register, because
 * two ways to reach one request is where the drift starts.
 */

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
