"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { Check, FileText, LoaderCircle, Paperclip, RotateCcw, TriangleAlert, X } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FileDrop } from "@/components/fileDrop";
import { ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import { Why } from "@/components/why";
import type { UploadProgress } from "@/lib/api/client";
import { useAddDocument, useRemoveDocument, type FirstRun, type FirstRunDocument } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { documentLine } from "@/lib/firstAgent";

import { sizeProblem } from "../../knowledge/AddDocument";
import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB, READ_KINDS_LINE } from "../../knowledge/uploadCopy";

/** The drop box's id, for the button that opens it. */
export const BRIEF_FILE_DROP_ID = "first-run-file-drop";

/**
 * FILES BESIDE THE BRIEF (D-918): a price list, a menu or a brochure the owner already has.
 *
 * Each file is an ordinary knowledge upload (`useAddDocument` sends it to `POST
 * /v1/kb/uploads`, then records it on the first run), so the knowledge screen lists it like
 * any other and every agent uses it. Its words also go to the question and script writers,
 * with customers' numbers and emails removed first.
 *
 * On the first card it is split in three, so the card keeps one row of tools rather than a
 * standing drop box: "Add a file" in that row (`AddFileButton`) opens the kit's `FileDrop`
 * under it, and the files are listed under the box (`BriefDocumentList`). A file dropped
 * anywhere on the card is sent too (`onDrop`). `useBriefDocuments` is the one sender.
 */
export function useBriefDocuments(run: FirstRun, onBusy?: (busy: boolean) => void) {
  const session = useClientSession();
  const add = useAddDocument(session);
  const remove = useRemoveDocument(session);
  const busy = add.isPending || remove.isPending;
  useEffect(() => onBusy?.(busy), [busy, onBusy]);
  // The progress bar and the row are the success; a refusal is drawn under the list.
  useActionFeedback(add, { errorDisplay: "inline" });
  useActionFeedback(remove, { errorDisplay: "inline" });
  const zone = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [sending, setSending] = useState<File | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const full = run.documents_left <= 0;

  const send = (file: File) => {
    if (add.isPending || full) return;
    const problem = sizeProblem(file);
    setRefused(problem);
    if (problem) return;
    setSending(file);
    setProgress({ loaded: 0, total: file.size });
    add.mutate(
      { file, onProgress: setProgress },
      {
        onSettled: () => {
          setSending(null);
          setProgress(null);
        },
      },
    );
  };

  const percent =
    progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null;

  return {
    run,
    add,
    remove,
    zone,
    open,
    toggle: () => setOpen((was) => !was),
    full,
    sending,
    percent,
    refused,
    send,
    // The failed file comes off, and the picker opens in its place.
    tryAnother: (document: FirstRunDocument) =>
      remove.mutate(document.upload_id, {
        onSuccess: () => {
          setOpen(true);
          requestAnimationFrame(() => zone.current?.querySelector<HTMLInputElement>("input[type=file]")?.click());
        },
      }),
    onDrop: (event: DragEvent) => {
      const file = event.dataTransfer.files?.[0];
      if (!file) return;
      event.preventDefault();
      send(file);
    },
  };
}

export type BriefDocumentsState = ReturnType<typeof useBriefDocuments>;

/** "Add a file" in the card's tools. At the bound it says where more go instead. */
export function AddFileButton({ files }: { files: BriefDocumentsState }) {
  if (files.full) return <p className="text-meta text-ink-muted">That&apos;s the most for now. Add more under Knowledge.</p>;
  return (
    <button
      type="button"
      className={SECONDARY_BUTTON}
      aria-expanded={files.open || files.sending !== null}
      aria-controls={BRIEF_FILE_DROP_ID}
      onClick={files.toggle}
    >
      <Paperclip aria-hidden className="h-4 w-4" />
      Add a file
    </button>
  );
}

