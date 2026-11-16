"use client";

/**
 * PICK FROM WHAT YOUR AGENTS KNOW (founder, 16 Nov 2026: one place to add things). The one
 * pick list a campaign's and an inbound line's Sources fold both show: the account's typed
 * notes, files and links, each by its source id, ticked for the ones Pip writes from, with
 * search once the list is long. Saving replaces the last choice.
 */

import type { UseMutationResult } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { SearchField } from "@/components/arc/search-field";
import { PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useKbNotes, useKbUploads } from "@/lib/api/kb";
import { useClientRealm } from "@/lib/api/session";

import { matchesWords } from "./matchWords";

type SourceChoice = { id: string; name: string; kind: string };

/** Search shows from this many choices on. */
const SEARCH_FROM = 7;

/** The account's knowledge as a pick list: typed notes and uploads, each by its source id. */
function useSourceChoices() {
  const { session } = useClientRealm();
  const notes = useKbNotes(session);
  const uploads = useKbUploads(session);
  const choices = useMemo<SourceChoice[]>(() => {
    const fromNotes = (notes.data?.notes ?? [])
      .filter((note) => note.state !== "removed")
      .map((note) => ({ id: note.id, name: note.name, kind: "Note" }));
    const fromUploads = (uploads.data ?? []).map((upload) => ({
      id: upload.source_id,
      name: upload.name,
      kind: upload.source_kind === "url" ? "Link" : "File",
    }));
    return [...fromUploads, ...fromNotes];
  }, [notes.data, uploads.data]);
  return {
    choices,
    isLoading: notes.isLoading || uploads.isLoading,
    error: notes.error ?? uploads.error,
    ready: notes.data !== undefined && uploads.data !== undefined,
    refetch: () => {
      void notes.refetch();
      void uploads.refetch();
    },
  };
}

export function SourcePicker<TData, TError, TContext>({
  saved,
  legend,
  canWrite,
  refusal,
  save,
  emptyAction = true,
}: {
  /** The source ids picked now. */
  saved: string[];
  /** What the list is for, for a screen reader ("Sources for this line"). */
  legend: string;
  canWrite: boolean;
  refusal?: string;
  save: UseMutationResult<TData, TError, string[], TContext>;
  /** With nothing to pick, offer a way to What your agents know. */
  emptyAction?: boolean;
}) {
  const { session, href } = useClientRealm();
  const sources = useSourceChoices();
  const [picked, setPicked] = useState<string[] | null>(null);
  const [query, setQuery] = useState("");
  const chosen = picked ?? saved;
  const dirty = picked !== null && [...picked].sort().join() !== [...saved].sort().join();
  const shown = sources.choices.filter((choice) => matchesWords(query, [choice.name, choice.kind]));
  const toggle = (id: string) =>
    setPicked((current) => {
      const base = current ?? saved;
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    });

  if (sources.isLoading) return <Skeleton rows={2} label="Loading what your agents know" />;
  if (!sources.ready) {
    return <ProblemNotice error={sources.error ?? new Error("Your sources did not load.")} onRetry={sources.refetch} />;
  }
  if (sources.choices.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-body text-ink-muted">Nothing added to What your agents know yet.</p>
        {emptyAction && (
          <Link href={href(`/c/${session.orgSlug}/knowledge`)} className={SECONDARY_BUTTON_SM}>
            Add knowledge
          </Link>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {sources.choices.length >= SEARCH_FROM && (
        <SearchField label="Search sources" hideLabel value={query} onValueChange={setQuery} placeholder="Search sources" />
      )}
      <fieldset>
        <legend className="sr-only">{legend}</legend>
        <ul className="max-w-3xl divide-y divide-line border-y border-line">
          {shown.map((choice) => (
            <li key={choice.id}>
              <label className="flex cursor-pointer items-start gap-3 py-3 touch:min-h-11">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 shrink-0 accent-brand"
                  checked={chosen.includes(choice.id)}
                  disabled={!canWrite || save.isPending}
                  onChange={() => toggle(choice.id)}
                />
                <span className="min-w-0">
                  <span className="block text-body text-ink [overflow-wrap:anywhere]">{choice.name}</span>
                  <span className="block text-meta text-ink-muted">{choice.kind}</span>
                </span>
              </label>
            </li>
          ))}
          {shown.length === 0 && <li className="py-3 text-meta text-ink-muted">Nothing matches “{query}”.</li>}
        </ul>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={!canWrite || !dirty || save.isPending}
          title={refusal}
          onClick={() => save.mutate(chosen, { onSuccess: () => setPicked(null) })}
        >
          {save.isPending ? "Saving…" : "Save sources"}
        </button>
        {dirty && (
          <button type="button" className={SECONDARY_BUTTON_SM} disabled={save.isPending} onClick={() => setPicked(null)}>
            Cancel
          </button>
        )}
      </div>
      {save.error != null && <ProblemNotice error={save.error} />}
    </div>
  );
}
