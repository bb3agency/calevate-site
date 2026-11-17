"use client";

/**
 * How the owner taught an agent to sound (`agents/voice_notes`): every call the agent makes
 * follows the active notes, from the next time each of its agents, campaigns and lines is
 * put live.
 *
 *   GET   /v1/agents/{aid}/voice-notes                 `agents:read`
 *   POST  /v1/agents/{aid}/voice-notes                 `agents:write`, audited
 *   POST  /v1/agents/{aid}/voice-notes/{nid}/retire    `agents:write`, audited
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

export type VoiceNote = components["schemas"]["VoiceNoteOut"];
export type VoiceNotes = components["schemas"]["VoiceNotesOut"];
export type VoiceNoteIn = components["schemas"]["VoiceNoteIn"];

export const voiceNotesKey = (org: string, agentId: string) => ["voice-notes", org, agentId] as const;

export function useVoiceNotes(session: Session, agentId: string) {
  return useQuery({
    queryKey: voiceNotesKey(session.orgSlug, agentId),
    queryFn: () => apiRequest<VoiceNotes>(session, `/v1/agents/${agentId}/voice-notes`),
    enabled: Boolean(agentId),
  });
}

export function useTeachVoiceNote(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: VoiceNoteIn) =>
      apiRequest<VoiceNote>(session, `/v1/agents/${agentId}/voice-notes`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: voiceNotesKey(session.orgSlug, agentId) }),
  });
}

export function useRetireVoiceNote(session: Session, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (noteId: string) =>
      apiRequest<void>(session, `/v1/agents/${agentId}/voice-notes/${noteId}/retire`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: voiceNotesKey(session.orgSlug, agentId) }),
  });
}
