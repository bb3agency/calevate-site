"use client";

import { useId, useState } from "react";
import { Link2 } from "lucide-react";

import { FileDrop } from "@/components/fileDrop";

import {
  FIELD_HINT,
  FIELD_INLINE,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useAddLink, useUploadDocument } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import type { UploadProgress } from "@/lib/api/client";

import { ACCEPTED_KINDS_SENTENCE, ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB } from "./uploadCopy";

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
 * 1. **The control is the kit's `FileDrop`** (a label around a real, focusable file
 *    input; see its header). Only the SIZE is checked in the browser: the API refuses
 *    `.doc` with a remediation naming the fix (Save as .docx), which a generic "that kind
 *    of file cannot be sent" here would hide.
 * 2. **The accepted kinds are said before a file is chosen**, in the paragraph above the
 *    control — making a person discover the list by being refused is the other choice.
 * 3. **Progress is real bytes, not a spinner.** 20 MB over a phone uplink is minutes of
 *    apparent silence, and a form that looks frozen gets pressed twice — which here means
 *    the same price list arriving twice and being reviewed twice. `apiUpload` reports what
 *    has actually left the device (`lib/api/client.ts`).
 */
export function AddDocument({
  allowed,
  reason,
}: {
  allowed: boolean;
  reason: string | null;
}) {
  const session = useClientSession();
  const upload = useUploadDocument(session);
  const link = useAddLink(session);

  const urlInputId = useId();
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [url, setUrl] = useState("");
  // The house refusal: our sentence, in our surface, rather than Chrome's bubble in
  // whatever language Chrome is set to (`components/formValidation.tsx`).
  const valid = useFormValidation();
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
    <div>
      <h3 className="text-sm font-semibold text-ink">Add a file or a web page</h3>
      <div className="mt-2 space-y-4">
        <p className="text-sm text-ink-muted">
          <span>
            Send us what you already have — a price list, a menu, a leaflet, or a photo of
            one. {ACCEPTED_KINDS_SENTENCE} Up to {MAX_UPLOAD_MB} MB each. Every one of
            your agents will use it.
          </span>
        </p>

        {upload.error && <ProblemNotice error={upload.error} />}

        <FileDrop
          label="Your document or photo"
          hint={`One at a time, up to ${MAX_UPLOAD_MB} MB.`}
          accept={ACCEPT_ATTRIBUTE}
          validate={sizeProblem}
          disabled={disabled}
          onFiles={([file]) => send(file)}
          sending={sending ? { file: sending, percent } : null}
        />

        <div className="border-t border-line pt-4">
          <form
            className="space-y-2"
            noValidate
            onSubmit={valid.onSubmit(() => {
              if (!allowed || link.isPending) return;
              link.mutate({ url: url.trim() }, { onSuccess: () => setUrl("") });
            })}
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
                  {...valid.field("url", "Give us the full web address of the page.")}
                  id={urlInputId}
                  type="url"
                  inputMode="url"
                  required
                  value={url}
                  disabled={!allowed || link.isPending}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://your-website.in/prices"
                  className={`${FIELD_INLINE} w-full pl-8`}
                />
              </div>
              <button
                type="submit"
                /* The empty-address rule is NOT repeated here: pressing answers in words,
                   where a dead button answers with nothing. */
                disabled={!allowed || link.isPending}
                title={reason ?? undefined}
                className={PRIMARY_BUTTON}
              >
                {link.isPending ? "Adding…" : "Add page"}
              </button>
            </div>
            {valid.error("url")}
            <span className={FIELD_HINT}>
              We read the page and check it again from time to time. If it changes, we ask
              you about the new version before your agents use it.
            </span>
            {link.error && <ProblemNotice error={link.error} />}
          </form>
        </div>
      </div>
    </div>
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
