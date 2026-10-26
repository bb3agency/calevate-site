"use client";

import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Drawer } from "@/components/console/drawer";
import { StatusPill } from "@/components/console/statusPill";
import { FileDrop } from "@/components/fileDrop";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useKbUploadText,
  useRenameUpload,
  useRereadUpload,
  useUploadDocument,
  type KbUpload,
} from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";

import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB, isReadCopy, reachesAgents, uploadState } from "./uploadCopy";

/**
 * THE READER (D-893 L8): the words we hold for one file, photo or link, opened over the
 * list it belongs to. What the owner reads here is what Pip reads with `knowledge_open` —
 * the same route (`GET /v1/kb/uploads/{id}/text`) — one PDF page or a few paragraphs at a
 * time, so a 60-page menu never arrives as one wall.
 *
 * It says plainly whether the agents use it, because for a PDF or a link that is a separate
 * fact from whether it is saved. The file's own words are never edited here: Rename changes
 * its name, Replace file sends a new version under the same name, Remove takes it away.
 */
export function ReaderDrawer({
  upload,
  onClose,
  onRemove,
}: {
  upload: KbUpload;
  onClose: () => void;
  /** Closes the reader and asks the row's own Remove question. */
  onRemove: () => void;
}) {
  const session = useClientSession();
  const [page, setPage] = useState(1);
  const words = useKbUploadText(session, upload.id, page);
  // The row watches itself while its words are read (`useKbUpload`); once that settles,
  // the reader shows the new words rather than the "still reading" it opened on.
  const { refetch } = words;
  const readState = upload.read_state;
  const [seenState, setSeenState] = useState(readState);
  useEffect(() => {
    if (readState === seenState) return;
    setSeenState(readState);
    void refetch();
  }, [readState, seenState, refetch]);
  const write = useWriteAccess(session, "kb:write", "change your knowledge");
  const [renaming, setRenaming] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const state = uploadState(upload);
  const reaches = reachesAgents(upload) && upload.is_live;
  const isLink = upload.source_kind === "url";

  return (
    <Drawer
      open
      onClose={onClose}
      title={upload.name}
      width="lg"
      initialFocus="container"
      description={
        <span className="flex flex-wrap items-center gap-2">
          <StatusPill tone={state.tone}>{state.label}</StatusPill>
          <span>{reaches ? "Your agents use this." : "Your agents don't use this yet."}</span>
        </span>
      }
      footer={
        write.allowed ? (
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setRenaming(true)}>
              Rename
            </button>
            {!isLink ? (
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setReplacing(true)}>
                Replace file
              </button>
            ) : null}
            {isReadCopy(upload) && upload.read_state !== "reading" ? <ReadAgain upload={upload} /> : null}
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={onRemove}>
              Remove
            </button>
          </div>
        ) : undefined
      }
    >
      <div className="space-y-4">
        <RestrictionNote reason={write.allowed ? null : write.reason} />
        <p className="text-meta text-ink-muted [text-wrap:pretty]">{state.meaning}</p>
        {renaming ? <RenameForm upload={upload} onDone={() => setRenaming(false)} /> : null}
        {replacing ? <ReplaceFile upload={upload} onDone={onClose} /> : null}

        {words.isLoading ? (
          <Skeleton rows={6} label={`Loading the words of ${upload.name}`} />
        ) : words.error || !words.data ? (
          <ProblemNotice
            error={words.error ?? new Error("We could not show you the words we hold for this.")}
            onRetry={() => void words.refetch()}
          />
        ) : (
          <>
            {words.data.note ? <p className="text-meta text-ink-muted">{words.data.note}</p> : null}
            {words.data.sections.length === 0 ? (
              <p className="text-body text-ink-muted">
                {upload.read_state === "reading"
                  ? "We are still reading this. The words appear here in a minute."
                  : "We hold no words for this yet."}
              </p>
            ) : (
              words.data.sections.map((section, index) => (
                <section key={`${words.data.page}-${index}`} aria-label={section.label || undefined}>
                  {section.label ? (
                    <h3 className="mb-1 text-meta font-medium text-ink-muted">{section.label}</h3>
                  ) : null}
                  <p className="whitespace-pre-wrap text-body text-ink [overflow-wrap:anywhere]">{section.content}</p>
                </section>
              ))
            )}
            {words.data.pages > 1 ? (
              <nav aria-label="Pages" className="flex items-center justify-between gap-2 border-t border-line pt-3">
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={words.data.page <= 1}
                  onClick={() => setPage(words.data.page - 1)}
                >
                  Previous
                </button>
                <span className="text-meta tabular-nums text-ink-muted">
                  {words.data.page} of {words.data.pages}
                </span>
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={words.data.page >= words.data.pages}
                  onClick={() => setPage(words.data.page + 1)}
                >
                  Next
                </button>
              </nav>
            ) : null}
          </>
        )}
      </div>
    </Drawer>
  );
}

