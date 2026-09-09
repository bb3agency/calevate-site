"use client";

import { useState, type ComponentType } from "react";
import { ChevronDown, ChevronUp, Archive, CheckCircle2, CircleHelp, Clock, XCircle } from "lucide-react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import { useKbChunks, type useKbSources } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

interface StatusCopy {
  label: string;
  /** Badge palette. Semantic rather than branded — this is a verdict, not navigation. */
  tone: string;
  icon: ComponentType<{ className?: string }>;
}

/** A state we cannot name, and the archived state, share the quietest treatment. */
const NEUTRAL_BADGE = "bg-black/5 text-ink-muted dark:bg-white/10";

const STATUS_COPY: Record<string, StatusCopy> = {
  pending_approval: {
    label: "In review",
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
    icon: Clock,
  },
  approved: {
    label: "Approved, not live yet",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
    icon: CheckCircle2,
  },
  rejected: {
    label: "Not accepted",
    tone: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
    icon: XCircle,
  },
  archived: {
    label: "Replaced by a newer version",
    tone: NEUTRAL_BADGE,
    icon: Archive,
  },
};

/**
 * Everything this account has TYPED IN, and what each submission is waiting for.
 *
 * THE TYPED NOTES ONLY — because an uploaded document is a `kb_sources` row too.
 * `create_upload` files every document and link as a source of kind `file`/`url`
 * (`apps/api/kb/uploads.py`), so `/v1/kb/sources` returns them alongside pasted text and
 * this panel used to be the whole list. Listing a document in both places is not merely
 * untidy: the two rows would disagree, because only `UploadList` can see how far the
 * reading has got, so the same price list would read "In review" here and "Being read"
 * two cards up. One row per thing, in the panel that knows the most about it.
 */
