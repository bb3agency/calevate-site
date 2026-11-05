"use client";

import { useState } from "react";

import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount } from "@/components/ui";
import { useKbChunks, type KbChunk, type KbUpload } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";

/** Sections shown before "Show all", so a 60-page file does not open as one wall. */
export const FIRST_SECTIONS = 12;

/**
 * WHAT ONE FILE TAUGHT THE AGENTS, read from the same chunks the agents are handed
 * (`GET /v1/kb/sources/{id}/preview`), each under the heading it sat under in the file.
 * The count on the row is the server's (`UploadOut.facts_count`), so the list and the
 * number cannot disagree. A link's chunks are our copy of the page: its agents read the
 * page itself, and the panel says so.
 */
export function FileContents({ upload, query = "" }: { upload: KbUpload; query?: string }) {
  return (
    <div className="mt-3">
      {upload.source_kind === "url" ? (
        <p className="mb-2 text-meta text-ink-muted">Our copy. Your agents read the page itself.</p>
      ) : null}
      <Sections sourceId={upload.source_id} total={upload.facts_count} query={query} />
    </div>
  );
}

function matches(query: string, chunk: KbChunk): boolean {
  const q = query.trim().toLocaleLowerCase();
  return !q || chunk.content.toLocaleLowerCase().includes(q);
}

function Sections({ sourceId, total, query }: { sourceId: string; total: number; query: string }) {
  const session = useClientSession();
  const chunks = useKbChunks(session, sourceId);
  const [all, setAll] = useState(false);

  if (chunks.isLoading) return <Skeleton rows={Math.min(total, 4)} label="Loading what it learned" />;
  if (chunks.error || !chunks.data) {
    return (
      <ProblemNotice
        error={chunks.error ?? new Error("We could not show what it learned.")}
        onRetry={() => void chunks.refetch()}
      />
    );
  }
  const found = chunks.data.filter((chunk) => matches(query, chunk));
  if (found.length === 0) {
    return <p className="text-meta text-ink-muted">Nothing here matches your search.</p>;
  }
  const shown = all ? found : found.slice(0, FIRST_SECTIONS);
  return (
    <>
      <ol className="divide-y divide-line border-y border-line" aria-label="What it learned">
        {shown.map((chunk, index) => {
          // A heading split over several chunks is printed once, above its first piece.
          const heading = chunk.section && chunk.section !== shown[index - 1]?.section ? chunk.section : null;
          return (
            <li key={chunk.idx} className="py-2.5">
              {heading ? <p className="text-meta font-medium text-ink-muted">{heading}</p> : null}
              <p className="whitespace-pre-line text-body text-ink [overflow-wrap:anywhere]">
                {chunk.body}
              </p>
            </li>
          );
        })}
      </ol>
      {found.length > shown.length ? (
        <button type="button" className={`${SECONDARY_BUTTON_SM} mt-3`} onClick={() => setAll(true)}>
          Show all {formatCount(found.length)}
        </button>
      ) : null}
    </>
  );
}
