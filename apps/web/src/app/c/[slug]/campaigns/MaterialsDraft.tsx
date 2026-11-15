"use client";

/**
 * MATERIALS BEFORE THE CAMPAIGN EXISTS (D-992). Files and links are uploaded into the client's
 * knowledge at once (they need no campaign); notes are held here. Create attaches every item to
 * the new campaign (`POST /v1/campaigns/{id}/materials`), where the campaign page's own
 * Materials section takes over.
 *
 * `MaterialForm` is the one way to add a material, here and on the campaign page: only what
 * happens to the finished item differs (held in this list, or attached to the campaign).
 *
 * A file is held as the File itself, never uploaded here: it goes in through the campaign's own
 * upload (`POST /v1/campaigns/{id}/materials/upload`), which reuses a copy already in the
 * knowledge instead of refusing it as a duplicate. So a new campaign's files wait for the draft.
 */

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION_DANGER } from "@/components/console/section";
import { FileDrop } from "@/components/fileDrop";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { MaterialIn } from "@/lib/api/campaignWorkspace";
import { useAddLink } from "@/lib/api/kb";
import { useClientRealm } from "@/lib/api/session";

import { FoldSection } from "./FoldSection";

/** A material as the form finishes it: a file still carries the File to upload. */
export type MaterialItem = MaterialIn & { file?: File };
export type PendingMaterial = MaterialItem & { key: string };

export const KIND_LABEL: Record<MaterialIn["kind"], string> = { file: "File", link: "Link", note: "Note" };

const MATERIAL_ACCEPT = ".pdf,.docx,.txt,.md,.csv,.xlsx,.jpg,.jpeg,.png,.webp,.heic";
const MATERIAL_MAX_BYTES = 20 * 1024 * 1024;

export const MATERIALS_HINT = "What Pip and the agent should know.";
export const MATERIALS_INFO =
  "Documents, price lists, website and video links, call recordings, notes. Files and links also go into your knowledge, so the agent can look things up on a call.";

/**
 * Choose a file, add a link or write a note, then hand the finished item to `onAdd`. A link goes
 * into the knowledge first; `addError` is the refusal of whatever `onAdd` sends.
 */
export function MaterialForm({
  canWrite,
  refusal,
  onAdd,
  adding = false,
  addError,
}: {
  canWrite: boolean;
  refusal?: string;
  onAdd: (item: MaterialItem) => Promise<unknown>;
  adding?: boolean;
  addError?: unknown;
}) {
  const { session } = useClientRealm();
  const addLink = useAddLink(session);
  useActionFeedback(addLink, { errorDisplay: "inline" });
  const [mode, setMode] = useState<MaterialIn["kind"] | null>(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  const busy = adding || addLink.isPending;
  const problem = addLink.error ?? addError;

  const reset = () => {
    setMode(null);
    setTitle("");
    setUrl("");
    setNote("");
    setFile(null);
    setMissing(null);
    addLink.reset();
  };

  const submit = async () => {
    setMissing(null);
    addLink.reset();
    let item: MaterialItem;
    try {
      if (mode === "file") {
        if (!file) return setMissing("Choose a file.");
        item = { kind: "file", title: title.trim() || file.name, file };
      } else if (mode === "link") {
        if (!/^https?:\/\//i.test(url.trim())) return setMissing("Paste the full address, starting with https://");
        const up = await addLink.mutateAsync({ url: url.trim() });
        item = { kind: "link", title: title.trim() || url.trim(), url: url.trim(), kb_upload_id: up.id };
      } else {
        if (!note.trim()) return setMissing("Write the note.");
        item = { kind: "note", title: title.trim() || note.trim().slice(0, 60), note: note.trim() };
      }
      await onAdd(item);
    } catch {
      // The refusal is on the mutation that failed and is rendered below.
      return;
    }
    reset();
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {(["file", "link", "note"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            className={mode === kind ? `${SECONDARY_BUTTON_SM} border-ink bg-ink/[0.04]` : SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            title={refusal}
            aria-pressed={mode === kind}
            onClick={() => (mode === kind ? reset() : (reset(), setMode(kind)))}
          >
            {kind === "file" ? "Upload a file" : kind === "link" ? "Add a link" : "Write a note"}
          </button>
        ))}
      </div>

      {mode && (
        <div className="mt-4 max-w-2xl space-y-3 border-l-2 border-line pl-4">
          <label className="block text-meta font-medium text-ink">
            Name <span className="font-normal text-ink-muted">(optional)</span>
            <input className={`${FIELD} mt-1 w-full`} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </label>
          {mode === "file" && (
            <FileDrop
              label="File"
              hint="PDF, Word, Excel, CSV, text or a photo, up to 20 MB."
              accept={MATERIAL_ACCEPT}
              maxBytes={MATERIAL_MAX_BYTES}
              files={file ? [file] : []}
              onRemove={() => setFile(null)}
              sending={adding && file ? { file, percent: null } : null}
              onFiles={([chosen]) => setFile(chosen ?? null)}
            />
          )}
          {mode === "file" && <p className="text-meta text-ink-muted">For a video or a recording, add its link.</p>}
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
          {missing && (
            <p role="alert" className="text-meta text-danger">
              {missing}
            </p>
          )}
          {problem != null && !busy && <ProblemNotice error={problem} />}
          <div className="flex gap-2">
            <button type="button" className={PRIMARY_BUTTON_SM} disabled={busy} onClick={() => void submit()}>
              {busy ? "Adding…" : "Add"}
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} disabled={busy} onClick={reset}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export function MaterialsDraft({
  items,
  onChange,
  canWrite,
}: {
  items: PendingMaterial[];
  onChange: (next: PendingMaterial[]) => void;
  canWrite: boolean;
}) {
  return (
    <FoldSection title="Materials" tone="materials" hint={MATERIALS_HINT} info={MATERIALS_INFO}>

      <MaterialForm
        canWrite={canWrite}
        onAdd={async (item) => onChange([...items, { ...item, key: crypto.randomUUID() }])}
      />

      {items.length > 0 && (
        <ul className="mt-4 max-w-4xl divide-y divide-line border-y border-line">
          {items.map((m) => (
            <li key={m.key} className="flex items-start gap-3 py-3.5">
              <span className="mt-0.5 w-12 shrink-0 text-meta text-ink-muted">
                {KIND_LABEL[m.kind]}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{m.title}</p>
                {m.url && <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{m.url}</p>}
                {m.note && <p className="mt-0.5 whitespace-pre-wrap text-meta text-ink-muted">{m.note}</p>}
              </div>
              <button
                type="button"
                className={TEXT_ACTION_DANGER}
                aria-label={`Remove ${m.title}`}
                onClick={() => onChange(items.filter((x) => x.key !== m.key))}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </FoldSection>
  );
}
