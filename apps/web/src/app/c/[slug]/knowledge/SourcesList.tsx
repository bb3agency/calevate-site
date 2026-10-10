"use client";

import { useState } from "react";

import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import { useKbChunks, useKbUploads, type useKbSources } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";

import { FactRow } from "./SubmittedList";
import { UploadRow } from "./UploadList";

/** `apps/api/teach/facts.FACTS_SOURCE_NAME`: the source the taught facts compile into. */
const TAUGHT_FACTS_SOURCE = "Facts you taught";

/**
 * EVERYTHING THIS ACCOUNT HAS TAUGHT ITS AGENTS, in one list: the files, photos and web
 * pages it sent, then the facts it typed — each row saying where it is. No row names an
 * agent, because every row is shared by all of them (D-689).
 *
 * Two reads behind one list, and each keeps its own honesty (§52): a read that failed gets
 * its refusal and no rows, and "nothing yet" is said only when BOTH answered empty —
 * "nothing here" over a request that never answered tells a client the price list they
 * sent this morning was never received. The upload list is read once; each row that is
 * still moving watches itself (`useKbUpload`) and stops the moment it settles.
 */
export function SourcesList({
  sources,
  only,
}: {
  sources: ReturnType<typeof useKbSources>;
  /** Facts and Files are separate tabs (REDESIGN-2); each lists its own kind. */
  only: "facts" | "files";
}) {
  const session = useClientSession();
  // The Facts tab reads no files (and so does not ask for them).
  const uploads = useKbUploads(session, only === "files");
  const [previewing, setPreviewing] = useState<string | null>(null);
  const chunks = useKbChunks(session, previewing);

  const uploadRows = only === "files" ? uploads.data : [];
  // The teach box's own facts compile into one source; they are listed one by one above it.
  const facts =
    only === "facts"
      ? sources.data?.filter((source) => source.kind === "text" && source.name !== TAUGHT_FACTS_SOURCE)
      : [];
  const loading = only === "files" ? uploads.isLoading : sources.isLoading;
  const count = (uploadRows?.length ?? 0) + (facts?.length ?? 0);

  return (
    <section aria-labelledby="kb-sources-heading" className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="kb-sources-heading" className="text-heading text-ink">
          {only === "files" ? "Your files" : "Notes you wrote"}
        </h2>
        {uploadRows && facts && count > 0 && (
          <span className="text-meta text-ink-muted">
            {formatCount(count)} {only === "files" ? (count === 1 ? "file" : "files") : count === 1 ? "note" : "notes"}
          </span>
        )}
      </div>

      {only === "files" && (uploads.error || (!uploads.isLoading && !uploads.data)) && (
        <ProblemNotice
          error={uploads.error ?? new Error("We could not load what you have sent.")}
          onRetry={() => void uploads.refetch()}
        />
      )}

      {/* Nothing to draw when neither read answered: the refusals say it all. */}
      {(loading || uploadRows || facts) && (
      <div className="border-y border-line">
        {loading ? (
          <div className="py-4">
            <Skeleton rows={4} label="Loading what your agents know" />
          </div>
        ) : uploadRows && facts && count === 0 ? (
          <EmptyState
            align="start"
            illustration={<EmptySketch kind="knowledge" />}
            message={
              <>
                <span className="block font-medium text-ink">
                  {only === "files" ? "No files yet" : "Nothing submitted yet"}
                </span>
                <span className="mt-1 block">
                  {only === "files"
                    ? "Send your price list, brochure or menu as a file or a photo."
                    : "Longer notes you wrote before the teach box appear here."}
                </span>
              </>
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {uploadRows?.map((upload) => (
              <UploadRow key={upload.id} upload={upload} />
            ))}
            {facts?.map((source) => (
              <FactRow
                key={source.id}
                source={source}
                open={previewing === source.id}
                onToggle={() => setPreviewing(previewing === source.id ? null : source.id)}
                chunks={chunks}
              />
            ))}
          </ul>
        )}
      </div>
      )}
    </section>
  );
}
