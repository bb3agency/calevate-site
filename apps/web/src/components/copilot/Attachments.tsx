"use client";

import { FileText, Paperclip, RotateCw, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { NOTICE_BAR, NOTICE_BASE, QUIET_ICON_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { ApiProblem } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import {
  ACCEPT,
  AttachmentError,
  MAX_FILES,
  MAX_PICTURES,
  kindOf,
  markNoticeSeen,
  noticeSeen,
  prepareFile,
  removeUpload,
  splitMarker,
  uploadPrepared,
  type AttachmentKind,
} from "@/lib/copilot/attachments";
import type { SentAttachment, TurnAttachment } from "@/lib/copilot/useCopilotConversation";

/**
 * Attaching files to a question for Pip (D-781): the paperclip, the tray of chosen files,
 * the first-use notice, and the files shown in a sent question's bubble.
 *
 * ## The decisions
 *
 * - **A real `<input type="file">` behind a labelled button** (`fileDrop.tsx`'s rule), so
 *   Tab reaches it, Enter or Space opens the picker, and a phone offers its camera and its
 *   gallery. No `capture`: that would remove the gallery and the file browser.
 * - **Paste and drop add files too**, through the same checks as the picker: a drop skips
 *   `accept`, so nothing here trusts it.
 * - **Each file says what is happening to it** — getting ready, sending with a percentage,
 *   attached, or what went wrong with a Retry — beside the file, not in a banner. Ask waits
 *   until every file has finished; a person is never told a file went that did not.
 * - **The notice says the true thing once, in plain words** before the first file goes:
 *   the AI provider sees the whole file, and nobody checks it. It names no provider.
 */

export interface TrayItem {
  key: string;
  name: string;
  kind: AttachmentKind;
  status: "preparing" | "uploading" | "ready" | "failed";
  /** 0–100 while uploading, when the browser can measure it. */
  progress: number | null;
  thumb: string | null;
  id: string | null;
  error: string | null;
  /** Whether trying again could help: a dropped connection can, our own refusal cannot. */
  retryable: boolean;
  file: File;
}

let keys = 0;
const nextKey = () => `attachment-${(keys += 1)}`;

function sentence(error: unknown): string {
  if (error instanceof AttachmentError) return error.message;
  if (error instanceof ApiProblem) {
    return [error.message, error.remediation].filter(Boolean).join(" ");
  }
  return "The file couldn't be sent. Check your connection and try again.";
}

/** The tray's state and what it can do. One per panel. */
export function useAttachmentTray(session: Session, realm: "client" | "admin") {
  const [items, setItems] = useState<TrayItem[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState(false);
  const controllers = useRef(new Map<string, AbortController>());

  const patch = useCallback((key: string, change: Partial<TrayItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }, []);

  const send = useCallback(
    async (key: string, file: File) => {
      const controller = new AbortController();
      controllers.current.set(key, controller);
      try {
        patch(key, { status: "preparing", error: null, progress: null });
        const prepared = await prepareFile(file);
        if (controller.signal.aborted) return;
        patch(key, { status: "uploading", thumb: prepared.thumb, progress: 0 });
        const stored = await uploadPrepared(session, realm, prepared, {
          signal: controller.signal,
          onProgress: ({ loaded, total }) =>
            patch(key, { progress: total ? Math.min(99, Math.round((loaded / total) * 100)) : null }),
        });
        patch(key, { status: "ready", id: stored.id, progress: 100 });
      } catch (error) {
        if (controller.signal.aborted) return;
        const retryable =
          !(error instanceof AttachmentError) &&
          (!(error instanceof ApiProblem) || error.retryable || error.status === 0);
        patch(key, { status: "failed", error: sentence(error), progress: null, retryable });
      } finally {
        controllers.current.delete(key);
      }
    },
    [patch, realm, session],
  );

  const add = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      setProblem(null);
      const room = MAX_FILES - items.length;
      let pictures = items.filter((item) => item.kind === "picture").length;
      const taken: TrayItem[] = [];
      const refused: string[] = [];
      for (const file of files) {
        const kind = kindOf(file);
        if (taken.length >= room) {
          refused.push(`A message can carry up to ${MAX_FILES} files.`);
          break;
        }
        if (kind === "picture" && pictures >= MAX_PICTURES) {
          refused.push(`A message can carry up to ${MAX_PICTURES} pictures.`);
          continue;
        }
        if (kind === "picture") pictures += 1;
        taken.push({
          key: nextKey(),
          name: file.name,
          kind,
          status: "preparing",
          progress: null,
          thumb: null,
          id: null,
          error: null,
          retryable: false,
          file,
        });
      }
      if (refused.length > 0) {
        setProblem(`${refused[0]} Send this message, then attach the rest to the next one.`);
      }
      if (taken.length === 0) return;
      if (!noticeSeen()) setNotice(true);
      setItems((current) => [...current, ...taken]);
      for (const item of taken) void send(item.key, item.file);
    },
    [items, send],
  );

  const remove = useCallback(
    (key: string) => {
      const item = items.find((candidate) => candidate.key === key);
      controllers.current.get(key)?.abort();
      setItems((current) => current.filter((candidate) => candidate.key !== key));
      setProblem(null);
      // Deleted at once on the server too. If that request fails the file is still
      // removed when the conversation ends, so the person is not asked to do anything.
      if (item?.id) void removeUpload(session, realm, item.id).catch(() => undefined);
    },
    [items, realm, session],
  );

  const retry = useCallback(
    (key: string) => {
      const item = items.find((candidate) => candidate.key === key);
      if (item) void send(key, item.file);
    },
    [items, send],
  );

  /** The ready files, for the question being sent, and an empty tray after. */
  const take = useCallback((): SentAttachment[] => {
    const ready = items
      .filter((item) => item.status === "ready" && item.id !== null)
      .map((item) => ({ id: item.id as string, name: item.name, kind: item.kind, thumb: item.thumb }));
    setItems([]);
    setProblem(null);
    return ready;
  }, [items]);

  const dismissNotice = useCallback(() => {
    markNoticeSeen();
    setNotice(false);
  }, []);

  useEffect(
    () => () => {
      for (const controller of controllers.current.values()) controller.abort();
    },
    [],
  );

  const busy = items.some((item) => item.status === "preparing" || item.status === "uploading");
  const ready = items.filter((item) => item.status === "ready").length;
  return { items, problem, notice, busy, ready, add, remove, retry, take, dismissNotice };
}

/** The paperclip: a labelled button over a hidden file input. */
export function AttachButton({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  return (
    <>
      <input
        ref={input}
        id={id}
        type="file"
        multiple
        accept={ACCEPT}
        // `hidden`, not `sr-only`: the labelled button below is the control a person and a
        // screen reader reach, and it opens this input with `click()`.
        hidden
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          // Cleared so the same file can be picked again after a removal.
          event.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={disabled}
        aria-label="Attach files"
        title="Attach files: pictures, PDFs, text, CSV, Word, Excel or PowerPoint"
        className={QUIET_ICON_BUTTON}
      >
        <Paperclip aria-hidden className="h-4 w-4" />
      </button>
    </>
  );
}

/** The plain, first-use statement of what happens to a file. */
export function AttachmentNotice({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className={`${NOTICE_BASE} ${NOTICE_BAR.neutral} mb-2 text-meta`} role="note">
      <p>
        {ASSISTANT_NAME}&apos;s AI provider sees the whole file, including any phone numbers
        or names in it. Nobody checks files for you, so only attach what you&apos;re allowed
        to share.
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        Got it
      </button>
    </div>
  );
}

function statusLine(item: TrayItem): string {
  switch (item.status) {
    case "preparing":
      return "Getting ready…";
    case "uploading":
      return item.progress === null ? "Sending…" : `Sending ${item.progress}%`;
    case "ready":
      return "Attached";
    default:
      return item.error ?? "Couldn't attach";
  }
}

/** The chosen files, above the question box. */
export function AttachmentTray({
  items,
  problem,
  onRemove,
  onRetry,
}: {
  items: TrayItem[];
  problem: string | null;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
}) {
  if (items.length === 0 && problem === null) return null;
  return (
    <div className="mb-2 space-y-1.5">
      {items.length > 0 && (
        <ul aria-label="Attached files" className="flex flex-wrap gap-2">
          {items.map((item) => (
            <li
              key={item.key}
              className={`flex max-w-full items-center gap-2 rounded-md border py-1 pl-1 pr-1 text-meta ${
                item.status === "failed" ? "border-chart-danger" : "border-line"
              }`}
            >
              {item.thumb ? (
                // A data URL of the cleaned preview; nothing to optimise or fetch.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={item.thumb} alt="" className="h-9 w-9 shrink-0 rounded object-cover" />
              ) : (
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-ink/[0.05]">
                  <FileText aria-hidden className="h-4 w-4 text-ink-muted" />
                </span>
              )}
              <span className="min-w-0">
                <span className="block max-w-[10rem] truncate text-ink">{item.name}</span>
                <span
                  className={`block max-w-[14rem] text-xs ${item.status === "failed" ? "text-danger" : "text-ink-muted"}`}
                  aria-live="polite"
                >
                  {statusLine(item)}
                </span>
              </span>
              {item.status === "failed" && item.retryable && (
                <button
                  type="button"
                  onClick={() => onRetry(item.key)}
                  aria-label={`Try ${item.name} again`}
                  className={QUIET_ICON_BUTTON}
                >
                  <RotateCw aria-hidden className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={() => onRemove(item.key)}
                aria-label={`Remove ${item.name}`}
                className={QUIET_ICON_BUTTON}
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {problem !== null && (
        <p role="alert" className="text-xs text-danger">
          {problem}
        </p>
      )}
    </div>
  );
}

/** The files a sent question carried, in its bubble. A stored turn from another device
 *  or an earlier visit has only a count, because the server keeps no name. */
export function TurnAttachments({
  attachments,
  count,
}: {
  attachments: TurnAttachment[] | undefined;
  count: number;
}) {
  if (attachments && attachments.length > 0) {
    return (
      <ul aria-label="Files sent with this question" className="mb-1.5 flex flex-wrap justify-end gap-1.5">
        {attachments.map((file, index) => (
          <li key={`${file.name}-${index}`}>
            {file.thumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={file.thumb}
                alt={file.name}
                className="h-16 w-16 rounded-md border border-line object-cover"
              />
            ) : (
              <span className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-ink-muted">
                <FileText aria-hidden className="h-3.5 w-3.5" />
                <span className="max-w-[9rem] truncate">{file.name}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
    );
  }
  if (count === 0) return null;
  return (
    <p className="mb-1 flex items-center justify-end gap-1 text-xs text-ink-muted">
      <Paperclip aria-hidden className="h-3.5 w-3.5" />
      {count === 1 ? "1 file attached" : `${count} files attached`}
    </p>
  );
}

export { splitMarker };
