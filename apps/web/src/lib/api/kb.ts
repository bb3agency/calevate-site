"use client";

/**
 * Client-realm knowledge hooks.
 *
 * Only the submitting half lives in the client realm — approval and publish are admin
 * actions (D-22), which is why there is no `approve` mutation here and why the screen
 * says a submission is "in review" rather than showing a button that would 403.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, apiUpload, type Session, type UploadProgress } from "./client";
import { queryKeys } from "./hooks";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type KbSource = Schemas["SourceOut"];
export type KbChunk = Schemas["ChunkOut"];
export type KbSubmitResult = Schemas["SubmitOut"];

export function useKbSources(session: Session): UseQueryResult<KbSource[]> {
  return useQuery({
    queryKey: ["kb", session.orgSlug],
    queryFn: () => apiRequest<KbSource[]>(session, "/v1/kb/sources"),
    // Slower than the call surfaces: an approval is a human on our side, measured in
    // hours, not the two-minute post-call SLO.
    refetchInterval: 120_000,
  });
}

export function useKbChunks(session: Session, sourceId: string | null) {
  return useQuery({
    queryKey: ["kb-preview", session.orgSlug, sourceId],
    queryFn: () => apiRequest<KbChunk[]>(session, `/v1/kb/sources/${sourceId}/preview`),
    enabled: Boolean(sourceId),
  });
}

export function useSubmitKnowledge(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, name, body }: { agentId: string; name: string; body: string }) =>
      apiRequest<KbSubmitResult>(session, "/v1/kb/sources", {
        method: "POST",
        body: { agent_id: agentId, name, body, kind: "text" },
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] }),
  });
}

export type StaffCuration = Schemas["StaffCurationOut"];

/**
 * May this account's `staff` members curate knowledge — the owner's own switch.
 *
 * READ ON `org:read`, which every role holds, so a staff member sees WHY the form is
 * closed to them rather than only that it is. Writing it is `org:manage`, so the control
 * is rendered disabled for anyone but an owner (and for a view-as operator, D-22).
 */
export function useStaffCuration(session: Session): UseQueryResult<StaffCuration> {
  return useQuery({
    queryKey: ["kb-staff-curation", session.orgSlug],
    queryFn: () => apiRequest<StaffCuration>(session, "/v1/kb/staff-curation"),
  });
}

export function useSetStaffCuration(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      apiRequest<StaffCuration>(session, "/v1/kb/staff-curation", {
        method: "PUT",
        body: { staff_may_curate_knowledge: enabled },
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["kb-staff-curation", session.orgSlug] });
      // `/v1/me` reports the EFFECTIVE permission set and `kb:write` is now part of it for
      // an eligible staff member (apps/api/tenancy/routes.py::me), so flipping this switch
      // changes what `useWriteAccess` will say. Without this invalidation an owner who
      // turns it on watches nothing happen until the next reload — and, worse, a staff
      // member left on the screen keeps a disabled form the server would now accept.
      //
      // `queryKeys.me(...)` rather than the literal `["me", slug]`, for the reason the
      // `useAgents` note at the bottom of this file records: two spellings of one key that
      // happen to be equal today is exactly how an invalidation silently stops working.
      void client.invalidateQueries({ queryKey: queryKeys.me(session.orgSlug) });
    },
  });
}

/*
 * `useAgents` deliberately does NOT live here.
 *
 * It existed twice — once here and once in `agents.ts` — fetching the same
 * `/v1/agents` with two separately-written cache keys that happened to be equal
 * (`["agents", org]` vs `agentKeys.all(org)`). `publishing.ts` invalidates the literal
 * `["agents", slug]` after an Apply, so the knowledge and campaigns screens refreshed
 * only by that coincidence: change either spelling and two of the four callers would
 * have gone on showing a stale agent list with nothing to indicate it. Import it from
 * `@/lib/api/agents`, which owns the key registry.
 */

// --- Documents, photographs and links -------------------------------------------
//
// The half of this screen that did not exist: a client with a price list in a Word file
// had to retype it. `apps/api/kb/routes.py` is the contract; everything below is one hook
// per route plus the ONE piece of judgement that is ours — when to stop polling.

export type KbUpload = Schemas["UploadOut"];
export type KbUploadDownload = Schemas["DownloadOut"];

/**
 * Has the machinery finished with this item, whatever the answer was?
 *
 * THIS IS THE POLLING STOP CONDITION and it is not simply "did it reach `processed`". Two
 * of the states a row can rest in are neither terminal-looking nor moving:
 *
 * - **A refusal is rest.** `error`, `conversion_failed` and `conversion_unavailable` are
 *   over; nothing behind them will change the row, and re-asking every few seconds for the
 *   rest of the session is a request per client per tick that can never answer differently.
 * - **`received` WITH a provenance is rest, and this is the subtle one.** A photograph
 *   whose text has been read sits back down at `received` — `apps/workers/kb_ingest.py`
 *   marks it with `text_provenance` and returns "awaiting_review", because the next move
 *   belongs to a PERSON confirming what a model read (`document_ocr.py`: OCR is never
 *   auto-approved). The status alone cannot tell that apart from "uploaded a second ago
 *   and not yet looked at", which is why this reads both columns. Without it, every
 *   photograph awaiting confirmation would poll until the tab closed.
 */
