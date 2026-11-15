"use client";

/**
 * A file picker that looks like the thing to press: a dashed box saying "Click to choose a
 * file, or drag it here", which shows the chosen file's name and size once picked. The real
 * `<input type="file">` sits inside the label (visually hidden), so the whole box opens the
 * system's file chooser, and keyboard and screen-reader users reach the same input.
 */

import { FileUp } from "lucide-react";
import { useId, useState } from "react";

export const MATERIAL_FILE_TYPES = ".pdf,.docx,.txt,.md,.csv,.xlsx,.jpg,.jpeg,.png,.webp,.heic";

function sizeLabel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FilePicker({
  file,
  onFile,
  accept = MATERIAL_FILE_TYPES,
  hint,
}: {
  file: File | null;
  onFile: (file: File | null) => void;
  accept?: string;
  hint?: string;
}) {
  const id = useId();
  const [over, setOver] = useState(false);
  return (
    <div>
      <label
        htmlFor={id}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          onFile(e.dataTransfer.files?.[0] ?? null);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-card border-2 border-dashed px-4 py-6 text-center transition-colors focus-within:ring-2 focus-within:ring-brand ${
          over ? "border-brand bg-brand-soft" : "border-info-line bg-info-soft/50 hover:border-brand hover:bg-brand-soft/60"
        }`}
      >
        <FileUp aria-hidden className="h-6 w-6 text-brand-strong" />
        {file ? (
          <>
            <span className="text-body font-medium text-ink [overflow-wrap:anywhere]">{file.name}</span>
            <span className="text-meta text-ink-muted">{sizeLabel(file.size)} · click to choose a different file</span>
          </>
        ) : (
          <>
            <span className="text-body font-medium text-brand-strong">Click to choose a file</span>
            <span className="text-meta text-ink-muted">or drag it here</span>
          </>
        )}
        <input
          id={id}
          type="file"
          accept={accept}
          className="sr-only"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </label>
      {hint && <p className="mt-1.5 text-meta text-ink-muted">{hint}</p>}
    </div>
  );
}
