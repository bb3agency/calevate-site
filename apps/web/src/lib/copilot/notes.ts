"use client";

/**
 * Pip's notes (D-936): what Pip noticed in the account on its own, read by the panel and by
 * the launcher's count. The server composes every line and every button; this module only
 * reads, marks and puts away.
 *
 * Live: `copilot_notes` is under the `assistant` topic (`apps/api/live/topics.py`), so a
 * detector run that opens a note tells this query to read again; the slow poll is the
 * fallback for a missed note, as everywhere else in the console.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest, type Session } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { livePoll } from "@/lib/live/liveStatus";

export type CopilotNote = components["schemas"]["CopilotNoteOut"];
export type CopilotNotes = components["schemas"]["CopilotNotesOut"];
export type NotesRealm = "client" | "admin";

/** The safety poll. The live topic does the real work. */
export const NOTES_POLL_MS = 5 * 60_000;
/** How many notes the panel shows before "Show N more". */
export const NOTES_SHOWN = 2;

export const notesKey = (realm: NotesRealm, org: string) => ["copilot-notes", realm, org] as const;

function base(realm: NotesRealm): string {
  return realm === "admin" ? "/v1/admin/copilot/notes" : "/v1/copilot/notes";
}

export function useCopilotNotes(session: Session, realm: NotesRealm, enabled = true) {
  return useQuery<CopilotNotes>({
    queryKey: notesKey(realm, session.orgSlug),
    queryFn: () => apiRequest<CopilotNotes>(session, base(realm)),
    refetchInterval: livePoll(NOTES_POLL_MS),
    // A view-as session is refused by the client route (`copilot:use`), so it never asks.
    enabled: enabled && !session.impersonateOrg,
    staleTime: 30_000,
  });
}

/** The launcher's number: Pip's own notes nobody has seen. Linked items are the bell's. */
export function launcherCount(data: CopilotNotes | undefined): number {
  return data?.unread ?? 0;
}

/** Seen, put away, pressed. Client realm only: the operator's notes are read live and
 *  store nothing to mark. */
export function useNoteActions(session: Session) {
  const client = useQueryClient();
  const key = notesKey("client", session.orgSlug);
  const refresh = () => void client.invalidateQueries({ queryKey: key });
  const post = (path: string) => apiRequest(session, path, { method: "POST" });

  const seen = useMutation({
    mutationFn: () => post("/v1/copilot/notes/seen"),
    onMutate: () => {
      client.setQueryData<CopilotNotes>(key, (old) =>
        old ? { notes: old.notes.map((n) => ({ ...n, unread: false })), unread: 0 } : old,
      );
    },
    onSettled: refresh,
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => post(`/v1/copilot/notes/${encodeURIComponent(id)}/dismiss`),
    // Optimistic: the line leaves at once; a refusal brings the list back on refetch.
    onMutate: (id) => {
      client.setQueryData<CopilotNotes>(key, (old) =>
        old ? { ...old, notes: old.notes.filter((n) => n.id !== id) } : old,
      );
    },
    onSettled: refresh,
  });
  const acted = useMutation({
    mutationFn: (id: string) => post(`/v1/copilot/notes/${encodeURIComponent(id)}/acted`),
  });
  return { seen, dismiss, acted };
}
