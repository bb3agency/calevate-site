"use client";

import clsx from "clsx";
import { File as FileIcon, FileImage, FileSpreadsheet, FileText, Upload, X } from "lucide-react";
import { useId, useRef, useState, type ReactNode } from "react";

import { SECONDARY_BUTTON_SM } from "@/components/ui";

/**
 * THE ONE FILE CONTROL. Every place a person hands the product a file uses this, so the
 * browser's own "Choose file · No file chosen" never reaches a screen.
 *
 * ## The decisions
 *
 * 1. **A `<label>` around a real `<input type="file">`, never a `<div onDrop>`.** The input
 *    is `sr-only` (visually hidden, still focusable), so Tab reaches it and Enter or Space
 *    opens the picker; the label makes the whole dashed box the pointer and finger target.
 *    Drag and drop is an addition to a working control, not the control.
 * 2. **What it takes is said before a file is chosen** (`hint`), in the words the caller's
 *    server refusal uses — a person should not learn the size limit by being refused.
 * 3. **A dropped file is checked in the browser, because a drop bypasses `accept`.** The
 *    caller's `validate` (the same rules its server enforces) runs on every file, picked
 *    or dropped; with no `validate`, `accept` and `maxBytes` are checked here. The refusal
 *    is inline, beside the control, and the file never reaches `onFiles`.
 * 4. **No `capture` attribute.** With `accept` naming an image type, iOS and Android
 *    already offer "Take photo" beside the file browser; `capture` would REMOVE the file
 *    browser and force the camera, so a person with a scanned PDF could not send it.
 *
 * Controlled for what is shown: `files` are the chosen-but-not-sent files (a form that
 * sends on submit) and `sending` the one in flight (a screen that sends on pick); the
 * caller owns both, so the control never claims a file arrived that the server refused.
 */