export function uploadSettled(upload: KbUpload): boolean {
  if (["processed", "error", "conversion_failed", "conversion_unavailable"].includes(upload.ingest_status)) {
    return true;
  }
  return upload.ingest_status === "received" && upload.text_provenance !== null && upload.text_provenance !== undefined;
}

/** How often an UNSETTLED item asks again. One item, not the list — see `useKbUpload`. */
const UPLOAD_POLL_MS = 4_000;

export function useKbUploads(session: Session): UseQueryResult<KbUpload[]> {
  return useQuery({
    queryKey: ["kb-uploads", session.orgSlug],
    queryFn: () => apiRequest<KbUpload[]>(session, "/v1/kb/uploads"),
    // The LIST is deliberately slow. What moves during an ingest is one row, and that row
    // watches itself (`useKbUpload`); re-reading every document a client has ever added on
    // a four-second timer to see one of them change is the shape this hook exists not to
    // be. Sixty seconds is here for the other reason a list changes — a colleague adding
    // something in another tab — and stays cheap.
    refetchInterval: 60_000,
  });
}

/**
 * ONE item, watched until it stops moving.
 *
 * `enabled` is the row's own judgement (`uploadSettled`), so a settled row makes no
 * request at all and a moving one asks every four seconds until it settles — at which
 * point `refetchInterval` returns false and the polling ENDS rather than idling forever at
 * a longer interval.
 *
 * The answer is written back into the list's cache so the rest of the screen (counts, the
 * live badge, what the delete button is deleting) is the same fact the row is showing.
 */
export function useKbUpload(session: Session, upload: KbUpload): UseQueryResult<KbUpload> {
  const client = useQueryClient();
  return useQuery({
    queryKey: ["kb-upload", session.orgSlug, upload.id],
    queryFn: async () => {
      const fresh = await apiRequest<KbUpload>(session, `/v1/kb/uploads/${upload.id}`);
      client.setQueryData<KbUpload[]>(["kb-uploads", session.orgSlug], (rows) =>
        rows?.map((row) => (row.id === fresh.id ? fresh : row)),
      );
      return fresh;
    },
    enabled: !uploadSettled(upload),
    refetchInterval: (query) => (query.state.data && uploadSettled(query.state.data) ? false : UPLOAD_POLL_MS),
  });
}

/** Everything an upload invalidates: its own list, and the sources list it also appears in. */
function invalidateKnowledge(client: ReturnType<typeof useQueryClient>, session: Session): void {
  void client.invalidateQueries({ queryKey: ["kb-uploads", session.orgSlug] });
  void client.invalidateQueries({ queryKey: ["kb", session.orgSlug] });
}

export function useUploadDocument(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      file,
      onProgress,
    }: {
      agentId: string;
      file: File;
      onProgress?: (progress: UploadProgress) => void;
    }) => {
      const form = new FormData();
      form.set("agent_id", agentId);
      form.set("file", file);
      return apiUpload<KbUpload>(session, "/v1/kb/uploads", form, { onProgress });
    },
    onSuccess: () => invalidateKnowledge(client, session),
  });
}

export function useAddLink(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, url }: { agentId: string; url: string }) =>
      apiRequest<KbUpload>(session, "/v1/kb/links", {
        method: "POST",
        body: { agent_id: agentId, url },
      }),
    onSuccess: () => invalidateKnowledge(client, session),
  });
}

/**
 * The owner's own approve-and-publish, after they have read what we made of their document.
 *
 * 409 `kb_upload_not_ready` is a real answer here and not a defect: the text is still being
 * read. It reaches the screen as an `ApiProblem` with the server's own remediation on it.
 */
export function useConfirmUpload(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      apiRequest<KbUpload>(session, `/v1/kb/uploads/${uploadId}/confirm`, { method: "POST" }),
    onSuccess: () => invalidateKnowledge(client, session),
  });
}

export function useDeleteUpload(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (uploadId: string) =>
      apiRequest<void>(session, `/v1/kb/uploads/${uploadId}`, { method: "DELETE" }),
    onSuccess: () => invalidateKnowledge(client, session),
  });
}

/**
 * A five-minute link to the client's own file — FETCHED ON THE CLICK, never rendered.
 *
 * A mutation rather than a query on purpose. The URL expires in `expires_in_s` (300s,
 * `apps/workers/storage.PRESIGN_TTL_S`), so an href painted when the list loaded is a dead
 * link by the time anybody presses it — and a dead link on the review step reads as "the
 * document is gone", which is the one thing it must not say.
 */
export function useOriginalLink(session: Session) {
  return useMutation({
    mutationFn: (uploadId: string) =>
      apiRequest<KbUploadDownload>(session, `/v1/kb/uploads/${uploadId}/original`),
  });
}
