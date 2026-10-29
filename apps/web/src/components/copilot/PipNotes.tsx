"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { NOTICE_BAR, NOTICE_BASE, QUIET_ICON_BUTTON, SECONDARY_BUTTON_SM, type NoticeTone } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  NOTES_SHOWN,
  useCopilotNotes,
  useNoteActions,
  type CopilotNote,
  type NotesRealm,
} from "@/lib/copilot/notes";

const TONE: Record<CopilotNote["tone"], NoticeTone> = {
  success: "ok",
  info: "neutral",
  warning: "warn",
  critical: "stop",
};

/**
 * WHAT PIP NOTICED (D-936), at the top of the panel: one line and one button per note, and a
 * way to put Pip's own notes away. Linked items (another screen's, said in Pip's voice) have
 * no dismiss: they leave when that screen's item does.
 *
 * Two shown, the rest behind "Show N more", so the ask box keeps the panel on a phone. The
 * button does what it says without a second step: `open` moves to the screen through the
 * dock (which checks the route against the sidebar and announces the move); `ask` puts the
 * words in the ask box for the person to send, never sending them itself.
 *
 * Opening the panel marks the notes seen, once, which is what takes the launcher's count
 * down. Nothing renders while loading: notes are extra, and a skeleton above the
 * conversation would cost more than the notes are worth. A failed read gets one quiet line
 * with a retry, because rendering nothing would read exactly like "nothing noticed"
 * (BUILD-LOG §52).
 */
export function PipNotes({
  session,
  realm,
  onOpen,
  onAsk,
}: {
  session: Session;
  realm: NotesRealm;
  /** Absent when this panel cannot move anybody; `open` buttons are then not offered. */
  onOpen?: (destination: { route: string; screen: string; where: string }) => void;
  onAsk: (prompt: string) => void;
}) {
  const notes = useCopilotNotes(session, realm);
  const actions = useNoteActions(session);
  const [expanded, setExpanded] = useState(false);
  const markedSeen = useRef(false);
  // Null until the read arrives: an unread count we never received marks nothing seen.
  const unread = notes.isSuccess ? notes.data.unread : null;
  const markSeen = actions.seen.mutate;

  useEffect(() => {
    if (realm !== "client" || markedSeen.current || !unread) return;
    markedSeen.current = true;
    markSeen();
  }, [realm, unread, markSeen]);

  if (notes.isPending) return null;
  if (notes.isError) {
    return (
      <p
        role="alert"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-4 py-2 text-meta text-ink-muted"
      >
        Could not check what {ASSISTANT_NAME} noticed.
        <button type="button" onClick={() => void notes.refetch()} className={SECONDARY_BUTTON_SM}>
          Try again
        </button>
      </p>
    );
  }
  const all = notes.data.notes.filter((n) => n.button.kind === "ask" || onOpen !== undefined);
  if (all.length === 0) return null;
  const shown = expanded ? all : all.slice(0, NOTES_SHOWN);
  const hidden = all.length - shown.length;

  function press(note: CopilotNote) {
    if (realm === "client" && note.source === "pip") actions.acted.mutate(note.id);
    const { button } = note;
    if (button.kind === "ask" && button.prompt) onAsk(button.prompt);
    else if (button.kind === "open" && button.route && button.screen && onOpen) {
      onOpen({ route: button.route, screen: button.screen, where: button.screen });
    }
  }

  return (
    <section aria-label={`${ASSISTANT_NAME} noticed`} className="border-b border-line px-4 py-3">
      <ul className="space-y-2">
        {shown.map((note) => (
          <li
            key={note.id}
            data-testid="pip-note"
            className={`${NOTICE_BASE} ${NOTICE_BAR[TONE[note.tone]]} flex flex-wrap items-center gap-x-3 gap-y-1.5`}
          >
            <span className="min-w-0 flex-1 basis-48 text-meta">{note.line}</span>
            <span className="flex shrink-0 items-center gap-1">
              <button type="button" onClick={() => press(note)} className={SECONDARY_BUTTON_SM}>
                {note.button.label}
              </button>
              {note.dismissible && realm === "client" && (
                <button
                  type="button"
                  onClick={() => actions.dismiss.mutate(note.id)}
                  aria-label={`Dismiss: ${note.line}`}
                  title="Dismiss"
                  className={QUIET_ICON_BUTTON}
                >
                  <X aria-hidden className="h-4 w-4" />
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {(hidden > 0 || expanded) && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
          className="mt-2 rounded-md px-1 text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {expanded ? "Show fewer" : `Show ${hidden} more`}
        </button>
      )}
    </section>
  );
}
