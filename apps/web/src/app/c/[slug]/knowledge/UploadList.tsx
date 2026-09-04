"use client";

import { useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  FileText,
  Globe,
  ImageIcon,
  Loader2,
  Trash2,
} from "lucide-react";

import {
  Card,
  EmptyState,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import {
  useConfirmUpload,
  useDeleteUpload,
  useKbChunks,
  useKbUpload,
  useKbUploads,
  useOriginalLink,
  type KbUpload,
} from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { awaitsConfirmation, fileSize, isMachineRead, uploadState } from "./uploadCopy";

/**
 * EVERY DOCUMENT AND WEB PAGE THIS ACCOUNT HAS SENT, each saying where it is.
 *
 * The list is read once and then left alone; each row that is still MOVING watches itself
 * (`useKbUpload`) and stops the moment it settles. That is the founder's "per-item live
 * status" without the shape it is usually built as — a whole list re-read on a tight timer
 * because one row in it might change.
 */
export function UploadList({ agentNames }: { agentNames: Record<string, string> }) {
  const session = useClientSession();
  const uploads = useKbUploads(session);

  if (uploads.isLoading) {
    return (
      <Card title="Files and web pages">
        <Skeleton rows={3} />
      </Card>
    );
  }
  // A failed read gets a refusal and NO list. "Nothing here yet" over a request that never
  // answered tells a client the price list they sent this morning was never received.
  if (uploads.error || !uploads.data) {
    return (
      <Card title="Files and web pages">
        <ProblemNotice
          error={uploads.error ?? new Error("We could not load what you have sent.")}
          onRetry={() => void uploads.refetch()}
        />
      </Card>
    );
  }

  return (
    <Card title="Files and web pages" bodyClassName="p-2">
      {uploads.data.length ? (
        <ul className="divide-y divide-line">
          {uploads.data.map((upload) => (
            <UploadRow
              key={upload.id}
              upload={upload}
              agentName={lookup(agentNames, upload.agent_id) ?? null}
            />
          ))}
        </ul>
      ) : (
        <EmptyState
          title="Nothing sent yet"
          hint="Send your price list, your menu or a photo of your printed rates — whatever callers ask about most."
        />
      )}
    </Card>
  );
}

const KIND_ICONS = {
  url: Globe,
  image: ImageIcon,
} as const;

function UploadRow({ upload, agentName }: { upload: KbUpload; agentName: string | null }) {
  const session = useClientSession();
  // The row's OWN poll while it is moving, and silence once it is not. `watch.data ?? upload`
  // rather than a manufactured empty: the list's own answer is a real fact about this row,
  // not a placeholder, so there is never a frame with nothing in it.
  const watch = useKbUpload(session, upload);
  const shown = watch.data ?? upload;
  const state = uploadState(shown);
  const remove = useDeleteUpload(session);
  const original = useOriginalLink(session);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const [reviewing, setReviewing] = useState(false);

  const Icon = lookup(KIND_ICONS, shown.source_kind) ?? FileText;
  const size = fileSize(shown.byte_size);
  const needsReview = awaitsConfirmation(shown);

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Icon aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
        <span className="min-w-0 break-words text-sm font-semibold text-ink">{shown.name}</span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${state.tone}`}
        >
          {state.working ? (
            <Loader2 aria-hidden className="h-3 w-3 animate-spin" />
          ) : shown.is_live ? (
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-bright" />
          ) : null}
          {state.label}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2 text-xs text-ink-faint">
          {size && <span className="tabular-nums">{size}</span>}
          {agentName && <span className="truncate">{agentName}</span>}
          {shown.change_detected_at && (
            <span className="whitespace-nowrap">
              Page changed {formatIST(shown.change_detected_at)}
            </span>
          )}
        </span>
      </div>

      <p className="mt-1 text-xs text-ink-muted">{state.meaning}</p>

      {/* The SPECIFIC reason, when the server has one. It is written for a client
          (`kb/routes.py::UploadOut.ingest_detail`: "a sentence to show the client … never
          a key or a stack"), so it is shown as it stands rather than paraphrased. */}
      {shown.ingest_detail && (
        <p className="mt-1 break-words rounded-md border border-line bg-app px-2 py-1.5 text-xs text-ink-muted">
          {shown.ingest_detail}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {needsReview && (
          <button
            type="button"
            onClick={() => setReviewing((open) => !open)}
            aria-expanded={reviewing}
            className={PRIMARY_BUTTON_SM}
          >
            {reviewing ? "Hide what we read" : "Read it and confirm"}
          </button>
        )}

        {/* A LINK HAS NOTHING TO DOWNLOAD, and the API says so by name rather than with an
            empty answer — so the row offers the page itself instead. */}
        {shown.source_kind === "url" && shown.source_url ? (
          <a
            href={shown.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className={SECONDARY_BUTTON_SM}
          >
            <ExternalLink aria-hidden className="h-3 w-3" />
            Open the page
          </a>
        ) : (
          <button
            type="button"
            disabled={original.isPending}
            /* FETCHED ON THE CLICK. The address lasts five minutes, so one painted when
               the list loaded is dead by the time anybody presses it — and a dead link
               here reads as "your document is gone". */
            onClick={() =>
              original.mutate(shown.id, {
                onSuccess: (answer) => window.open(answer.url, "_blank", "noopener,noreferrer"),
              })
            }
            className={SECONDARY_BUTTON_SM}
          >
            <ExternalLink aria-hidden className="h-3 w-3" />
            {original.isPending ? "Opening…" : "Open the file you sent"}
          </button>
        )}

        <button
          type="button"
          onClick={() => setConfirmingRemoval(true)}
          className={SECONDARY_BUTTON_SM}
        >
          <Trash2 aria-hidden className="h-3 w-3" />
          Remove
        </button>
      </div>

      {original.error && (
        <div className="mt-2">
          <ProblemNotice error={original.error} />
        </div>
      )}

      {reviewing && <ExtractedText upload={shown} onDone={() => setReviewing(false)} />}

      {confirmingRemoval && (
        <ConfirmDialog
          title={`Remove ${shown.name}?`}
          confirmLabel="Remove it"
          pendingLabel="Removing…"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => setConfirmingRemoval(false)}
          onConfirm={() => remove.mutate(shown.id, { onSuccess: () => setConfirmingRemoval(false) })}
        >
          <p>
            Your agent stops using this straight away, and we delete our copy of it. Callers
            who ask about it will get whatever else you have taught the agent.
          </p>
          <p>You can send it again later, and it goes through review again if you do.</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * WHAT WE MADE OF THEIR DOCUMENT, FOR THEM TO AGREE WITH OR THROW AWAY.
 *
 * This screen is the reason `POST /uploads/{id}/confirm` exists. A vision model returns no
 * confidence score, so nothing in the machinery can tell a good transcription from a
 * fluent one that says ₹260 where the menu says ₹280 (`apps/workers/document_ocr.py`) —
 * the only instrument that can is the person who owns the menu. So the text is shown, it
 * is LABELLED as a machine's reading of their document, and their agent says none of it
 * until they have agreed.
 *
 * The chunks are the same ones the pasted-text preview shows, from the same route: what is
 * on this screen is exactly what the agent is given, not a second rendering of it.
 */
function ExtractedText({ upload, onDone }: { upload: KbUpload; onDone: () => void }) {
  const session = useClientSession();
  const chunks = useKbChunks(session, upload.source_id);
  const confirm = useConfirmUpload(session);
  const discard = useDeleteUpload(session);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-line bg-app p-3">
      <p className="text-xs text-ink-muted">
        <span>
          {isMachineRead(upload)
            ? "This is what our computer read off your photo — it is not your own typing, so please check the numbers and the spellings before you say yes."
            : "This is the text we took out of what you sent. Check it before you say yes."}
        </span>
      </p>

      {chunks.isLoading ? (
        <Skeleton rows={3} />
      ) : chunks.error || !chunks.data ? (
        <ProblemNotice
          error={chunks.error ?? new Error("We could not show you what we read.")}
          onRetry={() => void chunks.refetch()}
        />
      ) : chunks.data.length ? (
        <div className="space-y-2">
          {chunks.data.map((chunk) => (
            <p
              key={chunk.idx}
              className="whitespace-pre-wrap break-words rounded-md border border-line bg-surface p-2 text-xs text-ink"
            >
              {chunk.content}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-xs text-ink-muted">
          There is nothing readable in this one. Remove it and send a clearer photo, or type
          the details in yourself.
        </p>
      )}

      {confirm.error && <ProblemNotice error={confirm.error} />}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={confirm.isPending}
          onClick={() => confirm.mutate(upload.id, { onSuccess: onDone })}
          className={PRIMARY_BUTTON_SM}
        >
          <CheckCircle2 aria-hidden className="h-3 w-3" />
          {confirm.isPending ? "Saving…" : "Yes, this is right"}
        </button>
        <button
          type="button"
          onClick={() => setConfirmingDiscard(true)}
          className={SECONDARY_BUTTON_SM}
        >
          <Trash2 aria-hidden className="h-3 w-3" />
          Throw this away
        </button>
      </div>

      {confirmingDiscard && (
        <ConfirmDialog
          title={`Throw away what we read from ${upload.name}?`}
          confirmLabel="Throw it away"
          pendingLabel="Removing…"
          pending={discard.isPending}
          error={discard.error}
          onCancel={() => setConfirmingDiscard(false)}
          onConfirm={() =>
            discard.mutate(upload.id, {
              onSuccess: () => {
                setConfirmingDiscard(false);
                onDone();
              },
            })
          }
        >
          <p>
            We delete this and the file it came from, and your agent never sees it. Nothing
            you have already taught your agent changes.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
