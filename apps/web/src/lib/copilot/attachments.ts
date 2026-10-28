"use client";

/**
 * Files a person attaches to a question for Pip (D-781): checked and converted HERE, on the
 * person's own device, then streamed to our API.
 *
 * The server never parses an upload, so every conversion happens in this module:
 *
 * - A PICTURE is decoded by the browser and re-drawn on a canvas, scaled to fit
 *   `MAX_EDGE`, and saved as JPEG. Re-drawing is what removes the location and camera data
 *   (EXIF/GPS): a canvas holds pixels and nothing else. HEIC works where the browser can
 *   decode it (Safari); elsewhere it is refused with a sentence that says what to do.
 * - A TEXT or CSV file is decoded (UTF-8, or UTF-16 by its byte-order mark) and re-encoded
 *   as UTF-8.
 * - A WORD, EXCEL or POWERPOINT file is opened by `officeText.ts` and only its text is sent.
 *
 * The limits mirror `apps/api/copilot/attachments.py`, which enforces them again.
 */

import { ApiProblem, apiRequest, apiUpload, type Session, type UploadProgress } from "@/lib/api/client";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { lookup } from "@/lib/lookup";

import { OfficeTextError, officeText } from "./officeText";
import { pdfText } from "./pdfText";

export const MAX_FILES = 5;
export const MAX_PICTURES = 2;
/** The largest file a person may pick, before conversion. */
export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_PICTURE_BYTES = 5 * 1024 * 1024;
export const MAX_PDF_BYTES = 14 * 1024 * 1024;
export const MAX_MESSAGE_BYTES = 50 * 1024 * 1024;
/** Pictures and PDFs together on one message: the bytes the model is sent inline. */
export const MAX_INLINE_BYTES = 14 * 1024 * 1024;
/** Uploads one person may have streaming at once; the server answers 429 past it. */
export const MAX_CONCURRENT_UPLOADS = 2;
/** The long edge Pip's model sees: twice the 768-pixel tile both providers bill by. */
export const MAX_EDGE = 1536;
const JPEG_QUALITY = 0.85;
const THUMB_EDGE = 160;

export type AttachmentKind = "picture" | "pdf" | "document";
type Source = "image" | "pdf" | "text" | "csv" | "docx" | "xlsx" | "pptx";

const SOURCES: Record<string, Source> = {
  jpg: "image",
  jpeg: "image",
  png: "image",
  webp: "image",
  heic: "image",
  heif: "image",
  txt: "text",
  md: "text",
  csv: "csv",
  docx: "docx",
  xlsx: "xlsx",
  pptx: "pptx",
  pdf: "pdf",
};

/** What the file picker offers. Explicit types rather than `image/*`: Safari on iOS then
 *  hands a HEIC photo over as JPEG (WebKit bug 267277). */
export const ACCEPT =
  "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp,.heic,.heif,.txt,.md,.csv,.docx,.xlsx,.pptx," +
  ".pdf,text/plain,text/csv,application/pdf";

/** What the transcript keeps instead of the files. Mirrors
 *  `apps/api/copilot/attachments.py::placeholder`. */
export const ATTACHED_MARKER = /^\[(\d+) files? attached\]\n?/;

export class AttachmentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AttachmentError";
  }
}

/** What the person reads when files cannot be attached at all. Names no provider and no
 *  setting (D-679): there is nothing they can do about it but ask in words. */
export const UPLOADS_UNAVAILABLE = `Attaching files isn't available yet. You can still ask ${ASSISTANT_NAME} in words.`;

/** The server's refusal for the same condition, which a race can still bring back. */
export function isUploadsUnavailable(error: unknown): boolean {
  return error instanceof ApiProblem && error.code === "copilot_uploads_unavailable";
}

/** The bytes one prepared file adds to its message, as the server counts them: the PDF's
 *  text counts toward the message, and pictures and PDFs also toward the inline total. */
export function bytesOf(prepared: PreparedFile): { total: number; inline: number } {
  const own = prepared.blob.size;
  return {
    total: own + (prepared.text?.size ?? 0),
    inline: prepared.kind === "document" ? 0 : own,
  };
}

/**
 * Whether one more prepared file fits the message, given what the others already hold, or
 * the sentence saying why not. Decided here, before the body is sent, because the server
 * decides the same thing from the declared length before reading the body, and an answer
 * that arrives while the body is still streaming can reach the browser as a reset stream
 * instead of as that answer.
 */
export function roomRefusal(
  name: string,
  adding: { total: number; inline: number },
  held: Iterable<{ total: number; inline: number }>,
): string | null {
  let total = adding.total;
  let inline = adding.inline;
  for (const other of held) {
    total += other.total;
    inline += other.inline;
  }
  const next = "Send this message, then attach the rest to the next one.";
  if (total > MAX_MESSAGE_BYTES) return `${name} doesn't fit: files on one message can add up to 50 MB. ${next}`;
  if (adding.inline > 0 && inline > MAX_INLINE_BYTES) {
    return `${name} doesn't fit: pictures and PDFs on one message can add up to 14 MB. ${next}`;
  }
  return null;
}

