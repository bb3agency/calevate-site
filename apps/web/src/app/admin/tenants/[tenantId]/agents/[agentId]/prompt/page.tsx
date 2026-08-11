"use client";

import Link from "next/link";
import { use, useState } from "react";

import { EmptyState, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  usePromptHistory,
  useRollbackPrompt,
  useWritePrompt,
} from "@/lib/api/prompts";

/**
 * Prompt version history + rollback for one agent (admin surface, D-22: prompt
 * mutations cannot exist behind read-only impersonation).
 *
 * Rollback here is copy-forward, never pointer-rewind (FLOWS §7): the button creates
 * a NEW version carrying the old content, so history stays linear and audited. The
 * page receives agentId from the route — there is no agent-list endpoint on this path.
 */
export default function AgentPromptPage({
  params,
}: {
  params: Promise<{ tenantId: string; agentId: string }>;
}) {
  const { tenantId, agentId } = use(params);
  const history = usePromptHistory(tenantId, agentId);
  const write = useWritePrompt(tenantId, agentId);
  const rollback = useRollbackPrompt(tenantId, agentId);

  const [body, setBody] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <div className="space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="text-sm text-sky-400 hover:underline"
        >
          ← Client
        </Link>
        <h1 className="mt-1 text-xl font-semibold">Agent prompt</h1>
        <p className="text-sm text-slate-400">
          Every save is a new immutable version; the live one is just a pointer.
        </p>
      </div>

      {history.error && (
        <ProblemNotice error={history.error} onRetry={() => history.refetch()} />
      )}
      {rollback.error && <ProblemNotice error={rollback.error} />}

      {/* Same reason as the tenant page: local panel styling, not the client-realm Card. */}
      <section className="rounded-xl border border-slate-800 bg-slate-900">
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">Version history</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Rolling back creates a NEW version with that content — history is never
            rewritten.
          </p>
        </header>
        <div className="p-4">
          {history.isLoading ? (
            <Skeleton rows={4} />
          ) : history.data?.length ? (
            <ul className="space-y-2">
              {history.data.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 p-3"
                >
                  <span className="font-mono text-sm font-semibold text-slate-100">
                    v{entry.version}
                  </span>
                  {entry.active && (
                    <span className="rounded bg-emerald-500 px-1.5 py-0.5 text-xs font-medium text-emerald-950">
                      live
                    </span>
                  )}
                  <span className="text-xs text-slate-500">
                    {formatIST(entry.created_at)}
                  </span>
                  {entry.notes && (
                    <span className="text-xs text-slate-400">{entry.notes}</span>
                  )}
                  {!entry.active && (
                    <button
                      type="button"
                      disabled={rollback.isPending}
                      onClick={() => rollback.mutate({ version: entry.version })}
                      className="ml-auto rounded-md border border-slate-700 px-2 py-1 text-xs disabled:opacity-50"
                    >
                      Roll back to this
                    </button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No prompt versions yet"
              hint="Write the first version below."
            />
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-800 bg-slate-900">
        <header className="border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">New version</h2>
        </header>
        <div className="p-4">
          {write.error && <ProblemNotice error={write.error} />}
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              write.mutate(
                { body, ...(notes.trim() ? { notes: notes.trim() } : {}) },
                {
                  onSuccess: () => {
                    setBody("");
                    setNotes("");
                  },
                },
              );
            }}
          >
            <textarea
              required
              minLength={20}
              rows={8}
              value={body}
              onChange={(ev) => setBody(ev.target.value)}
              placeholder="The full system prompt for this agent (min 20 characters)."
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            />
            <input
              value={notes}
              onChange={(ev) => setNotes(ev.target.value)}
              maxLength={200}
              placeholder="Notes (optional) — what changed and why"
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200"
            />
            <button
              type="submit"
              disabled={write.isPending || body.length < 20}
              className="rounded-md bg-slate-100 px-3 py-1 text-xs font-medium text-slate-900 disabled:opacity-50"
            >
              Save as new version
            </button>
          </form>
          <p className="mt-2 text-xs text-slate-500">
            If the agent is live, this goes to the voice platform immediately.
          </p>
        </div>
      </section>
    </div>
  );
}
