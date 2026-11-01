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
import type { NoticeTone } from "@/components/ui";

/** One state, as the client meets it. */
export interface UploadState {
  /** The badge. Three or four words. */
  label: string;
  /** The sentence under the row: what is happening, or what is needed from them. */
  meaning: string;
  /** Badge palette — semantic, matching the pasted-text badges above it. */
  tone: NoticeTone;
  /** Is the machinery still moving? Drives the "working" affordance, not the polling. */
  working: boolean;
  /** Does this row need the client to read the extracted text and confirm it? */
  awaitingConfirmation: boolean;
}

const LIVE_TONE: NoticeTone = "ok";
const WAIT_TONE: NoticeTone = "warn";
const WORK_TONE: NoticeTone = "neutral";
const STOP_TONE: NoticeTone = "stop";
const QUIET_TONE: NoticeTone = "neutral";

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

/**
 * WHETHER THE WORDS REACH THE AGENTS IS THE SERVER'S ANSWER, NOT THIS FILE'S (D-868).
 * Word, text, CSV, Excel, photos and PDFs are read into text and that text is what the
 * agents are sent; a PDF only once we have read its words (`reaches_agents`,
 * `apps/api/kb/service.upload_reaches_agents`). A link is sent as its address and read by
 * the agents' platform; a page it cannot read comes back as an `error` with the reason in
 * `ingest_detail`. Until the server says it reaches them, the row must not say "In use".
 */
const READ_COPY_KINDS: ReadonlySet<string> = new Set(["pdf", "url"]);

/** Does what this upload says reach the agents? The server's `reaches_agents`. */
export function reachesAgents(upload: Pick<KbUpload, "reaches_agents">): boolean {
  return upload.reaches_agents !== false;
}

/** Is this a PDF or a link, whose words we read into a copy? */
export function isReadCopy(upload: Pick<KbUpload, "source_kind">): boolean {
  return READ_COPY_KINDS.has(upload.source_kind);
}

/** A refusal the owner has to act on, which outranks every other state on the row. */
function isStopped(upload: KbUpload): boolean {
  return (
    upload.ingest_status === "error" ||
    upload.ingest_status === "conversion_failed" ||
    upload.ingest_status === "conversion_unavailable" ||
    upload.review_state === "rejected"
  );
}

