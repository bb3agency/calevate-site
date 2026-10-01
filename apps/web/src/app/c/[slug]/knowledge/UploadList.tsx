"use client";

import { useState } from "react";
import { CheckCircle2, FileText, Globe, ImageIcon, Trash2 } from "lucide-react";

import { RowMenu } from "@/components/console/rowMenu";
import { TaskSteps } from "@/components/interior/task-steps";
import {
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { useActAccess } from "@/lib/api/hooks";
import {
  useConfirmUpload,
  useDeleteUpload,
  useKbChunks,
  useKbUpload,
  useOriginalLink,
  type KbUpload,
} from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { awaitsConfirmation, fileSize, isMachineRead, uploadState, uploadSteps } from "./uploadCopy";

const KIND_ICONS = {
  url: Globe,
  image: ImageIcon,
} as const;

/** One file, photo or web page the account sent, watching itself while it moves. */
export function UploadRow({ upload, agentName }: { upload: KbUpload; agentName: string | null }) {
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

  const steps = uploadSteps(shown);
  const kind = shown.source_kind === "url" ? "Web page" : shown.source_kind === "image" ? "Photo" : "File";

  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="min-w-0 break-words text-sm font-medium text-ink">{shown.name}</span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${state.tone}`}
            >
              {shown.is_live && (
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-bright" />
              )}
              {state.label}
            </span>
          </div>
          <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-ink-faint">
            <span>{kind}</span>
            {size && <span className="tabular-nums">{size}</span>}
            {agentName && (
              <span title={agentName} className="truncate">
                {agentName}
              </span>
            )}
            {shown.change_detected_at && (
              <span className="whitespace-nowrap">
                Page changed {formatIST(shown.change_detected_at)}
              </span>
            )}
          </p>
          <p className="mt-1 text-xs text-ink-muted">{state.meaning}</p>

          {/* The SPECIFIC reason, when the server has one. It is written for a client
              (`kb/routes.py::UploadOut.ingest_detail`: "a sentence to show the client …
              never a key or a stack"), so it is shown as it stands. */}
          {shown.ingest_detail && (
            <p className="mt-1 break-words text-xs text-ink-muted">{shown.ingest_detail}</p>
          )}

          {/* Steps only while the row is MOVING, from the server's own ingest and review
              states — never a percentage nobody measured. */}
          {steps && (
            <TaskSteps
              steps={steps.steps}
              current={steps.current}
              label={`Progress of ${shown.name}`}
              className="mt-2 max-w-xs"
            />
          )}

          {needsReview && (
            <button
              type="button"
              onClick={() => setReviewing((open) => !open)}
              aria-expanded={reviewing}
              className={`${PRIMARY_BUTTON_SM} mt-2`}
            >
              {reviewing ? "Hide what we read" : "Read it and confirm"}
            </button>
          )}
        </div>
        <RowMenu
          label={shown.name}
          items={[
            /* A LINK HAS NOTHING TO DOWNLOAD, and the API says so by name, so the row
               offers the page itself. A file's address is FETCHED ON THE CLICK: it lasts
               five minutes, so one painted when the list loaded would be dead by the time
               anybody pressed it — and a dead link here reads as "your document is gone". */
            shown.source_kind === "url" && shown.source_url
              ? {
                  id: "open",
                  label: "Open the page",
                  onSelect: () => {
                    window.open(shown.source_url ?? "", "_blank", "noopener,noreferrer");
                  },
                }
              : {
                  id: "open",
                  label: original.isPending ? "Opening…" : "Open the file you sent",
                  disabled: original.isPending,
                  onSelect: () =>
                    original.mutate(shown.id, {
                      onSuccess: (answer) => window.open(answer.url, "_blank", "noopener,noreferrer"),
                    }),
                },
            { id: "remove", label: "Remove", tone: "danger", onSelect: () => setConfirmingRemoval(true) },
          ]}
        />
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
          <p>You can send it again later.</p>
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
  /**
   * THE ACT THIS SCREEN PERFORMS IS AN APPROVAL, and it is the one knowledge act a view-as
   * session may not do. `POST /v1/kb/uploads/{id}/confirm` publishes under the client's own
   * name, so it asks `may_self_approve` and then `assert_view_as_may(principal,
   * "kb.self_approve")` for an operator (`apps/api/kb/uploads.py:722`) — the ground being
   * that the record must show that WE approved it, from the operator console's queue.
   *
   * SUBMITTING is a different route and is NOT withheld (`kb/routes.py:266` takes an
   * operator's upload with `auto_approve=False`, i.e. into review), which is why the gate
   * is here on the button that publishes rather than on the form that adds.
   */
  const approve = useActAccess(
    session,
    "kb:write",
    "kb.self_approve",
    "publish what we read under this account's name",
  );
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
      <RestrictionNote reason={approve.reason} />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!approve.allowed || confirm.isPending}
          title={approve.reason ?? undefined}
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
