"use client";

import type { ComponentType } from "react";
import { Archive, CheckCircle2, CircleHelp, Clock, Type, XCircle } from "lucide-react";

import { ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import type { useKbChunks, useKbSources } from "@/lib/api/kb";
import { lookup } from "@/lib/lookup";

type Source = NonNullable<ReturnType<typeof useKbSources>["data"]>[number];
type Chunks = ReturnType<typeof useKbChunks>;

interface StatusCopy {
  label: string;
  /** Badge palette. Semantic rather than branded — this is a verdict, not navigation. */
  tone: string;
  icon: ComponentType<{ className?: string }>;
}

/** A state we cannot name, and the archived state, share the quietest treatment. */
const NEUTRAL_BADGE = "bg-ink/[0.05] text-ink-muted";

/**
 * What a typed fact's status means to the person who typed it. Since D-658 an account
 * member's own fact is approved on submission, so "In review" now appears only on content
 * an operator added or a view-as session submitted.
 */
const STATUS_COPY: Record<string, StatusCopy> = {
  pending_approval: { label: "In review", tone: "bg-warn-soft text-warn", icon: Clock },
  approved: { label: "Approved, not live yet", tone: NEUTRAL_BADGE, icon: CheckCircle2 },
  rejected: { label: "Not accepted", tone: "bg-danger-soft text-danger", icon: XCircle },
  archived: { label: "Replaced by a newer version", tone: NEUTRAL_BADGE, icon: Archive },
};

/**
 * One typed fact in the sources list, with its preview of what the agent was given.
 *
 * The preview is the chunks the agent actually holds, from the same route the upload
 * check uses — not a second rendering of the text the client typed.
 */
export function FactRow({
  source,
  open,
  onToggle,
  chunks,
}: {
  source: Source;
  open: boolean;
  onToggle: () => void;
  /** The preview read, shared by the list: only the open row's chunks are fetched. */
  chunks: Chunks;
}) {
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <Type aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="break-words text-sm font-medium text-ink">{source.name}</span>
            <SourceBadge source={source} />
          </div>
          <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-ink-faint">
            <span>Typed fact</span>
            <span className="tabular-nums">v{source.version}</span>
            <span className="tabular-nums">
              {formatCount(source.chunks)} {source.chunks === 1 ? "answer" : "answers"}
            </span>
            {source.published_at && (
              <span className="whitespace-nowrap">Published {formatIST(source.published_at)}</span>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="press shrink-0 rounded-md px-2 py-1 text-xs font-medium text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {open ? "Hide" : "Preview"}
        </button>
      </div>
      {open && (
        <div className="mt-3 rounded-lg bg-surface-muted p-3 sm:ml-7">
          {/* §52: a failed or paused preview is a refusal, never "nothing in this one". */}
          {chunks.isLoading ? (
            <Skeleton rows={2} />
          ) : chunks.error || !chunks.data ? (
            <ProblemNotice
              error={chunks.error ?? new Error("This preview could not be loaded.")}
              onRetry={() => void chunks.refetch()}
            />
          ) : chunks.data.length ? (
            <div className="space-y-2">
              {chunks.data.map((chunk) => (
                <div
                  key={chunk.idx}
                  className="border-l-2 border-line pl-3 text-xs text-ink-muted"
                >
                  <p className="break-words">{chunk.content}</p>
                  {/* The English key written beside another script is for SEARCH, and the
                      agent never says it — so it is labelled as such rather than shown as
                      a second answer. */}
                  {chunk.gloss ? (
                    <p className="mt-2 break-words border-t border-line pt-2 text-ink-faint">
                      <span className="font-medium">Auto-translated for search</span> — not
                      spoken by your agent. {chunk.gloss}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-ink-muted">
              There is nothing in this submission for the agent to say.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function SourceBadge({ source }: { source: { status: string; is_active: boolean } }) {
  if (source.is_active) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2 py-0.5 text-xs font-semibold text-brand-strong">
        {/* `is_active` is the publish, not the review: only a published source is live. */}
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-bright" />
        Live
      </span>
    );
  }
  // A status this build cannot name fails VISIBLE, with the server's own word.
  // `lookup()`: a wire string indexing a literal walks the prototype chain (lib/lookup.ts).
  const copy = lookup(STATUS_COPY, source.status) ?? {
    label: source.status,
    tone: NEUTRAL_BADGE,
    icon: CircleHelp,
  };
  const Icon = copy.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${copy.tone}`}
    >
      <Icon aria-hidden className="h-3 w-3" />
      {copy.label}
    </span>
  );
}
