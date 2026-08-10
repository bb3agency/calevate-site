"use client";

import { use, useState } from "react";

import { Card, EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { devSession } from "@/lib/api/client";
import { useAgents, useKbChunks, useKbSources, useSubmitKnowledge } from "@/lib/api/kb";

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  pending_approval: {
    label: "In review",
    tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
  },
  approved: {
    label: "Approved, not live yet",
    tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  },
  rejected: {
    label: "Not accepted",
    tone: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  },
  archived: {
    label: "Replaced by a newer version",
    tone: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  },
};

/**
 * Client-side knowledge (FLOWS §7).
 *
 * The screen is deliberately honest about the approval gate rather than hiding it: a
 * submission shows as "in review" and the copy says why. A client who does not know
 * their change is queued will submit it three more times, and the agent speaks under
 * their PE registration — the wait is a feature they should understand, not a delay
 * they should have to discover.
 */
export default function KnowledgePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const session = devSession(slug);
  const sources = useKbSources(session);
  const agents = useAgents(session);
  const submit = useSubmitKnowledge(session);

  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const chunks = useKbChunks(session, selected);

  const agentId = agents.data?.[0]?.id ?? "";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-50">Knowledge</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          What your agent knows. Everything you add is reviewed by your account manager
          before it goes live.
        </p>
      </div>

      {sources.error && <ProblemNotice error={sources.error} onRetry={() => sources.refetch()} />}
      {submit.error && <ProblemNotice error={submit.error} />}

      <Card title="Add knowledge">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!agentId) return;
            submit.mutate(
              { agentId, name, body },
              { onSuccess: () => { setName(""); setBody(""); } },
            );
          }}
        >
          <input
            required
            minLength={2}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="What is this about? e.g. Clinic hours"
            className="w-full rounded-md border border-slate-200 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <textarea
            required
            minLength={10}
            rows={6}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={
              "Write it the way you would tell a new receptionist.\n\n" +
              "Leave a blank line between topics. Short related topics are grouped " +
              "into one answer; long ones are split."
            }
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <div className="flex items-center justify-between">
            {/* Chunking is paragraph-aware, so telling the client that changes how they
                write — and better input is cheaper than better retrieval. */}
            <p className="text-xs text-slate-500">
              Submitting a topic that already exists creates a new version; the previous
              one stays until this is approved.
            </p>
            <button
              type="submit"
              disabled={submit.isPending || !agentId || body.length < 10}
              className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {submit.isPending ? "Submitting…" : "Submit for review"}
            </button>
          </div>
        </form>
      </Card>

      <Card title="Submitted">
        {sources.isLoading ? (
          <Skeleton rows={4} />
        ) : sources.data?.length ? (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {sources.data.map((source) => {
              const copy = STATUS_COPY[source.status] ?? {
                label: source.status,
                tone: "bg-slate-100 text-slate-700",
              };
              return (
                <li key={source.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                      {source.name}
                    </span>
                    <span className="text-xs text-slate-500">v{source.version}</span>
                    {source.is_active ? (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                        Live
                      </span>
                    ) : (
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${copy.tone}`}>
                        {copy.label}
                      </span>
                    )}
                    <span className="ml-auto text-xs text-slate-500">
                      {source.chunks} {source.chunks === 1 ? "answer" : "answers"} ·{" "}
                      {source.published_at ? formatIST(source.published_at) : "not live yet"}
                    </span>
                    <button
                      type="button"
                      onClick={() => setSelected(selected === source.id ? null : source.id)}
                      className="rounded-md border border-slate-200 px-2 py-0.5 text-xs dark:border-slate-700"
                    >
                      {selected === source.id ? "Hide" : "Preview"}
                    </button>
                  </div>
                  {selected === source.id && (
                    <div className="mt-2 space-y-2">
                      {(chunks.data ?? []).map((chunk) => (
                        <p
                          key={chunk.idx}
                          className="rounded-md bg-slate-50 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                        >
                          {chunk.content}
                        </p>
                      ))}
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
  );
}
