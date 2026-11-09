"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { NOTICE_BAR, NOTICE_BASE, QUIET_ICON_BUTTON, SECONDARY_BUTTON_SM, type NoticeTone } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { NOTES_SHOWN, useCopilotNotes, useNoteActions, type CopilotNote } from "@/lib/copilot/notes";

import { ReadFailedRow } from "./homeNotices";
import { HOME } from "./_ui/copy";

const TONE: Record<CopilotNote["tone"], NoticeTone> = {
  success: "ok",
  info: "neutral",
  warning: "warn",
  critical: "stop",
};

/**
 * WHAT PIP NOTICED (D-936), with the home screen's other notices: one line and one button
 * per note, and a way to put each away. It sits here rather than in Pip's panel (founder,
 * 9 Nov 2026) so the panel opens on one question, as a chat's home does.
 *
 * Only Pip's own notes. The server also repeats the needs-attention queue's counts and the
 * line healer's open incident in Pip's voice ("linked"); this screen already shows both, in
 * its next steps and its line notice, so they would be said twice.
 *
 * Two shown, the rest behind "Show N more". `open` goes to the screen the note names; `ask`
 * opens Pip with the words in its ask box for the person to send, never sending them.
 *
 * Showing the notes marks them seen, once. Nothing renders while loading: notes are extra,
 * and a skeleton for them would cost more than they are worth. A failed read gets one quiet
 * line with a retry, because rendering nothing would read exactly like "nothing noticed"
 * (BUILD-LOG §52).
 */
export function PipNotes({
  session,
  onOpen,
  onAsk,
}: {
  session: Session;
  onOpen: (destination: { route: string; screen: string; where: string }) => void;
  onAsk: (prompt: string) => void;
}) {
  const notes = useCopilotNotes(session);
  const actions = useNoteActions(session);
  const [expanded, setExpanded] = useState(false);
  const markedSeen = useRef(false);
  // Null until the read arrives: an unread count we never received marks nothing seen.
  const unread = notes.isSuccess ? notes.data.unread : null;
  const markSeen = actions.seen.mutate;

  useEffect(() => {
    if (markedSeen.current || !unread) return;
    markedSeen.current = true;
    markSeen();
  }, [unread, markSeen]);

  if (notes.isPending) return null;
  if (notes.isError) {
    return (
      <ReadFailedRow
        action={
          <button type="button" onClick={() => void notes.refetch()} className={`${SECONDARY_BUTTON_SM} shrink-0`}>
            {HOME.tryAgain}
          </button>
        }
      >
        Could not check what {ASSISTANT_NAME} noticed.
      </ReadFailedRow>
    );
  }
  const all = notes.data.notes.filter((n) => n.source === "pip");
  if (all.length === 0) return null;
  const shown = expanded ? all : all.slice(0, NOTES_SHOWN);
  const hidden = all.length - shown.length;

  function press(note: CopilotNote) {
    actions.acted.mutate(note.id);
    const { button } = note;
    if (button.kind === "ask" && button.prompt) onAsk(button.prompt);
    else if (button.kind === "open" && button.route && button.screen) {
      onOpen({ route: button.route, screen: button.screen, where: button.screen });
    }
  }

  return (
    <section aria-label={`${ASSISTANT_NAME} noticed`}>
      <ul className="space-y-2">
        {shown.map((note) => (
          <li
            key={note.id}
            data-testid="pip-note"
            className={`${NOTICE_BASE} ${NOTICE_BAR[TONE[note.tone]]} flex flex-wrap items-center gap-x-3 gap-y-1.5`}
          >
            <span className="min-w-0 flex-1 basis-48 text-body">{note.line}</span>
            <span className="flex shrink-0 items-center gap-1">
              <button type="button" onClick={() => press(note)} className={SECONDARY_BUTTON_SM}>
                {note.button.label}
              </button>
              {note.dismissible && (
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
