"use client";

/**
 * Notes the team leaves on a lead or one of its calls (W7.2), and the console's Find (W7.4).
 *
 * A note's words travel in a request BODY and come back on the lead's history
 * (`LeadTimelineEventOut.note`) and on its call's page (`GET /v1/calls/{id}/notes`). Find is
 * a POST for the reason `/v1/leads/search` is: the term can be a phone number, and a query
 * string reaches access logs and browser history (hard rule 6).
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type LeadNote = Schemas["LeadNoteOut"];
export type CallNotes = Schemas["CallNotesOut"];
export type TimelineNote = Schemas["TimelineNoteOut"];
export type FindResult = Schemas["FindOut"];

/** The longest note the server keeps (`crm.models.LEAD_NOTE_MAX_CHARS`). */
export const NOTE_MAX_CHARS = 2000;

function invalidateNotes(client: ReturnType<typeof useQueryClient>, org: string, leadId: string, callId?: string | null) {
  void client.invalidateQueries({ queryKey: ["lead-timeline", org, leadId] });
  if (callId) void client.invalidateQueries({ queryKey: ["call-notes", org, callId] });
}

export function useCallNotes(session: Session, callId: string): UseQueryResult<CallNotes> {
  return useQuery({
    queryKey: ["call-notes", session.orgSlug, callId],
    queryFn: () => apiRequest<CallNotes>(session, `/v1/calls/${callId}/notes`),
    enabled: Boolean(callId),
  });
}

export function useAddNote(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, body, callId }: { leadId: string; body: string; callId?: string | null }) =>
      apiRequest<LeadNote>(session, `/v1/leads/${leadId}/notes`, {
        method: "POST",
        body: callId ? { body, call_id: callId } : { body },
      }),
    onSuccess: (note) => invalidateNotes(client, session.orgSlug, note.lead_id, note.call_id),
  });
}

export function useEditNote(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      leadId,
      noteId,
      body,
      expectedVersion,
    }: {
      leadId: string;
      noteId: string;
      body: string;
      expectedVersion: number;
    }) =>
      apiRequest<LeadNote>(session, `/v1/leads/${leadId}/notes/${noteId}`, {
        method: "PATCH",
        body: { body, expected_version: expectedVersion },
      }),
    onSuccess: (note) => invalidateNotes(client, session.orgSlug, note.lead_id, note.call_id),
    // A note changed meanwhile is refused with 409: re-read so the editor sees the new words.
    onError: (_error, { leadId }) => invalidateNotes(client, session.orgSlug, leadId),
  });
}

export function useRemoveNote(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ leadId, noteId }: { leadId: string; noteId: string; callId?: string | null }) =>
      apiRequest<void>(session, `/v1/leads/${leadId}/notes/${noteId}`, { method: "DELETE" }),
    onSuccess: (_none, { leadId, callId }) => invalidateNotes(client, session.orgSlug, leadId, callId),
  });
}

/** The Find box's answer for a settled term. Nothing is asked for an empty term. */
export function useFind(session: Session, term: string): UseQueryResult<FindResult> {
  return useQuery({
    // The term is in the key, which stays in memory; it is never put in a URL.
    queryKey: ["find", session.orgSlug, term],
    queryFn: () => apiRequest<FindResult>(session, "/v1/find", { method: "POST", body: { q: term } }),
    enabled: term.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}
