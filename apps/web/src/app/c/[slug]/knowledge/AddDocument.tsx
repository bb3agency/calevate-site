"use client";

import { useId, useState } from "react";
import { Link2 } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FileDrop } from "@/components/fileDrop";
import { FIELD_INLINE, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useAddLink, useUploadDocument } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import type { UploadProgress } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { READ_FILE_REQUEST } from "./TeachBox";
import {
  ACCEPT_ATTRIBUTE,
  LINK_NOTE,
  MAX_UPLOAD_MB,
  PDF_NOTE,
  READ_KINDS_SENTENCE,
} from "./uploadCopy";

/**
 * THE FILE HALF OF THE ADD AREA: a price list, a menu or a photo of one.
 *
 * Three things here are decisions, not layout:
 *
 * 1. **The control is the kit's `FileDrop`** (a label around a real, focusable file input).
 *    Only the SIZE is checked in the browser: the API refuses `.doc` with a remediation
 *    naming the fix (Save as .docx), which a generic refusal here would hide.
 * 2. **What reaches the agents is said before a file is chosen**, and a PDF is said apart
 *    (`PDF_NOTE`): its words are read for the owner and Pip, and whether the agents use
 *    them is the server's answer per item (`reaches_agents`, D-893 L8), so the note
 *    promises nothing the row may later deny.
 * 3. **Progress is real bytes, not a spinner.** 20 MB over a phone uplink is minutes of
 *    apparent silence, and a form that looks frozen gets pressed twice — the same price
 *    list arriving twice. `apiUpload` reports what has actually left the device.
 *
 * The new row lands in the list below, often off screen on a phone, so a toast says the
 * file arrived and what happens next.
 */
export function AddFile({ allowed }: { allowed: boolean }) {
  const session = useClientSession();
  const upload = useUploadDocument(session);
  // The refusal is drawn above the control (ProblemNotice), so no toast repeats it.
  useActionFeedback(upload, {
    errorDisplay: "inline",
    successToast: (sent) => `${sent.name} received`,
    successDescription: (sent) =>
      sent.source_kind === "pdf"
        ? "It is saved, and we're reading its words now. Its row says whether your agents use it."
        : "We're reading it now. You'll see it in the list below.",
  });

  const [progress, setProgress] = useState<UploadProgress | null>(null);
  /** The last file this panel accepted, so the row can say what it is sending. */
  const [sending, setSending] = useState<File | null>(null);
  const disabled = !allowed || upload.isPending;

  function send(file: File): void {
    if (disabled) return;
    setSending(file);
    setProgress({ loaded: 0, total: file.size });
    upload.mutate(
      { file, onProgress: setProgress },
      {
        // Cleared on BOTH outcomes: a bar left at 100% under a refusal is the screen
        // saying the file arrived, which is the opposite of what happened.
        onSettled: () => {
          setProgress(null);
          setSending(null);
        },
      },
    );
  }

  const percent =
    progress && progress.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null;

  return (
    <div className="space-y-4">
      <p className="text-body text-ink-muted [text-wrap:pretty]">
        {READ_KINDS_SENTENCE}
      </p>

      {upload.error && <ProblemNotice error={upload.error} />}

      <FileDrop
        label="Your file or photo"
        hint={`One at a time, up to ${MAX_UPLOAD_MB} MB.`}
        accept={ACCEPT_ATTRIBUTE}
        validate={sizeProblem}
        disabled={disabled}
        onFiles={([file]) => send(file)}
        sending={sending ? { file: sending, percent } : null}
      />

      <p className="text-meta text-ink-muted [text-wrap:pretty]">{PDF_NOTE}</p>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-4">
        <p className="text-meta text-ink-muted">
          Want to check the facts first? {ASSISTANT_NAME} can read a photo or file and sort it
          into facts you approve one by one.
        </p>
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} read a photo or file`}
          prompt={READ_FILE_REQUEST}
          disabled={!allowed}
        />
      </div>
    </div>
  );
}

/**
 * THE LINK HALF OF THE ADD AREA. A link is stored, its one page read and checked for
 * changes; whether the agents use its words is said on its row (`reaches_agents`, D-893
 * L8). So `LINK_NOTE` promises only the reading, and the button says "Save", not "Add to
 * your agents".
 */
export function AddLink({ allowed, reason }: { allowed: boolean; reason: string | null }) {
  const session = useClientSession();
  const link = useAddLink(session);
  const linkFeedback = useActionFeedback(link, {
    errorDisplay: "inline",
    successToast: "Link saved",
    successDescription: "Your agents can't read web pages yet. It is in the list below.",
  });
  const urlInputId = useId();
  const [url, setUrl] = useState("");
  // The house refusal: our sentence, in our surface, rather than Chrome's bubble in
  // whatever language Chrome is set to (`components/formValidation.tsx`).
  const valid = useFormValidation();

  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={valid.onSubmit(() => {
        if (!allowed || link.isPending) return;
        link.mutate({ url: url.trim() }, { onSuccess: () => setUrl("") });
      })}
    >
      <p className="text-body text-ink-muted [text-wrap:pretty]">{LINK_NOTE}</p>
      <div>
        <label htmlFor={urlInputId} className={FIELD_LABEL}>
          Web address
        </label>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1 basis-60">
            <Link2
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
            />
            <input
              {...valid.field("url", "Give us the full web address of the page.")}
              id={urlInputId}
              type="url"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              enterKeyHint="done"
              required
              value={url}
              disabled={!allowed || link.isPending}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://your-website.in/prices"
              className={`${FIELD_INLINE} w-full pl-8`}
            />
          </div>
          <ActionButton
            type="submit"
            variant="secondary"
            status={linkFeedback.status}
            pendingLabel="Saving…"
            successLabel="Saved"
            /* The empty-address rule is NOT repeated here: pressing answers in words,
               where a dead button answers with nothing. */
            disabled={!allowed}
            title={reason ?? undefined}
          >
            Save link
          </ActionButton>
        </div>
        {valid.error("url")}
      </div>
      {link.error && <ProblemNotice error={link.error} />}
    </form>
  );
}

/** The one rule the browser previews: the API's `MAX_UPLOAD_BYTES`, said its way. */
function sizeProblem(file: File): string | null {
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `That file is over ${MAX_UPLOAD_MB} MB. Split it into smaller documents, or send the price list on its own.`;
  }
  return null;
}
