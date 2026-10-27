"use client";

import { useState } from "react";
import { RotateCcw, Trash2, Type } from "lucide-react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { InlineEdit } from "@/components/arc/inline-edit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { StatusPill } from "@/components/console/statusPill";
import {
  ProblemNotice,
  Skeleton,
  formatCount,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  useKbChunks,
  useRemoveNote,
  useRenameNote,
  useRestoreNote,
  type KbNote,
} from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/** `apps/api/kb/store.MAX_NAME_CHARS`. */
const MAX_NAME = 120;

const STATE_COPY: Record<string, { label: string; tone: NoticeTone }> = {
  in_use: { label: "In use", tone: "ok" },
  in_review: { label: "In review", tone: "warn" },
  needs_attention: { label: "Not accepted", tone: "stop" },
  getting_ready: { label: "Approved, not in use yet", tone: "neutral" },
  removed: { label: "Removed", tone: "neutral" },
};

/**
 * NOTES THE OWNER TYPED, with the three things they can do to one: rename it, remove it
 * (versions are kept, so the toast offers Undo) and put a removed one back. The buttons call
 * `/v1/kb/notes/*`, the same `kb/store` functions Pip's `knowledge_rename` and
 * `knowledge_remove` call.
 *
 * Removed notes are folded under the list rather than mixed into it: they are not knowledge
 * any more, only something to put back.
 */
export function NotesList({
  notes,
  canWrite,
  query,
}: {
  notes: KbNote[];
  canWrite: boolean;
  /** The page's search; a removed note is matched by the same words. */
  query: (name: string) => boolean;
}) {
  const session = useClientSession();
  const [previewing, setPreviewing] = useState<string | null>(null);
  const chunks = useKbChunks(session, previewing);
  const live = notes.filter((note) => note.state !== "removed" && query(note.name));
  const removed = notes.filter((note) => note.state === "removed" && query(note.name));

  return (
    <div className="space-y-4">
      {live.length > 0 ? (
        <ul className="divide-y divide-line border-y border-line">
          {live.map((note) => (
            <NoteRow
              key={note.id}
              note={note}
              canWrite={canWrite}
              open={previewing === note.id}
              onToggle={() => setPreviewing(previewing === note.id ? null : note.id)}
              chunks={chunks}
            />
          ))}
        </ul>
      ) : (
        <p className="text-meta text-ink-muted">No notes in use. Removed ones are below.</p>
      )}
      {removed.length > 0 ? <RemovedNotes notes={removed} canWrite={canWrite} /> : null}
    </div>
  );
}

function NoteRow({
  note,
  canWrite,
  open,
  onToggle,
  chunks,
}: {
  note: KbNote;
  canWrite: boolean;
  open: boolean;
  onToggle: () => void;
  chunks: ReturnType<typeof useKbChunks>;
}) {
  const session = useClientSession();
  const [confirming, setConfirming] = useState(false);
  const rename = useRenameNote(session);
  const renameFeedback = useActionFeedback(rename, { errorDisplay: "inline" });
  const remove = useRemoveNote(session);
  const restore = useRestoreNote(session);
  useActionFeedback(restore, { successToast: `${note.name} is back` });
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: `Removed ${note.name}`,
    successDescription: "Your agents stop using it within a minute.",
    undo: (_data, noteId) => restore.mutate(noteId),
  });
  const state = lookup(STATE_COPY, note.state) ?? { label: note.state, tone: "neutral" as const };

  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <Type aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {/* The name is the Rename button: press it, type, Enter. */}
            {canWrite ? (
              <InlineEdit
                label="Note name"
                value={note.name}
                status={renameFeedback.status}
                onSave={(name) => rename.mutate({ noteId: note.id, name })}
                validate={(name) => (name.length < 2 ? "A name needs at least 2 characters." : null)}
                errorMessage={problemToast(rename.error, "That name did not save").description}
                maxLength={MAX_NAME}
                editLabel={() => "Rename note"}
                textClassName="text-sm font-medium"
                className="min-w-0 max-w-full"
              />
            ) : (
              <span className="text-sm font-medium text-ink [overflow-wrap:anywhere]">{note.name}</span>
            )}
            <StatusPill tone={state.tone}>{state.label}</StatusPill>
          </div>
          <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-ink-faint">
            <span>Note</span>
            <span className="tabular-nums">
              {formatCount(note.chunks)} {note.chunks === 1 ? "answer" : "answers"}
            </span>
            <span className="whitespace-nowrap">Changed {formatIST(note.changed_at)}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="press shrink-0 rounded-md px-2 py-1 text-xs font-medium text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {open ? "Hide" : "Preview"}
        </button>
        {canWrite ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={`Remove ${note.name}`}
            className="press inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-ink-muted hover:bg-danger/[0.08] hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
          >
            <Trash2 aria-hidden className="h-3.5 w-3.5" />
            <span className="max-sm:sr-only">Remove</span>
          </button>
        ) : null}
      </div>

      {open ? <Preview chunks={chunks} /> : null}

      {confirming ? (
        <ConfirmDialog
          title={`Remove ${note.name}?`}
          confirmLabel="Remove it"
          pendingLabel="Removing…"
          status={removeFeedback.status}
          successLabel="Removed"
          error={remove.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() => remove.mutate(note.id, { onSuccess: () => setConfirming(false) })}
        >
          <p>Your agents stop using this note. Callers who ask about it get whatever else you have taught them.</p>
          <p>We keep it, so you can put it back from Removed notes.</p>
        </ConfirmDialog>
      ) : null}
    </li>
  );
}

