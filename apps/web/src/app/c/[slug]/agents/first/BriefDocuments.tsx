"use client";

import { useRef, useState } from "react";
import { Check, FileText, LoaderCircle, RotateCcw, TriangleAlert, X } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FileDrop } from "@/components/fileDrop";
import { ProblemNotice } from "@/components/ui";
import { Why } from "@/components/why";
import type { UploadProgress } from "@/lib/api/client";
import { useAddDocument, useRemoveDocument, type FirstRun, type FirstRunDocument } from "@/lib/api/firstRun";
import { useClientSession } from "@/lib/api/session";
import { documentLine } from "@/lib/firstAgent";

import { sizeProblem } from "../../knowledge/AddDocument";
import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB, READ_KINDS_LINE } from "../../knowledge/uploadCopy";

/**
 * FILES BESIDE THE BRIEF (D-918): a price list, a menu or a brochure the owner already has.
 *
 * Each file is an ordinary knowledge upload (`useAddDocument` sends it to `POST
 * /v1/kb/uploads`, then records it on the first run), so the knowledge screen lists it like
 * any other and every agent uses it. Its words also go to the question and script writers,
 * with customers' numbers and emails removed first. Each row says where the file is: being
 * read, read (and whether the agents use it on calls), or not readable, with "Try another
 * file" in place.
 */
export function BriefDocuments({ run }: { run: FirstRun }) {
  const session = useClientSession();
  const add = useAddDocument(session);
  const remove = useRemoveDocument(session);
  // The progress bar and the row are the success; a refusal is drawn above the control.
  useActionFeedback(add, { errorDisplay: "inline" });
  useActionFeedback(remove, { errorDisplay: "inline" });
  const drop = useRef<HTMLDivElement>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [sending, setSending] = useState<File | null>(null);
  const full = run.documents_left <= 0;

  const send = (file: File) => {
    if (add.isPending || full) return;
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

  const tryAnother = (document: FirstRunDocument) =>
    remove.mutate(document.upload_id, {
      onSuccess: () => drop.current?.querySelector<HTMLInputElement>("input[type=file]")?.click(),
    });

  const percent =
    progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null;

  return (
    <div className="rounded-card border border-line p-4">
      <p className="text-heading text-ink">Or add a file</p>
      <p className="mt-0.5 text-meta text-ink-muted">
        {READ_KINDS_LINE} Up to {run.documents.length + run.documents_left}.
      </p>
      <Why>
        We read it to write your agent&apos;s script and questions. Customers&apos; numbers and emails are
        removed first. It also goes into Knowledge, so every agent can use it.
      </Why>

      {run.documents.length > 0 ? (
        <ul className="mt-3 divide-y divide-line rounded-md border border-line">
          {run.documents.map((document) => (
            <DocumentRow
              key={document.upload_id}
              document={document}
              busy={remove.isPending}
              onRemove={() => remove.mutate(document.upload_id)}
              onTryAnother={() => tryAnother(document)}
            />
          ))}
        </ul>
      ) : null}

      {add.error ? <ProblemNotice error={add.error} /> : null}
      {remove.error ? <ProblemNotice error={remove.error} /> : null}

      <div ref={drop} className="mt-3">
        {full ? (
          <p className="text-meta text-ink-muted">That&apos;s the most for now. Add more under Knowledge.</p>
        ) : (
          <FileDrop
            label="Your file or photo"
            hint={`One at a time, up to ${MAX_UPLOAD_MB} MB.`}
            accept={ACCEPT_ATTRIBUTE}
            validate={sizeProblem}
            disabled={add.isPending}
            onFiles={([file]) => send(file)}
            sending={sending ? { file: sending, percent } : null}
          />
        )}
      </div>
    </div>
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
          <button type="button" className={`${TEXT_ACTION} mt-1`} disabled={busy} onClick={onTryAnother}>
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            Try another file
          </button>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onRemove}
        disabled={busy}
        aria-label={`Don't use ${document.name}`}
        className="press grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
      >
        <X aria-hidden className="h-4 w-4" />
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
