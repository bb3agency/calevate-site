"use client";

/**
 * ADD A FILE OR NOTE from a campaign's Sources fold. What is added goes into What your agents
 * know, the one place that holds them (founder, 16 Nov 2026), and the campaign picks it. A
 * file already in the knowledge is reused rather than refused as a duplicate.
 */

import { useState } from "react";

import { FileDrop } from "@/components/fileDrop";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { NewCampaignSource } from "@/lib/api/campaignWorkspace";
import { NOTE_MAX_CHARS } from "@/lib/textLimits";

type Kind = NewCampaignSource["kind"];

const SOURCE_ACCEPT = ".pdf,.docx,.txt,.md,.csv,.xlsx,.jpg,.jpeg,.png,.webp,.heic";
const SOURCE_MAX_BYTES = 20 * 1024 * 1024;
const NAME_MAX = 200;

export const SOURCES_HINT = "What Pip reads to write this campaign's script.";
export const SOURCES_INFO =
  "Pick from What your agents know. Anything you add here goes there too, so every agent can use it.";

const BUTTON_LABEL: Record<Kind, string> = { file: "Upload a file", link: "Add a link", note: "Write a note" };

/** Choose a file, add a link or write a note, then hand the finished item to `onAdd`. */
export function AddSourceForm({
  canWrite,
  refusal,
  onAdd,
  adding = false,
  addError,
}: {
  canWrite: boolean;
  refusal?: string;
  onAdd: (item: NewCampaignSource) => Promise<unknown>;
  adding?: boolean;
  addError?: unknown;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Kind>("note");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [missing, setMissing] = useState<string | null>(null);

  const reset = () => {
    setOpen(false);
    setMode("note");
    setName("");
    setUrl("");
    setNote("");
    setFile(null);
    setMissing(null);
  };

  const submit = async () => {
    setMissing(null);
    let item: NewCampaignSource;
    if (mode === "file") {
      if (!file) return setMissing("Choose a file.");
      item = { kind: "file", file };
    } else if (mode === "link") {
      if (!/^https?:\/\//i.test(url.trim())) return setMissing("Paste the full address, starting with https://");
      item = { kind: "link", url: url.trim(), name: name.trim() || undefined };
    } else {
      if (!note.trim()) return setMissing("Write the note.");
      item = { kind: "note", note: note.trim(), title: name.trim() || undefined };
    }
    try {
      await onAdd(item);
    } catch {
      // The refusal is on the mutation and is rendered below.
      return;
    }
    reset();
  };

  if (!open) {
    return (
      <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite} title={refusal} onClick={() => setOpen(true)}>
        Add a file or note
      </button>
    );
  }

  return (
    <div className="max-w-2xl space-y-3 border-l-2 border-line pl-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="What to add">
        {(["note", "file", "link"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            className={mode === kind ? `${SECONDARY_BUTTON_SM} border-ink bg-ink/[0.04]` : SECONDARY_BUTTON_SM}
            aria-pressed={mode === kind}
            disabled={adding}
            onClick={() => {
              setMode(kind);
              setMissing(null);
            }}
          >
            {BUTTON_LABEL[kind]}
          </button>
        ))}
      </div>
      {mode !== "file" && (
        <label className="block text-meta font-medium text-ink">
          Name <span className="font-normal text-ink-muted">(optional)</span>
          <input className={`${FIELD} mt-1 w-full`} value={name} maxLength={NAME_MAX} onChange={(e) => setName(e.target.value)} />
        </label>
      )}
      {mode === "file" && (
        <>
          <FileDrop
            label="File"
            hint="PDF, Word, Excel, CSV, text or a photo, up to 20 MB."
            accept={SOURCE_ACCEPT}
            maxBytes={SOURCE_MAX_BYTES}
            files={file ? [file] : []}
            onRemove={() => setFile(null)}
            sending={adding && file ? { file, percent: null } : null}
            onFiles={([chosen]) => setFile(chosen ?? null)}
          />
          <p className="text-meta text-ink-muted">For a video or a recording, add its link.</p>
        </>
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
            maxLength={NOTE_MAX_CHARS}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      )}
      {missing && (
        <p role="alert" className="text-meta text-danger">
          {missing}
        </p>
      )}
      {addError != null && !adding && <ProblemNotice error={addError} />}
      <div className="flex gap-2">
        <button type="button" className={PRIMARY_BUTTON_SM} disabled={adding} onClick={() => void submit()}>
          {adding ? "Adding…" : "Add"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={adding} onClick={reset}>
          Cancel
        </button>
      </div>
    </div>
  );
}
