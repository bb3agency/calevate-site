"use client";

import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useCallNotes } from "@/lib/api/leadNotes";

import { NoteComposer } from "../../leads/LeadNotes";

/**
 * Notes the team wrote from this call (W7.2), and the box to add one. Each note also lands on
 * the person's history with a link back here. A call with no person on file has nowhere to
 * keep a note, so the card is not drawn.
 */
export function CallNotesCard({
  session,
  callId,
  leadId,
}: {
  session: Session;
  callId: string;
  leadId: string | null | undefined;
}) {
  const notes = useCallNotes(session, leadId ? callId : "");
  if (!leadId) return null;
  const items = notes.data?.items ?? [];
  return (
    <Section title="Team notes">
      <div className="space-y-3">
        {notes.error ? <ProblemNotice error={notes.error} onRetry={() => void notes.refetch()} /> : null}
        {notes.isLoading ? (
          <Skeleton rows={2} label="Loading the notes" />
        ) : items.length > 0 ? (
          <ul className="space-y-3 border-y border-line py-3">
            {items.map((note) => (
              <li key={note.id} className="space-y-0.5">
                <p className="whitespace-pre-line text-body text-ink [overflow-wrap:anywhere]">{note.body}</p>
                <p className="text-meta text-ink-faint">
                  {note.author_name ?? "A colleague"} · {formatIST(note.created_at)}
                  {note.edited_at ? " · edited" : ""}
                </p>
              </li>
            ))}
            {notes.data && notes.data.total > items.length && (
              <li className="text-meta text-ink-muted">The rest are on the person&rsquo;s page.</li>
            )}
          </ul>
        ) : null}
        <NoteComposer session={session} leadId={leadId} callId={callId} />
      </div>
    </Section>
  );
}