function RenameForm({ upload, onDone }: { upload: KbUpload; onDone: () => void }) {
  const session = useClientSession();
  const [name, setName] = useState(upload.name);
  const rename = useRenameUpload(session);
  const feedback = useActionFeedback(rename, { errorDisplay: "inline", successToast: "Renamed" });
  const cleaned = name.trim();
  const valid = cleaned.length >= 2 && cleaned.length <= 120;
  return (
    <form
      className="space-y-2"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && cleaned !== upload.name && !rename.isPending) {
          rename.mutate({ uploadId: upload.id, name: cleaned }, { onSuccess: onDone });
        }
      }}
    >
      <label htmlFor={`rename-${upload.id}`} className={FIELD_LABEL}>
        New name
      </label>
      <input
        id={`rename-${upload.id}`}
        value={name}
        maxLength={120}
        onChange={(event) => setName(event.target.value)}
        className={FIELD}
      />
      {rename.error ? <ProblemNotice error={rename.error} /> : null}
      <div className="flex gap-2">
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={feedback.status}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={!valid || cleaned === upload.name}
        >
          Save name
        </ActionButton>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/**
 * A new file under the SAME name: the server makes it the next version of this item, and it
 * takes this one's place once it is read. The old version is kept as history.
 */
function ReplaceFile({ upload, onDone }: { upload: KbUpload; onDone: () => void }) {
  const session = useClientSession();
  const send = useUploadDocument(session);
  useActionFeedback(send, {
    errorDisplay: "inline",
    successToast: `We're reading the new ${upload.name}. It takes the old one's place once it's read.`,
  });
  const [percent, setPercent] = useState<number | null>(null);
  const [sending, setSending] = useState<File | null>(null);
  return (
    <div className="space-y-2">
      <FileDrop
        label="The new file"
        hint={`It replaces ${upload.name}. Up to ${MAX_UPLOAD_MB} MB.`}
        accept={ACCEPT_ATTRIBUTE}
        maxBytes={MAX_UPLOAD_MB * 1024 * 1024}
        disabled={send.isPending}
        sending={sending ? { file: sending, percent } : null}
        onFiles={([file]) => {
          if (!file) return;
          setSending(file);
          send.mutate(
            {
              file,
              name: upload.name,
              onProgress: (progress) =>
                setPercent(
                  progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null,
                ),
            },
            { onSuccess: onDone, onSettled: () => setSending(null) },
          );
        }}
      />
      {send.error ? <ProblemNotice error={send.error} /> : null}
    </div>
  );
}

function ReadAgain({ upload }: { upload: KbUpload }) {
  const session = useClientSession();
  const reread = useRereadUpload(session);
  const feedback = useActionFeedback(reread, {
    errorDisplay: "toast",
    successToast: `Reading ${upload.name} again`,
  });
  return (
    <ActionButton
      variant="secondary-sm"
      status={feedback.status}
      pendingLabel="Starting…"
      successLabel="Reading"
      onClick={() => feedback.run(upload.id)}
    >
      Read it again
    </ActionButton>
  );
}