export function FileDrop({
  label,
  hint,
  accept,
  maxBytes,
  validate,
  multiple = false,
  disabled = false,
  onFiles,
  files = [],
  onRemove,
  sending,
  className,
}: {
  /** The control's name, shown as the box's title and announced as the input's label. */
  label: string;
  /** What it takes, in plain words: kinds and size, e.g. "PDF, JPEG or PNG, up to 5 MB." */
  hint: ReactNode;
  /** The picker's filter. A hint to the picker, never the check — see `validate`. */
  accept: string;
  /** Checked here only when the caller passes no `validate`. */
  maxBytes?: number;
  /** Why this file cannot be sent, or `null`: the caller's preview of its server's rules. */
  validate?: (file: File) => string | null;
  multiple?: boolean;
  disabled?: boolean;
  /** The files that passed, in the order chosen. Never called with an empty list. */
  onFiles: (files: File[]) => void;
  /** Chosen and held by the caller until its form is sent; each gets a Remove action. */
  files?: File[];
  onRemove?: (index: number) => void;
  /** The file being sent now. `percent` is `null` while the browser cannot measure it. */
  sending?: { file: File; percent: number | null } | null;
  className?: string;
}) {
  const inputId = useId();
  const titleId = useId();
  const hintId = useId();
  const errorId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  function take(list: FileList | null | undefined): void {
    const chosen = Array.from(list ?? []);
    if (chosen.length === 0) return;
    const offered = multiple ? chosen : chosen.slice(0, 1);
    const accepted: File[] = [];
    const refusals: string[] = [];
    for (const file of offered) {
      const why = validate ? validate(file) : defaultProblem(file, accept, maxBytes);
      if (why) refusals.push(offered.length > 1 ? `${file.name}: ${why}` : why);
      else accepted.push(file);
    }
    if (!multiple && chosen.length > 1) refusals.push("Choose one file at a time.");
    setProblem(refusals.length ? refusals.join(" ") : null);
    if (accepted.length) onFiles(accepted);
    // Cleared so choosing the same file again (after removing it, or after a refusal from
    // the server) still fires `change`.
    if (input.current) input.current.value = "";
  }

  return (
    <div className={clsx("space-y-2", className)}>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!disabled) take(event.dataTransfer.files);
        }}
        className={clsx(
          "flex flex-col items-center gap-2 rounded-card border border-dashed px-4 py-5 text-center transition-colors duration-(--duration-fast) has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app",
          dragging ? "border-brand bg-brand-soft" : "border-line bg-app",
          disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        )}
      >
        <input
          ref={input}
          id={inputId}
          type="file"
          className="sr-only"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          aria-labelledby={titleId}
          aria-describedby={problem ? `${hintId} ${errorId}` : hintId}
          aria-invalid={problem ? true : undefined}
          onChange={(event) => take(event.target.files)}
        />
        <Upload aria-hidden className="h-5 w-5 text-ink-faint" />
        <span id={titleId} className="text-sm font-medium text-ink [overflow-wrap:anywhere]">
          {label}
        </span>
        {/* A span styled as the button: the label is the control, so a nested <button>
            would be a second, conflicting target. */}
        <span aria-hidden className={clsx(SECONDARY_BUTTON_SM, "pointer-events-none")}>
          {multiple ? "Choose files" : "Choose a file"}
        </span>
        {/* Nobody drags a file on a phone. */}
        <span aria-hidden className="text-xs text-ink-muted touch:hidden">
          or drag {multiple ? "them" : "it"} here
        </span>
        <span id={hintId} className="text-xs text-ink-muted">
          {hint}
        </span>
      </label>

      {problem && (
        <p id={errorId} role="alert" className="text-sm text-danger">
          {problem}
        </p>
      )}

      {sending && (
        <FileSummary file={sending.file}>
          <div
            role="progressbar"
            aria-label="Sending your file"
            aria-valuemin={0}
            aria-valuemax={100}
            // Absent while the browser cannot compute a total: a bar drawn against a
            // guessed total lies.
            aria-valuenow={sending.percent ?? undefined}
            className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10"
          >
            {/* Scaled rather than resized: progress events arrive many times a second,
                and a width transition re-lays-out the row on every one of them. */}
            <div
              className="h-full w-full origin-left rounded-full bg-brand-strong transition-transform duration-(--duration-base) ease-out"
              style={{ transform: `scaleX(${(sending.percent ?? 10) / 100})` }}
            />
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            Sending {sending.file.name}
            {sending.percent === null ? "…" : ` — ${sending.percent}%`}
          </p>
        </FileSummary>
      )}

      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.size}-${index}`}>
              <FileSummary
                file={file}
                action={
                  onRemove && (
                    <button
                      type="button"
                      onClick={() => onRemove(index)}
                      aria-label={`Remove ${file.name}`}
                      disabled={disabled}
                      className="press flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-black/5 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:h-11 touch:w-11 dark:hover:bg-white/5"
                    >
                      <X aria-hidden className="h-4 w-4" />
                    </button>
                  )
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One file as a row: its kind's icon, its name, and what it is. Used under `FileDrop` for
 * a chosen file, and on its own for a file already on record (pass `name`/`size`/`type`
 * from the server's metadata; `meta` adds a line such as when it was sent).
 */
export function FileSummary({
  file,
  name = file?.name ?? "",
  size = file?.size ?? null,
  type = file?.type ?? "",
  meta,
  action,
  children,
}: {
  file?: File;
  name?: string;
  size?: number | null;
  type?: string;
  meta?: ReactNode;
  /** Trailing controls: Remove, View, Replace. */
  action?: ReactNode;
  /** Under the name: a progress bar, a status. */
  children?: ReactNode;
}) {
  const Icon = iconFor(type, name);
  const facts = [kindLabel(type, name), formatFileSize(size)].filter(Boolean).join(" · ");
  return (
    <div className="flex items-start gap-3 rounded-md border border-line bg-surface px-3 py-2.5">
      <Icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-ink-faint" />
      <div className="min-w-0 flex-1">
        {/* `anywhere`: a scanner's filename is one unbroken 60-character token. */}
        <p className="text-sm font-medium text-ink [overflow-wrap:anywhere]">{name}</p>
        {facts && <p className="text-xs text-ink-muted">{facts}</p>}
        {meta && <div className="text-xs text-ink-muted">{meta}</div>}
        {children}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">{action}</div>}
    </div>
  );
}

/** A byte count as a person reads it, so a 3.4 MB file does not render as 3565158. */
export function formatFileSize(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${bytes} bytes`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function kindLabel(type: string, name: string): string {
  const extension = extensionOf(name);
  if (type === "application/pdf" || extension === "pdf") return "PDF";
  if (type.startsWith("image/")) return `${type.slice(6).toUpperCase()} image`;
  return extension ? extension.toUpperCase() : "";
}

function iconFor(type: string, name: string) {
  const extension = extensionOf(name);
  if (type.startsWith("image/") || ["jpg", "jpeg", "png", "heic", "heif", "webp", "avif"].includes(extension)) {
    return FileImage;
  }
  if (["csv", "tsv", "xlsx", "xls"].includes(extension)) return FileSpreadsheet;
  if (type === "application/pdf" || ["pdf", "docx", "txt", "md"].includes(extension)) return FileText;
  return FileIcon;
}

/** Does `file` match one entry of an `accept` list (".pdf", "image/png", "image/*")? */
function matchesAccept(file: File, accept: string): boolean {
  const entries = accept
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  if (entries.length === 0) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return entries.some((entry) =>
    entry.startsWith(".")
      ? name.endsWith(entry)
      : entry.endsWith("/*")
        ? type.startsWith(entry.slice(0, -1))
        : type === entry,
  );
}

function defaultProblem(file: File, accept: string, maxBytes: number | undefined): string | null {
  if (!matchesAccept(file, accept)) return "That kind of file cannot be sent here.";
  if (file.size === 0) return "That file is empty.";
  if (maxBytes !== undefined && file.size > maxBytes) {
    return `That file is ${formatFileSize(file.size)}, over the ${formatFileSize(maxBytes)} limit.`;
  }
  return null;
}