function Preview({ chunks }: { chunks: ReturnType<typeof useKbChunks> }) {
  return (
    <div className="mt-3 rounded-lg bg-surface-muted p-3 sm:ml-7">
      {chunks.isLoading ? (
        <Skeleton rows={2} />
      ) : chunks.error || !chunks.data ? (
        <ProblemNotice
          error={chunks.error ?? new Error("This preview could not be loaded.")}
          onRetry={() => void chunks.refetch()}
        />
      ) : chunks.data.length ? (
        <div className="space-y-2">
          {chunks.data.map((chunk) => (
            <p key={chunk.idx} className="break-words border-l-2 border-line pl-3 text-xs text-ink-muted">
              {chunk.content}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-xs text-ink-muted">There is nothing in this submission for the agent to say.</p>
      )}
    </div>
  );
}

function RemovedNotes({ notes, canWrite }: { notes: KbNote[]; canWrite: boolean }) {
  return (
    <details className="group rounded-lg border border-line">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-sm font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 [&::-webkit-details-marker]:hidden">
        <span className="flex items-baseline gap-1.5">
          <span>Removed notes</span>
          <span className="tabular-nums text-ink-faint">· {formatCount(notes.length)}</span>
        </span>
        <span aria-hidden className="text-xs text-ink-faint group-open:hidden">
          Show
        </span>
        <span aria-hidden className="hidden text-xs text-ink-faint group-open:inline">
          Hide
        </span>
      </summary>
      <ul className="divide-y divide-line border-t border-line">
        {notes.map((note) => (
          <RemovedRow key={note.id} note={note} canWrite={canWrite} />
        ))}
      </ul>
    </details>
  );
}

function RemovedRow({ note, canWrite }: { note: KbNote; canWrite: boolean }) {
  const session = useClientSession();
  const restore = useRestoreNote(session);
  const feedback = useActionFeedback(restore, {
    errorDisplay: "inline",
    successToast: `${note.name} is back`,
    successDescription: "Your agents use it again within a minute.",
  });
  return (
    <li className="px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <p className="break-words text-sm text-ink [overflow-wrap:anywhere]">{note.name}</p>
          <p className="text-xs text-ink-faint">Removed {formatIST(note.changed_at)}</p>
        </div>
        {canWrite && note.restorable ? (
          <ActionButton
            variant="secondary-sm"
            status={feedback.status}
            pendingLabel="Putting back…"
            successLabel="Back"
            onClick={() => restore.mutate(note.id)}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            Put back
          </ActionButton>
        ) : !note.restorable ? (
          <p className="text-xs text-ink-muted">Never went live, so there is nothing to put back.</p>
        ) : null}
      </div>
      {restore.error ? (
        <div className="mt-2">
          <ProblemNotice error={restore.error} />
        </div>
      ) : null}
    </li>
  );
}
