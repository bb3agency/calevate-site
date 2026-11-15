"use client";

/**
 * MATERIALS BEFORE THE CAMPAIGN EXISTS (D-992). Files and links are uploaded into the client's
 * knowledge at once (they need no campaign); notes are held here. Create attaches every item to
 * the new campaign (`POST /v1/campaigns/{id}/materials`), where the campaign page's own
 * Materials section takes over.
 */

import { useState } from "react";

import { problemToast } from "@/components/arc/feedback";
import { FIELD, PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { MaterialIn } from "@/lib/api/campaignWorkspace";
import { useAddLink, useUploadDocument } from "@/lib/api/kb";
import { useClientRealm } from "@/lib/api/session";

import { FilePicker } from "./FilePicker";

export type PendingMaterial = MaterialIn & { key: string };

const KIND_LABEL: Record<MaterialIn["kind"], string> = { file: "File", link: "Link", note: "Note" };

export function MaterialsDraft({
  items,
  onChange,
  canWrite,
}: {
  items: PendingMaterial[];
  onChange: (next: PendingMaterial[]) => void;
  canWrite: boolean;
}) {
  const { session } = useClientRealm();
  const upload = useUploadDocument(session);
  const addLink = useAddLink(session);
  const [mode, setMode] = useState<MaterialIn["kind"] | null>(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = upload.isPending || addLink.isPending;

  const reset = () => {
    setMode(null);
    setTitle("");
    setUrl("");
    setNote("");
    setFile(null);
    setError(null);
  };

  const add = async () => {
    setError(null);
    try {
      let item: MaterialIn;
      if (mode === "file") {
        if (!file) return setError("Choose a file.");
        const up = await upload.mutateAsync({ file });
        item = { kind: "file", title: title.trim() || file.name, kb_upload_id: up.id };
      } else if (mode === "link") {
        if (!/^https?:\/\//i.test(url.trim())) return setError("Paste the full address, starting with https://");
        const up = await addLink.mutateAsync({ url: url.trim() });
        item = { kind: "link", title: title.trim() || url.trim(), url: url.trim(), kb_upload_id: up.id };
      } else {
        if (!note.trim()) return setError("Write the note.");
        item = { kind: "note", title: title.trim() || note.trim().slice(0, 60), note: note.trim() };
      }
      onChange([...items, { ...item, key: crypto.randomUUID() }]);
      reset();
    } catch (e) {
      setError(problemToast(e, "That did not upload. Try again.").description ?? "That did not upload. Try again.");
    }
  };

  return (
    <section
      aria-labelledby="new-campaign-materials"
      className="rounded-card border border-info-line bg-info-soft p-4 sm:p-6 dark:bg-info/10"
    >
      <h2 id="new-campaign-materials" className="text-heading text-ink">
        <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-ink text-meta font-semibold text-surface">
          2
        </span>
        Materials
      </h2>
      <p className="mt-1 text-meta text-ink-muted">
        Everything Pip and the agent should know: documents, price lists, website links, video links, call recordings,
        notes. Files and links also go into your knowledge, so the agent can look things up on a call.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {(["file", "link", "note"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            className={mode === kind ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            aria-pressed={mode === kind}
            onClick={() => (mode === kind ? reset() : (reset(), setMode(kind)))}
          >
            {kind === "file" ? "Upload a file" : kind === "link" ? "Add a link (website, video)" : "Write a note"}
          </button>
        ))}
      </div>

      {mode && (
        <div className="mt-4 space-y-3 rounded-card border border-info-line bg-surface p-4">
          <label className="block text-meta font-medium text-ink">
            Name <span className="font-normal text-ink-muted">(optional)</span>
            <input className={`${FIELD} mt-1 w-full`} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </label>
          {mode === "file" && (
            <FilePicker
              file={file}
              onFile={setFile}
              hint="PDF, Word, Excel, CSV, text or a photo, up to 20 MB. For a video or a call recording, add its link."
            />
          )}
          {mode === "link" && (
            <label className="block text-meta font-medium text-ink">
              Address
              <input
                type="url"
                inputMode="url"
                className={`${FIELD} mt-1 w-full`}
                value={url}
                placeholder="https://"
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>
          )}
          {mode === "note" && (
            <label className="block text-meta font-medium text-ink">
              Note
              <textarea
                className={`${FIELD} mt-1 min-h-28 w-full resize-y`}
                value={note}
                maxLength={4000}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          )}
          {error && (
            <p role="alert" className="text-meta text-danger">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <button type="button" className={PRIMARY_BUTTON_SM} disabled={busy} onClick={() => void add()}>
              {busy ? "Uploading…" : "Add"}
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} disabled={busy} onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {items.length > 0 && (
        <ul className="mt-4 divide-y divide-info-line overflow-hidden rounded-card border border-info-line bg-surface">
          {items.map((m) => (
            <li key={m.key} className="flex items-start gap-3 px-4 py-3">
              <span className="mt-0.5 shrink-0 rounded-sm bg-info-soft px-1.5 py-0.5 text-meta font-medium text-info">
                {KIND_LABEL[m.kind]}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{m.title}</p>
                {m.url && <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{m.url}</p>}
                {m.note && <p className="mt-0.5 whitespace-pre-wrap text-meta text-ink-muted">{m.note}</p>}
              </div>
              <button
                type="button"
                className="shrink-0 text-meta text-ink-muted underline hover:text-danger"
                aria-label={`Remove ${m.title}`}
                onClick={() => onChange(items.filter((x) => x.key !== m.key))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