/**
 * At most `MAX_CONCURRENT_UPLOADS` uploads streaming at once; the rest wait their turn here
 * rather than being started and refused by the server with 429 mid-body.
 */
export class UploadSlots {
  private free: number;
  private readonly waiting: (() => void)[] = [];

  constructor(size: number = MAX_CONCURRENT_UPLOADS) {
    this.free = size;
  }

  /** Resolves when a slot is this caller's; rejects with an `AbortError` if `signal` fires
   *  first. Every resolved `acquire` must be paired with one `release`. */
  acquire(signal: AbortSignal): Promise<void> {
    if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
    if (this.free > 0) {
      this.free -= 1;
      return Promise.resolve();
    }
    return new Promise<void>((resolve, reject) => {
      const go = () => {
        signal.removeEventListener("abort", drop);
        resolve();
      };
      const drop = () => {
        const at = this.waiting.indexOf(go);
        if (at >= 0) this.waiting.splice(at, 1);
        reject(new DOMException("Aborted", "AbortError"));
      };
      this.waiting.push(go);
      signal.addEventListener("abort", drop, { once: true });
    });
  }

  release(): void {
    const next = this.waiting.shift();
    if (next) next();
    else this.free += 1;
  }
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

/** Why this file cannot be attached, in a sentence a person can act on, or null. */
export function refusalFor(file: File): string | null {
  const ext = extensionOf(file.name);
  if (["docm", "dotm", "xlsm", "xltm", "xlsb", "xlam", "pptm", "potm", "ppsm", "ppam"].includes(ext)) {
    return `${file.name} has macros. Save it as a regular .docx, .xlsx or .pptx file and attach that.`;
  }
  if (["doc", "xls", "ppt"].includes(ext)) {
    return `${file.name} is an older Office file. Save it as .docx, .xlsx or .pptx and attach that.`;
  }
  if (lookup(SOURCES, ext) === undefined) {
    return `${file.name} can't be attached. ${ASSISTANT_NAME} reads pictures, PDFs, text, Markdown and CSV files, and Word, Excel and PowerPoint files.`;
  }
  if (ext === "pdf" && file.size > MAX_PDF_BYTES) return `${file.name} is larger than 14 MB, the most a PDF can be.`;
  if (file.size > MAX_FILE_BYTES) return `${file.name} is larger than 20 MB.`;
  if (file.size === 0) return `${file.name} is empty.`;
  return null;
}

export function kindOf(file: File): AttachmentKind {
  const source = lookup(SOURCES, extensionOf(file.name));
  if (source === "image") return "picture";
  return source === "pdf" ? "pdf" : "document";
}

/** A file ready to send: the converted bytes, and a small preview for pictures. */
export interface PreparedFile {
  name: string;
  kind: AttachmentKind;
  blob: Blob;
  /** A small JPEG data URL, for pictures. Made from the cleaned image, never the original. */
  thumb: string | null;
  /** For a PDF: the text this browser found in it (UTF-8), or null when it found none. */
  text?: Blob | null;
}

async function decodeImage(file: File): Promise<ImageBitmap> {
  try {
    return await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    const ext = extensionOf(file.name);
    throw new AttachmentError(
      ext === "heic" || ext === "heif"
        ? `This browser can't open HEIC photos. Take a screenshot of ${file.name}, or share it as JPEG, and attach that.`
        : `${file.name} couldn't be opened as a picture.`,
    );
  }
}

function draw(bitmap: ImageBitmap, edge: number): HTMLCanvasElement {
  const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d");
  if (context === null) throw new AttachmentError("This browser couldn't prepare the picture.");
  // White under transparency: a screenshot of a page with a clear background reads as one.
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function toJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new AttachmentError("The picture couldn't be prepared."))),
      "image/jpeg",
      quality,
    );
  });
}

async function preparePicture(file: File): Promise<PreparedFile> {
  const bitmap = await decodeImage(file);
  try {
    let blob = await toJpeg(draw(bitmap, MAX_EDGE), JPEG_QUALITY);
    if (blob.size > MAX_PICTURE_BYTES) blob = await toJpeg(draw(bitmap, MAX_EDGE), 0.6);
    if (blob.size > MAX_PICTURE_BYTES) throw new AttachmentError(`${file.name} is too large to send.`);
    const thumb = draw(bitmap, THUMB_EDGE).toDataURL("image/jpeg", 0.7);
    return { name: file.name, kind: "picture", blob, thumb };
  } finally {
    bitmap.close();
  }
}

function decodeText(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder("utf-16le").decode(bytes.subarray(2));
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder("utf-16be").decode(bytes.subarray(2));
  return new TextDecoder("utf-8").decode(bytes);
}