export function SubmittedList({
  agentNames,
  sources,
}: {
  agentNames: Record<string, string>;
  sources: ReturnType<typeof useKbSources>;
}) {
  const session = useClientSession();
  const [selected, setSelected] = useState<string | null>(null);
  const chunks = useKbChunks(session, selected);

  /* `?? []` is safe here and nowhere else on this screen: the branch below has already
     refused a failed read, so this line is only reached with an answer in hand. */
  const typedNotes = (sources.data ?? []).filter((source) => source.kind === "text");

  return (
    <>
    {/* A failed first load gets NO card. An empty panel headed "Submitted" is the
        same sentence as "nothing submitted", drawn instead of written, and on this
        screen that sentence tells a client their queued change is not queued. The
        notice above is the whole answer. `sources.data` survives a failed REFETCH,
        and those rows are real — so the guard is on the data, not on the error. */}
    {sources.isLoading ? (
      <Card title="Submitted">
        <Skeleton rows={4} />
      </Card>
    ) : !sources.data ? null : (
      <div>
        <Card title="Submitted" bodyClassName="p-2">
          {typedNotes.length ? (
            <ul className="divide-y divide-line">
              {typedNotes.map((source) => {
                // WHICH agent this teaches, or nothing. Absent rather than guessed
                // while the agent list is loading or has failed: a source attributed
                // to the wrong agent is worse than one attributed to none.
                const agentName = lookup(agentNames, source.agent_id);
                const open = selected === source.id;
                return (
                  <li key={source.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                      <span className="text-sm font-semibold text-ink">{source.name}</span>
                      <span className="text-xs tabular-nums text-ink-faint">
                        v{source.version}
                      </span>
                      <SourceBadge source={source} />
                      <span className="ml-auto flex items-center gap-2 text-xs text-ink-faint">
                        <span className="tabular-nums">
                          {formatCount(source.chunks)}{" "}
                          {source.chunks === 1 ? "answer" : "answers"}
                        </span>
                        {agentName && (
                          <span title={agentName} className="truncate">
                            {agentName}
                          </span>
                        )}
                        {source.published_at && (
                          <span className="whitespace-nowrap">
                            Published {formatIST(source.published_at)}
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={() => setSelected(open ? null : source.id)}
                        aria-expanded={open}
                        className="flex items-center gap-1 rounded-md border border-line px-2 py-1.5 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                      >
                        {open ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                        {open ? "Hide" : "Preview"}
                      </button>
                    </div>

                    {open && (
                      <div className="mt-3 rounded-lg border border-line bg-app p-3">
                        {/* Answers that used to look identical: still fetching, no
                            answer at all, and "the server says there is nothing in
                            here". Only the last is emptiness; the others read to a
                            client as text that arrived blank. "No answer" is a failed
                            read AND a paused query (offline: not loading, `error ===
                            null`, `data === undefined`) — `chunks.data?.length` alone
                            collapsed the paused case into the emptiness sentence, so
                            the refusal owns both non-answers (§52). */}
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
                                className="rounded-md border border-line bg-surface p-2 text-xs text-ink-muted"
                              >
                                {/* The client's OWN words, at whatever length and in
                                    whatever script they typed them. A price list or a
                                    URL with no space in it walked this card off the
                                    side of a phone; `break-words` is the only thing
                                    between an unbroken token and a sideways page. */}
                                <p className="break-words">{chunk.content}</p>
                                {/* THE GLOSS, AND IT IS LABELLED AS A MACHINE'S WORK.
                                    It is a SEARCH AID, not something the agent says:
                                    it exists so a caller who asks in Telugu typed in
                                    English letters can still be found the answer
                                    above. Showing it unlabelled beside the client's
                                    own approved words would read as their words, so
                                    the label is part of the feature rather than
                                    decoration. */}
                                {chunk.gloss ? (
                                  <p className="mt-2 break-words border-t border-line pt-2 text-ink-faint">
                                    <span className="font-medium">
                                      Auto-translated for search
                                    </span>{" "}
                                    — not spoken by your agent. {chunk.gloss}
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
              })}
            </ul>
          ) : (
            <EmptyState
              title="Nothing submitted yet"
              hint="Add your opening hours, services and prices first — those are what callers ask about."
            />
          )}
        </Card>
      </div>
    )}
    </>
  );
}

/**
 * THE two-step ladder this screen exists for (FLOWS §7), and the one thing in this file
 * that must not be simplified:
 *
 *     is_active  →  "Live"       (a caller hears this now)
 *     otherwise  →  status copy  ("In review", "Approved, not live yet", …)
 *
 * `approved` is NOT `live`. Between them sit the version bump and the T0 recompile that
 * splices the fact into the agent's own prompt (FLOWS §7), either of which can still be
 * outstanding — so a badge keyed on `status === "approved"` tells a client the agent is
 * saying something no caller will hear, and they stop chasing the publish. Both fields
 * are on every row, so `tsc` catches nothing here; tests/knowledgeApproval.test.tsx does.
 *
 * There is no engine-side KB sync in that list, and for PASTED TEXT there still is not:
 * publishing a typed note means the T0 prompt and nothing else. ⚠ THE SENTENCE THAT USED
 * TO SIT HERE — "the engine's built-in knowledge base is off and `attach_kb` refuses" —
 * IS NO LONGER TRUE OF THE SCREEN AS A WHOLE. `BOLNA_CAPABILITIES.knowledge_base` is
 * `True` (`apps/api/engine/bolna.py:3261`, D-488) and a DOCUMENT does reach the engine's
 * own knowledge base; that half of the screen is `UploadList`, and its states are the
 * ingest ladder rather than this badge. This ladder is still the whole of what a typed
 * note can do.
 *
 * `SourceOut.status` is plain `string` on the wire, so the copy lookup fails VISIBLE: an
 * unnameable status renders as itself, because a client whose submission is stuck in an
 * unfamiliar state still has to see that it is stuck and quote the word to support.
 * `lookup` rather than a bare index — `STATUS_COPY["constructor"]` is the `Object`
 * function, which `??` does not treat as missing, so the badge rendered with `undefined`
 * copy and a stringified function for its class list (lib/lookup.ts).
 */
function SourceBadge({ source }: { source: { status: string; is_active: boolean } }) {
  if (source.is_active) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2 py-0.5 text-xs font-semibold text-brand-strong">
        {/* The design's live-state pip (globals.css), not an icon: "on air" is a state,
            and the pip is what the console uses for one everywhere else. */}
        <span className="h-1.5 w-1.5 rounded-full bg-brand-bright" />
        Live
      </span>
    );
  }
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
      <Icon className="h-3 w-3" />
      {copy.label}
    </span>
  );
}