export function uploadState(upload: KbUpload): UploadState {
  const isLink = upload.source_kind === "url";
  const thing = isLink ? "page" : "file";

  // A refusal comes first, whatever the kind and even on a live row: a page the agents'
  // platform could not read is not in use however it was published, and the reason it
  // gives ("the page may require a login") is the one thing the owner can act on.
  if (upload.ingest_status === "error") {
    return {
      label: isLink ? "Agents couldn't read it" : "Could not be added",
      meaning: upload.ingest_detail ?? `Couldn't add this ${thing}. Send it again.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  // A PDF's words, ahead of `is_live`: published, it reaches the agents only once they are
  // read, and "In use" would tell the owner callers are hearing their price list when they
  // are not.
  if (upload.source_kind === "pdf" && !isStopped(upload)) {
    if (upload.read_state === "reading") {
      return {
        label: "Being read",
        meaning: "Reading every page now. About a minute.",
        tone: WORK_TONE,
        working: true,
        awaitingConfirmation: false,
      };
    }
    if (upload.read_state === "failed") {
      return {
        label: "Couldn't read",
        meaning: upload.read_detail ?? "Couldn't read this file. It is still saved.",
        tone: STOP_TONE,
        working: false,
        awaitingConfirmation: false,
      };
    }
    if (upload.is_live && !reachesAgents(upload)) {
      return {
        label: "Not read yet",
        meaning: "Open it and tap Read it again.",
        tone: WAIT_TONE,
        working: false,
        awaitingConfirmation: false,
      };
    }
  }

  if (upload.is_live) {
    return {
      label: "In use",
      // A partial reading ("We read 18 of 20 pages", "2 pictures could not be read") is
      // said where the owner looks. Not a link's: its agents use the page the platform
      // fetched, whatever our own copy managed.
      meaning:
        (isLink ? null : upload.read_detail) ??
        (isLink ? "Your agents use this page on calls." : "Your agents use this on calls and in their scripts."),
      tone: LIVE_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "conversion_failed") {
    return {
      label: "Could not be read",
      meaning: `Nothing readable in this ${thing}.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "conversion_unavailable") {
    return {
      label: "Cannot be read here",
      meaning: "Can't read this type here. Send a PDF or type it.",
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  if (upload.review_state === "rejected") {
    return {
      label: "Not accepted",
      meaning: `This ${thing} was not accepted.`,
      tone: STOP_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  if (upload.review_state === "archived") {
    return {
      label: "Replaced",
      meaning: "A newer version replaced it.",
      tone: QUIET_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }

  if (awaitsConfirmation(upload)) {
    return {
      label: "Check what we read",
      meaning: isMachineRead(upload)
        ? "Check the words we read off your photo."
        : "Check what we read, then confirm.",
      tone: WAIT_TONE,
      working: false,
      awaitingConfirmation: true,
    };
  }

  if (upload.ingest_status === "received" || upload.ingest_status === "converting") {
    return {
      label: "Being read",
      meaning: isLink
        ? "Reading the page. About a minute."
        : "Reading your file. About a minute.",
      tone: WORK_TONE,
      working: true,
      awaitingConfirmation: false,
    };
  }
  if (upload.ingest_status === "processing") {
    return {
      label: "Going to your agents",
      meaning: "Sending to your agents. A minute or two.",
      tone: WORK_TONE,
      working: true,
      awaitingConfirmation: false,
    };
  }

  // Approved and not live yet: the publish has not run. An account member's own upload is
  // approved without anybody (D-658), so this names no person — only the step left.
  if (upload.review_state === "approved") {
    return {
      label: "Approved, not in use yet",
      meaning: "Nothing to do. Agents get it soon.",
      tone: WORK_TONE,
      working: false,
      awaitingConfirmation: false,
    };
  }
  return {
    label: "Waiting for review",
    meaning: `We check this ${thing} first.`,
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
/**
 * The steps a MOVING upload is on, from the server's own states — or `null` once it has
 * settled (live, failed, refused, replaced), where the status chip says it all.
 *
 * Since D-658 an account member's own upload needs nobody's approval, so its path is
 * received → read → in use; a machine-read document adds the one step that is the client's
 * own, checking what we read. Content still waiting for review (operator-added, or sent
 * in a view-as session) shows no steps: the next one is a person, not this pipeline.
 */
export function uploadSteps(
  upload: KbUpload,
): { steps: { id: string; label: string }[]; current: number } | null {
  // While a PDF's pages are being read the status chip says so; the steps resume after.
  if (upload.is_live || (isReadCopy(upload) && upload.read_state === "reading")) {
    return null;
  }
  if (awaitsConfirmation(upload)) {
    return {
      steps: [
        { id: "received", label: "Received" },
        { id: "read", label: "Read" },
        { id: "checked", label: "Checked by you" },
        { id: "live", label: "In use" },
      ],
      current: 2,
    };
  }
  const base = [
    { id: "received", label: "Received" },
    { id: "read", label: "Read" },
    { id: "live", label: "In use" },
  ];
  if (upload.ingest_status === "received" || upload.ingest_status === "converting") {
    return { steps: base, current: 1 };
  }
  if (upload.ingest_status === "processing") return { steps: base, current: 2 };
  return null;
}

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

/**
 * The kinds whose words reach the agents: one short line by default, the full sentence
 * behind the File view's tip. Each row still says whether its agents use it
 * (`reaches_agents`), since a PDF with no readable words, or a page that cannot be read,
 * does not reach them.
 */
export const READ_KINDS_LINE = "PDF, Word, Excel, CSV, text, or a photo of a list.";
export const READ_KINDS_SENTENCE =
  "Send what you already have: a PDF, a Word document, an Excel or CSV sheet, a text file, or a " +
  "photo of a printed price list or menu. We read it, and every one of your agents uses what it says.";

/** Said beside the file control: scanned pages are read too (`apps/workers/kb_read.py`). */
export const PDF_LINE = "Scanned PDF pages are read too.";
export const PDF_NOTE =
  "We read every page of a PDF, scanned pages too, and your agents use its words. Each one shows how the reading went.";

/** Said beside the link control: the agents read the page itself (D-868). */
export const LINK_LINE = "Your agents read that one page.";
export const LINK_NOTE =
  "We send that one page to your agents and keep a copy you and Pip can open. If it can't be read, its row says why.";

/** `apps/api/kb/uploads.MAX_UPLOAD_BYTES`, said the way the refusal says it. */
export const MAX_UPLOAD_MB = 20;

/** The kit formatter, under the name this screen already used. */
export { formatFileSize as fileSize } from "@/components/fileDrop";