async function prepareDocument(file: File, source: Exclude<Source, "image" | "pdf">): Promise<PreparedFile> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text: string;
  if (source === "text" || source === "csv") {
    text = decodeText(bytes);
    if (text.includes("\u0000")) throw new AttachmentError(`${file.name} isn't a text file.`);
  } else {
    try {
      text = await officeText(bytes, source);
    } catch (error) {
      if (error instanceof OfficeTextError) throw new AttachmentError(`${file.name}: ${error.message}`);
      throw new AttachmentError(`${file.name} couldn't be opened.`);
    }
  }
  if (text.trim() === "") throw new AttachmentError(`${file.name} has no text in it.`);
  const type = source === "csv" ? "text/csv" : "text/plain";
  const blob = new Blob([new TextEncoder().encode(text)], { type });
  if (blob.size > MAX_FILE_BYTES) throw new AttachmentError(`${file.name} is larger than 20 MB.`);
  return { name: file.name, kind: "document", blob, thumb: null };
}

/** Check and convert one file on this device. Throws `AttachmentError` with a sentence. */
export async function prepareFile(file: File): Promise<PreparedFile> {
  const refusal = refusalFor(file);
  if (refusal !== null) throw new AttachmentError(refusal);
  const source = lookup(SOURCES, extensionOf(file.name));
  if (source === undefined) throw new AttachmentError(`${file.name} can't be attached.`);
  if (source === "image") return preparePicture(file);
  return source === "pdf" ? preparePdf(file) : prepareDocument(file, source);
}

/** A PDF goes AS IT IS (Gemini reads it natively); its text is taken out here too, so Pip
 *  has something to read if Gemini cannot read the PDF when the question is asked. */
async function preparePdf(file: File): Promise<PreparedFile> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const signature = new TextDecoder("latin1").decode(bytes.subarray(0, 5));
  if (signature !== "%PDF-") throw new AttachmentError(`${file.name} isn't a PDF.`);
  const text = await pdfText(bytes);
  const textBlob = text.trim() === "" ? null : new Blob([new TextEncoder().encode(text)], { type: "text/plain" });
  return {
    name: file.name,
    kind: "pdf",
    blob: new Blob([bytes], { type: "application/pdf" }),
    thumb: null,
    // Text over a document's limit would be refused before its body is read; without it
    // the PDF still works while Gemini can read it.
    text: textBlob !== null && textBlob.size <= MAX_FILE_BYTES ? textBlob : null,
  };
}

export interface StoredAttachment {
  id: string;
  file_name: string;
  kind: AttachmentKind;
  content_type: string;
  size_bytes: number | null;
  status: "ready";
}

export function uploadsPath(realm: "client" | "admin"): string {
  return realm === "admin" ? "/v1/admin/copilot/uploads" : "/v1/copilot/uploads";
}

/** Stream one prepared file to the API. The body is the file; the name rides a header. */
export function uploadPrepared(
  session: Session,
  realm: "client" | "admin",
  prepared: PreparedFile,
  options: { signal?: AbortSignal; onProgress?: (progress: UploadProgress) => void } = {},
): Promise<StoredAttachment> {
  return uploadWithText(session, realm, prepared, options);
}

async function uploadWithText(
  session: Session,
  realm: "client" | "admin",
  prepared: PreparedFile,
  options: { signal?: AbortSignal; onProgress?: (progress: UploadProgress) => void },
): Promise<StoredAttachment> {
  const stored = await apiUpload<StoredAttachment>(session, uploadsPath(realm), prepared.blob, {
    uploadName: prepared.name,
    signal: options.signal,
    onProgress: options.onProgress,
  });
  if (prepared.text) {
    // The PDF's text, tied to it. If this fails the PDF still works while Gemini can read
    // it; there is just no text to fall back on, which the server already handles.
    await apiUpload(session, uploadsPath(realm), prepared.text, {
      uploadName: `${prepared.name}.txt`,
      uploadTextOf: stored.id,
      signal: options.signal,
    }).catch(() => undefined);
  }
  return stored;
}

/** Delete one stored file. */
export function removeUpload(session: Session, realm: "client" | "admin", id: string): Promise<void> {
  return apiRequest<void>(session, `${uploadsPath(realm)}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/** The marker the transcript stored, and the question without it. */
export function splitMarker(content: string): { count: number; text: string } {
  const match = ATTACHED_MARKER.exec(content);
  if (match === null) return { count: 0, text: content };
  return { count: Number(match[1]), text: content.slice(match[0].length) };
}

const NOTICE_KEY = "calevate.pip.attachNotice";

/** Has this browser shown the first-use notice? Storage can be unavailable; then the
 *  notice simply shows again, which is the safe direction. */
export function noticeSeen(): boolean {
  try {
    return window.localStorage.getItem(NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

export function markNoticeSeen(): void {
  try {
    window.localStorage.setItem(NOTICE_KEY, "1");
  } catch {
    // Storage blocked: the notice shows again next time, which is the safe direction.
  }
}