/** The kit's drop box, opened by "Add a file" and kept open while a file is sent. */
export function BriefFileDrop({ files }: { files: BriefDocumentsState }) {
  if (files.full || (!files.open && files.sending === null)) return null;
  return (
    <div ref={files.zone} id={BRIEF_FILE_DROP_ID}>
      <FileDrop
        compact
        label="Your file or photo"
        hint={`One at a time, up to ${MAX_UPLOAD_MB} MB.`}
        accept={ACCEPT_ATTRIBUTE}
        validate={sizeProblem}
        disabled={files.add.isPending}
        onFiles={([file]) => files.send(file)}
        sending={files.sending ? { file: files.sending, percent: files.percent } : null}
      />
    </div>
  );
}

/** The files added, each with where it is, and any refusal. */
export function BriefDocumentList({ files }: { files: BriefDocumentsState }) {
  const { run, add, remove, refused } = files;
  if (run.documents.length === 0 && !refused && !add.error && !remove.error) return null;
  return (
    <div className="space-y-2">
      {run.documents.length > 0 ? (
        <ul className="divide-y divide-line rounded-md border border-line bg-surface">
          {run.documents.map((document) => (
            <DocumentRow
              key={document.upload_id}
              document={document}
              busy={remove.isPending}
              onRemove={() => remove.mutate(document.upload_id)}
              onTryAnother={() => files.tryAnother(document)}
            />
          ))}
        </ul>
      ) : null}
      {refused ? (
        <p role="alert" className="text-meta text-ink">
          {refused}
        </p>
      ) : null}
      {add.error ? <ProblemNotice error={add.error} /> : null}
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
    </div>
  );
}


/** What a file may be, behind a tap beside the button. */
export function FilesWhy({ run }: { run: FirstRun }) {
  return (
    <Why inline label="Which files?">
      {READ_KINDS_LINE} Up to {run.documents.length + run.documents_left}, {MAX_UPLOAD_MB} MB each. We read it to write
      your agent&apos;s script and questions. Customers&apos; numbers and emails are removed first. It also goes into
      Knowledge, so every agent can use it.
    </Why>
  );
}

function DocumentRow({
  document,
  busy,
  onRemove,
  onTryAnother,
}: {
  document: FirstRunDocument;
  busy: boolean;
  onRemove: () => void;
  onTryAnother: () => void;
}) {
  const failed = document.state === "failed";
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <StateIcon state={document.state} />
      <div className="min-w-0 flex-1">
        <p className="break-words text-body text-ink">{document.name}</p>
        <p role={failed ? "alert" : "status"} className={`text-meta ${failed ? "text-ink" : "text-ink-muted"}`}>
          {documentLine(document)}
        </p>
        {failed && document.detail ? <Why label="Details">{document.detail}</Why> : null}
        {failed ? (
          <button
            type="button"
            className={`${TEXT_ACTION} mt-1 aria-disabled:cursor-progress`}
            aria-disabled={busy || undefined}
            onClick={() => (busy ? undefined : onTryAnother())}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            Try another file
          </button>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => (busy ? undefined : onRemove())}
        aria-disabled={busy || undefined}
        aria-label={`Remove ${document.name}`}
        className="press inline-flex min-h-8 shrink-0 items-center gap-1 rounded-md px-2 text-meta font-medium text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand aria-disabled:cursor-progress aria-disabled:text-ink-faint touch:min-h-11"
      >
        <X aria-hidden className="h-3.5 w-3.5" />
        Remove
      </button>
    </li>
  );
}

function StateIcon({ state }: { state: FirstRunDocument["state"] }) {
  if (state === "reading")
    return <LoaderCircle aria-hidden className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-ink-muted motion-reduce:animate-none" />;
  if (state === "failed") return <TriangleAlert aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-warn" />;
  return (
    <span aria-hidden className="relative mt-0.5 h-5 w-5 shrink-0">
      <FileText className="h-5 w-5 text-ink-muted" />
      <Check className="absolute -right-1 -bottom-1 h-3 w-3 rounded-full bg-surface text-brand-strong" strokeWidth={3} />
    </span>
  );
}
