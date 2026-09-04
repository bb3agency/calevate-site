"use client";

import { useId, useRef, useState } from "react";
import { Link2, Paperclip, Upload } from "lucide-react";

import {
  Card,
  FIELD_HINT,
  FIELD_INLINE,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
} from "@/components/ui";
import { useAddLink, useUploadDocument } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import type { UploadProgress } from "@/lib/api/client";

import { ACCEPTED_KINDS_SENTENCE, ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB, fileSize } from "./uploadCopy";

/**
 * THE DOOR FOR A DOCUMENT, A PHOTOGRAPH AND A LINK — the half of this screen the founder
 * found missing ("where is a client able to upload files or docs or links?").
 *
 * It sits BESIDE the typed-text form rather than replacing it. Typing a short answer is
 * still the fastest way to add one fact, and a clinic that wants to correct its closing
 * time should not have to produce a document to do it.
 *
 * ## Three things here are decisions, not layout
 *
 * 1. **The drop zone is a `<label>` around a real `<input type="file">`.** The input is
 *    `sr-only` — visually hidden, NOT `display:none` — so it keeps its place in the tab
 *    order and opens the picker on Enter or Space, and the label gives it a big visible
 *    target for a pointer. A `<div onDrop>` with a click handler is the shape that looks
 *    identical and is unreachable from a keyboard; the drag handlers here are an
 *    ADDITION to a working control, never the control itself.
 * 2. **The accepted kinds are said before a file is chosen.** The API refuses `.doc`
 *    with a remediation naming the fix, and that refusal is worth keeping — but making a
 *    person discover the list by being refused is a choice, and this is the other one.
 * 3. **Progress is real bytes, not a spinner.** 20 MB over a phone uplink is minutes of
 *    apparent silence, and a form that looks frozen gets pressed twice — which here means
 *    the same price list arriving twice and being reviewed twice. `apiUpload` reports what
 *    has actually left the device (`lib/api/client.ts`).
 */
export function AddDocument({
  agentId,
  agentName,
  allowed,
  reason,
}: {
  /** Which agent learns this. Empty while the agent list has not answered. */
  agentId: string;
  /** Named on the card when there is more than nothing to say. */
  agentName: string | null;
  allowed: boolean;
  reason: string | null;
}) {
  const session = useClientSession();
  const upload = useUploadDocument(session);
  const link = useAddLink(session);

  const fileInputId = useId();
  const urlInputId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [url, setUrl] = useState("");
  /** The last file this panel accepted, so the row can say what it is sending. */
  const [sending, setSending] = useState<File | null>(null);

  const disabled = !allowed || !agentId || upload.isPending;

  function send(file: File): void {
    if (disabled) return;
    setSending(file);
    setProgress({ loaded: 0, total: file.size });
    upload.mutate(
      { agentId, file, onProgress: setProgress },
      {
        // Cleared on BOTH outcomes: a bar left at 100% under a refusal is the screen
        // saying the file arrived, which is the opposite of what happened.
        onSettled: () => {
          setProgress(null);
          setSending(null);
          if (fileInput.current) fileInput.current.value = "";
        },
      },
    );
  }

  const percent =
    progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null;

  return (
    <Card title="Add a file or a web page">
      <div className="space-y-4">
        <p className="text-sm text-ink-muted">
          <span>
            Send us what you already have — a price list, a menu, a leaflet, or a photo of
            one. {ACCEPTED_KINDS_SENTENCE} Up to {MAX_UPLOAD_MB} MB each.
            {agentName ? ` Goes to ${agentName}.` : ""}
          </span>
        </p>

        {upload.error && <ProblemNotice error={upload.error} />}

        {/* The drop zone. `htmlFor` rather than a click handler on the box: the label IS
            the control's label, so a screen reader announces the sentence inside it when
            the input takes focus, and the pointer target is the whole box for free. */}
        <label
          htmlFor={fileInputId}
          onDragOver={(event) => {
            event.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            const dropped = event.dataTransfer.files[0];
            if (dropped) send(dropped);
          }}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-card border border-dashed px-4 py-6 text-center transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app ${
            dragging ? "border-brand bg-brand-soft" : "border-line bg-app"
          } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
        >
          <input
            ref={fileInput}
            id={fileInputId}
            type="file"
            className="sr-only"
            accept={ACCEPT_ATTRIBUTE}
            disabled={disabled}
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              if (chosen) send(chosen);
            }}
          />
          <Upload aria-hidden className="h-5 w-5 text-ink-faint" />
          <span className="text-sm font-medium text-ink">
            Choose a file, or drag one here
          </span>
          <span className="text-xs text-ink-muted">
            One at a time. We will tell you when your agent has it.
          </span>
        </label>

        {/* THE BAR, and the sentence beside it. `role="progressbar"` with the three ARIA
            values so a screen reader can follow it too; a bar with no accessible name is
            an unlabelled widget axe will fail, and a person listening gets nothing. */}
        {progress && (
          <div className="space-y-1">
            <p className="flex items-center gap-2 text-xs text-ink-muted">
              <Paperclip aria-hidden className="h-3.5 w-3.5 shrink-0" />
              <span>
                Sending {sending?.name ?? "your file"}
                {percent === null ? "…" : ` — ${percent}%`}
                {fileSize(sending?.size) ? ` of ${fileSize(sending?.size)}` : ""}
              </span>
            </p>
            <div
              role="progressbar"
              aria-label="Sending your file"
              aria-valuemin={0}
              aria-valuemax={100}
              // Absent while the browser cannot compute a total, which is what an
              // indeterminate progressbar is: a bar drawn against a guessed total lies.
              aria-valuenow={percent ?? undefined}
              className="h-1.5 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10"
            >
              <div
                className="h-full rounded-full bg-brand-strong transition-[width]"
                style={{ width: `${percent ?? 10}%` }}
              />
            </div>
          </div>
        )}

        <div className="border-t border-line pt-4">
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (disabled || !url.trim()) return;
              link.mutate(
                { agentId, url: url.trim() },
                { onSuccess: () => setUrl("") },
              );
            }}
          >
            <label htmlFor={urlInputId} className={FIELD_LABEL}>
              Or give us the address of a page
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-0 flex-1">
                <Link2
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                />
                <input
                  id={urlInputId}
                  type="url"
                  inputMode="url"
                  value={url}
                  disabled={!allowed || !agentId || link.isPending}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://your-website.in/prices"
                  className={`${FIELD_INLINE} w-full pl-8`}
                />
              </div>
              <button
                type="submit"
                disabled={!allowed || !agentId || link.isPending || url.trim() === ""}
                title={reason ?? undefined}
                className={PRIMARY_BUTTON}
              >
                {link.isPending ? "Adding…" : "Add page"}
              </button>
            </div>
            <span className={FIELD_HINT}>
              We read the page and check it again from time to time. If it changes, we ask
              you about the new version before your agent uses it.
            </span>
            {link.error && <ProblemNotice error={link.error} />}
          </form>
        </div>
      </div>
    </Card>
  );
}
