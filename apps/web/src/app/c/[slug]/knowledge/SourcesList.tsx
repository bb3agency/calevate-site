"use client";

import { useState } from "react";

import { EmptyState } from "@/components/console/emptyState";
import { ProblemNotice, Skeleton, formatCount } from "@/components/ui";
import { useKbChunks, useKbUploads, type useKbSources } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { FactRow } from "./SubmittedList";
import { UploadRow } from "./UploadList";

/**
 * EVERYTHING THIS ACCOUNT HAS TAUGHT ITS AGENTS, in one list: the files, photos and web
 * pages it sent, then the facts it typed — each row saying where it is.
 *
 * Two reads behind one list, and each keeps its own honesty (§52): a read that failed gets
 * its refusal and no rows, and "nothing yet" is said only when BOTH answered empty —
 * "nothing here" over a request that never answered tells a client the price list they
 * sent this morning was never received. The upload list is read once; each row that is
 * still moving watches itself (`useKbUpload`) and stops the moment it settles.
 */
export function SourcesList({
  agentNames,
  sources,
}: {
  agentNames: Record<string, string>;
  sources: ReturnType<typeof useKbSources>;
}) {
  const session = useClientSession();
  const uploads = useKbUploads(session);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const chunks = useKbChunks(session, previewing);

  const uploadRows = uploads.data;
  const facts = sources.data?.filter((source) => source.kind === "text");
  const loading = uploads.isLoading || sources.isLoading;
  const count = (uploadRows?.length ?? 0) + (facts?.length ?? 0);

  return (
    <section aria-labelledby="kb-sources-heading" className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="kb-sources-heading" className="text-[15px] font-semibold text-ink">
          Sources
        </h2>
        {uploadRows && facts && count > 0 && (
          <span className="text-[13px] text-ink-muted">
            {formatCount(count)} {count === 1 ? "source" : "sources"}
          </span>
        )}
      </div>

      {(uploads.error || (!uploads.isLoading && !uploadRows)) && (
        <ProblemNotice
          error={uploads.error ?? new Error("We could not load what you have sent.")}
          onRetry={() => void uploads.refetch()}
        />
      )}

      {/* Nothing to draw when neither read answered: the refusals say it all. */}
      {(loading || uploadRows || facts) && (
      <div className="rounded-card border border-line bg-surface px-4">
        {loading ? (
          <div className="py-4">
            <Skeleton rows={4} label="Loading what your agents know" />
          </div>
        ) : uploadRows && facts && count === 0 ? (
          <EmptyState
            message={
              <>
                <span className="block font-medium text-ink">Nothing submitted yet</span>
                <span className="mt-1 block">
                  Add your opening hours, services and prices first — those are what callers
                  ask about.
                </span>
              </>
            }
          />
        ) : (
          <ul className="divide-y divide-line">
            {uploadRows?.map((upload) => (
              <UploadRow
                key={upload.id}
                upload={upload}
                agentName={lookup(agentNames, upload.agent_id) ?? null}
              />
            ))}
            {facts?.map((source) => (
              <FactRow
                key={source.id}
                source={source}
                agentName={lookup(agentNames, source.agent_id) ?? null}
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
