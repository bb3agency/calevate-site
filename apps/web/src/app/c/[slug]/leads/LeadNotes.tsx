"use client";

import { useId, useState, type KeyboardEvent } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { NOTE_MAX_CHARS, useAddNote, useEditNote, useRemoveNote, type TimelineNote } from "@/lib/api/leadNotes";
import { isImeComposing } from "@/lib/imeEnter";

/** Within this many characters of the limit, the box says how many are left. */
const NEAR_LIMIT = 200;

/** Ctrl/Cmd+Enter sends; a plain Enter is a new line, because a note is often two. */
function sendsOnKey(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
  return event.key === "Enter" && (event.metaKey || event.ctrlKey) && !isImeComposing(event);
}

function CharsLeft({ text }: { text: string }) {
  const left = NOTE_MAX_CHARS - text.length;
  if (left > NEAR_LIMIT) return null;
  return (
    <span className={`text-meta tabular-nums ${left < 0 ? "text-danger" : "text-ink-faint"}`}>
      {left < 0 ? `${-left} too many` : `${left} left`}
    </span>
  );
}

/**
 * THE NOTE BOX: a short note for the team, on a lead's page or from one of its calls.
 *
 * Kept on the server as the team's own words (`lead_notes`), shown on the lead's history with
 * who wrote it. From a call page it is filed under that call, and the history links back.
 */
export function NoteComposer({
  session,
  leadId,
  callId,
}: {
  session: Session;
  leadId: string;
  callId?: string;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const add = useAddNote(session);
  const adding = useActionFeedback(add, { errorTitle: "Could not save the note" });
  const write = useWriteAccess(session, "leads:write", "write a note");
  const trimmed = text.trim();
  const tooLong = text.length > NOTE_MAX_CHARS;

  const send = () => {
    if (!trimmed || tooLong || adding.status === "pending" || !write.allowed) return;
    add.mutate(
      { leadId, body: trimmed, callId },
      // Cleared only once the server kept it: a failed save must not lose what was typed.
      { onSuccess: () => setText("") },
    );
  };

  if (!write.allowed && write.reason) {
    return <p className="text-meta text-ink-muted">{write.reason}</p>;
  }

  return (
    <form
      noValidate
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <label htmlFor={`${id}-note`} className="sr-only">
        A note for your team
      </label>
      <textarea
        id={`${id}-note`}
        rows={2}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (sendsOnKey(event)) {
            event.preventDefault();
            send();
          }
        }}
        aria-invalid={tooLong || undefined}
        placeholder={callId ? "What should your team know about this call?" : "What should your team know?"}
        className={`${FIELD} mt-0 min-h-16 resize-y [overflow-wrap:anywhere]`}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CharsLeft text={text} />
        <ActionButton
          type="submit"
          variant="secondary-sm"
          status={adding.status}
          retryable={adding.retryable}
          successLabel="Saved"
          disabled={!trimmed || tooLong}
          className="ml-auto"
        >
          Add note
        </ActionButton>
      </div>
    </form>
  );
}

/**
 * One note's words on the lead's history, with Edit and Remove for its writer or the owner.
 *
 * An edit sends the version it read; a note somebody changed meanwhile is refused and the
 * history is re-read, so nobody overwrites words they never saw.
 */
export function NoteBody({
  session,
  leadId,
  callId,
  note,
}: {
  session: Session;
  leadId: string;
  callId?: string | null;
  note: TimelineNote;
}) {
  const me = useMe(session);
  const write = useWriteAccess(session, "leads:write", "change a note");
  const edit = useEditNote(session);
  const editing = useActionFeedback(edit, { errorTitle: "Could not change the note" });
  const remove = useRemoveNote(session);
  const removing = useActionFeedback(remove, { errorTitle: "Could not remove the note" });
  const [draft, setDraft] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const id = useId();

  const mine = me.data?.user_id != null && me.data.user_id === note.author_user_id;
  const mayChange = write.allowed && (mine || me.data?.role === "owner");

  const save = () => {
    const body = draft?.trim() ?? "";
    if (!body || body.length > NOTE_MAX_CHARS || editing.status === "pending") return;
    edit.mutate(
      { leadId, noteId: note.id, body, expectedVersion: note.version },
      { onSuccess: () => setDraft(null) },
    );
  };

  if (draft !== null) {
    return (
      <form
        noValidate
        className="mt-2 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <label htmlFor={`${id}-edit`} className="sr-only">
          Change this note
        </label>
        <textarea
          id={`${id}-edit`}
          rows={3}
          value={draft}
          // Focus follows the press that opened the editor.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDraft(null);
            else if (sendsOnKey(event)) {
              event.preventDefault();
              save();
            }
          }}
          aria-invalid={draft.length > NOTE_MAX_CHARS || undefined}
          className={`${FIELD} mt-0 min-h-16 resize-y [overflow-wrap:anywhere]`}
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            type="submit"
            variant="secondary-sm"
            status={editing.status}
            retryable={editing.retryable}
            successLabel="Saved"
            disabled={!draft.trim() || draft.length > NOTE_MAX_CHARS}
          >
            Save
          </ActionButton>
          <button type="button" className={TEXT_ACTION} onClick={() => setDraft(null)}>
            Cancel
          </button>
          <CharsLeft text={draft} />
        </div>
      </form>
    );
  }

  return (
    <div className="mt-1.5 space-y-1">
      <p className="whitespace-pre-line text-body text-ink [overflow-wrap:anywhere]">{note.body}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-faint">
        {note.edited_at && <span>Edited {formatIST(note.edited_at)}</span>}
        {mayChange && !confirming && (
          <>
            <button type="button" className={TEXT_ACTION} onClick={() => setDraft(note.body)}>
              Edit
            </button>
            <button type="button" className={TEXT_ACTION} onClick={() => setConfirming(true)}>
              Remove
            </button>
          </>
        )}
        {mayChange && confirming && (
          <span role="group" aria-label="Remove this note?" className="flex flex-wrap items-center gap-2">
            <span className="text-ink-muted">Remove this note?</span>
            <ActionButton
              variant="danger"
              className="min-h-8 px-2.5 text-meta"
              status={removing.status}
              retryable={removing.retryable}
              successLabel="Removed"
              onClick={() => removing.run({ leadId, noteId: note.id, callId })}
            >
              Remove
            </ActionButton>
            <button type="button" className={TEXT_ACTION} onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
