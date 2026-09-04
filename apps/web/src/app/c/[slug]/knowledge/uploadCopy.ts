/**
 * WHAT A DOCUMENT'S STATE MEANS, IN THE WORDS OF THE PERSON WHO UPLOADED IT.
 *
 * The API deliberately keeps two states apart and this module keeps them apart too, then
 * says the ONE sentence that follows from both together:
 *
 *   - `ingest_status` is the machinery — have the bytes been read, has the voice platform
 *     indexed them (`apps/api/kb/routes.py::UploadOut`);
 *   - `review_state` + `is_live` are whether a person has said yes and whether a caller
 *     hears it.
 *
 * A shop owner does not have those two questions. They have one: *is my agent using my
 * price list yet, and if not, what is it waiting for?* So every branch below answers that,
 * and none of them prints a state, a code or an enum — `tests/plainLanguageGuard.test.ts`
 * bans the wire vocabulary from this realm, and it would be the wrong thing to show even
 * if it did not: "conversion_unavailable" tells the reader nothing they can act on.
 *
 * ## The two orderings that are decisions rather than style
 *
 * 1. **`is_live` wins over everything.** It is the only fact the caller on the phone can
 *    verify, and the same rule the pasted-text badge has followed since FLOWS §7: approved
 *    is not live, and a row that IS live must not show an older status underneath it.
 * 2. **A failure outranks a review state.** A document we could not read is not "waiting
 *    for review" — nobody is going to review it — and telling a client to wait for us is
 *    how a broken upload sits untouched for a week.
 *
 * ## The state the wire cannot express on its own
 *
 * A photograph whose text has been read sits back down at `received` with
 * `text_provenance` set, because the next move belongs to a person
 * (`apps/workers/kb_ingest.py`, and `document_ocr.py` on why OCR is never auto-approved).
 * `received` alone therefore means two opposite things — "we have not started" and "we
 * have finished and are waiting for you" — and only the provenance separates them. That
 * is the one place this file reads two fields to answer one question.
 */

import type { KbUpload } from "@/lib/api/kb";

/** One state, as the client meets it. */
export interface UploadState {
  /** The badge. Three or four words. */
  label: string;
  /** The sentence under the row: what is happening, or what is needed from them. */
  meaning: string;
  /** Badge palette — semantic, matching the pasted-text badges above it. */
  tone: string;
  /** Is the machinery still moving? Drives the "working" affordance, not the polling. */
  working: boolean;
  /** Does this row need the client to read the extracted text and confirm it? */
  awaitingConfirmation: boolean;
}

const LIVE_TONE = "bg-brand-soft text-brand-strong";
const WAIT_TONE = "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300";
const WORK_TONE = "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300";
const STOP_TONE = "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300";
const QUIET_TONE = "bg-black/5 text-ink-muted dark:bg-white/10";

/** Is this row's text something a model read off a photograph, rather than parsed out? */
export function isMachineRead(upload: KbUpload): boolean {
  return upload.text_provenance === "ocr";
}

/**
 * Has the text been extracted and left for a person to confirm?
 *
 * See the module header: `received` plus a provenance is the resting state of a
 * photograph nobody has confirmed yet.
 */
export function awaitsConfirmation(upload: KbUpload): boolean {
  return (
    upload.ingest_status === "received" &&
    Boolean(upload.text_provenance) &&
    upload.review_state === "pending_approval"
  );
}

export function uploadState(upload: KbUpload): UploadState {
  const isLink = upload.source_kind === "url";
  const thing = isLink ? "page" : "file";

  if (upload.is_live) {
    return {
      label: "In use",
      meaning: "Your agent is using this now, on every call.",
      tone: LIVE_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  // A refusal, ahead of any review state: nobody is waiting to review a document that
  // could not be read, and the client is the only person who can fix it.
  if (upload.ingest_status === "error") {
    return {
      label: "Could not be added",
      meaning: `We could not add this ${thing} to your agent.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "conversion_failed") {
    return {
      label: "Could not be read",
      meaning: `We could not read anything out of this ${thing}.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "conversion_unavailable") {
    return {
      label: "Cannot be read here",
      meaning:
        "We cannot read this kind of file on this account yet. Send the same content as a PDF, " +
        "or paste it in as text.",
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  if (upload.review_state === "rejected") {
    return {
      label: "Not accepted",
      meaning: `Your account manager did not accept this ${thing}.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.review_state === "archived") {
    return {
      label: "Replaced",
      meaning: "A newer version of this took its place.",
      tone: QUIET_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  if (awaitsConfirmation(upload)) {
    return {
      label: "Check what we read",
      meaning: isMachineRead(upload)
        ? "We read the words off your photo. Read them through and confirm they are right — " +
          "then your agent can start using them."
        : "We have read this. Have a look and confirm it, and your agent can start using it.",
      tone: WAIT_TONE,
      working: false,
      awaitingConfirmation: true,
    };
  }

  if (upload.ingest_status === "received" || upload.ingest_status === "converting") {
    return {
      label: "Being read",
      meaning: isLink
        ? "We are reading the page. This usually takes a minute."
        : "We are reading your file. This usually takes a minute.",
      tone: WORK_TONE,
      working: true,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "processing") {
    return {
      label: "Going to your agent",
      meaning: "Your agent is being given this now. It takes a minute or two.",
      tone: WORK_TONE,
      working: true,
      awaitingConfirmation: false,
    };
  }

  // Read, indexed, and not live: somebody has to say yes. Which somebody depends on who
  // submitted it, and the row cannot know that — so the sentence names the wait, and the
  // panel above the list explains whose it is.
  if (upload.review_state === "approved") {
    return {
      label: "Approved, not in use yet",
      meaning: "This is approved. Your agent starts using it at the next publish.",
      tone: WORK_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  return {
    label: "Waiting for review",
    meaning: `Your account manager reads this ${thing} before your agent starts using it.`,
    tone: WAIT_TONE,
    working: false,
    awaitingConfirmation: false,
  };
}

/**
 * What a client may send, in the words a file picker uses.
 *
 * SAID BEFORE THEY CHOOSE, not after the API refuses: the accepted kinds are
 * `apps/api/kb/uploads._EXTENSION_KINDS` filtered by `SUPPORTED_UPLOAD_KINDS`, and a
 * client who picks a `.doc` gets a 422 whose remediation names the fix. Both halves are
 * worth having; only one of them is worth making them discover.
 */
export const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".txt",
  ".md",
  ".csv",
  ".xlsx",
  ".jpg",
  ".jpeg",
  ".png",
  ".heic",
  ".heif",
  ".webp",
  ".avif",
] as const;

/** The `accept` attribute, which is a HINT to the picker and never a check. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

/** The same list as a sentence, for the person rather than for the picker. */
export const ACCEPTED_KINDS_SENTENCE =
  "PDFs, Word documents, spreadsheets, plain text, and photos of a printed page.";

/** `apps/api/kb/uploads.MAX_UPLOAD_BYTES`, said the way the refusal says it. */
export const MAX_UPLOAD_MB = 20;

/** A byte count as a person reads it, so a 3.4 MB file does not render as 3565158. */
export function fileSize(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${bytes} bytes`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}
