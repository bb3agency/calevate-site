"use client";

/**
 * WHAT THE AGENT HAS BEEN TAUGHT ABOUT HOW IT SOUNDS (founder, 17 Nov 2026): the notes its
 * owner wrote after hearing lines in its voice, from any campaign's Call flow or here. Every
 * call it makes follows them, from the next time each of its campaigns and lines is put live
 * (and the agent itself once its script is put live). A note is retired, never deleted.
 */

import { Plus, X } from "lucide-react";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { useRetireVoiceNote, useTeachVoiceNote, useVoiceNotes } from "@/lib/api/voiceNotes";

function languageOf(tag: string): string {
  return tag ? (lookup(LANGUAGE_NAMES, tag) ?? tag) : "Every language";
}

export function AgentVoiceNotes({ agentId, canWrite = true }: { agentId: string; canWrite?: boolean }) {
  const session = useClientSession();
  const notes = useVoiceNotes(session, agentId);
  const teach = useTeachVoiceNote(session, agentId);
  const retire = useRetireVoiceNote(session, agentId);
  const teachFeedback = useActionFeedback(teach, { errorDisplay: "inline", successToast: "Taught" });
  useActionFeedback(retire, { errorTitle: "Could not retire the note", successToast: "No longer followed" });
  const [typed, setTyped] = useState("");

  const items = notes.data?.items ?? [];
  const full = notes.data ? items.length >= notes.data.limit : false;
  const add = () => {
    const note = typed.trim();
    if (!note) return;
    teach.mutate({ note, language: "", source: "Agent page" }, { onSuccess: () => setTyped("") });
  };

  return (
    <section aria-labelledby={`voice-notes-${agentId}`} className="rounded-card border border-series-4/30 bg-series-4/5 p-4">
      <h3 id={`voice-notes-${agentId}`} className="text-body font-semibold text-ink">
        How it should sound
      </h3>
      <p className="mt-0.5 text-meta text-ink-muted">
        What you taught this agent after hearing it, here or in a campaign&apos;s Call flow. Every call it makes follows
        these, from the next time each campaign, line or the agent is put live.
      </p>
      {notes.isLoading && <Skeleton rows={2} label="Loading what it was taught" />}
      {notes.error != null && <ProblemNotice error={notes.error} onRetry={() => notes.refetch()} />}
      {notes.data && items.length === 0 && <p className="mt-3 text-meta text-ink-muted">Nothing taught yet.</p>}
      {items.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-card border border-line bg-surface">
          {items.map((n) => (
            <li key={n.id} className="flex items-start gap-3 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-body text-ink">{n.note}</p>
                <p className="text-[11px] text-ink-faint">
                  {languageOf(n.language)}
                  {n.source ? ` · ${n.source}` : ""} · {formatIST(n.created_at)}
                </p>
              </div>
              {canWrite && (
                <ActionButton
                  variant="text"
                  className="rounded p-1 text-ink-muted hover:bg-ink/[0.06] hover:text-ink"
                  aria-label={`Stop following "${n.note}"`}
                  title="Stop following this (it is kept, not deleted)"
                  status={retire.isPending && retire.variables === n.id ? "pending" : "idle"}
                  pendingLabel={<></>}
                  disabled={retire.isPending && retire.variables !== n.id}
                  onClick={() => retire.mutate(n.id)}
                >
                  <X aria-hidden className="h-4 w-4" />
                </ActionButton>
              )}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="mt-3 flex gap-2">
          <input
            aria-label="Teach it how to sound"
            className={FIELD}
            placeholder="e.g. Speak a little slower, and say our name the way our callers say it"
            value={typed}
            maxLength={300}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <ActionButton
            variant="secondary-sm"
            status={teachFeedback.status}
            successLabel="Taught"
            disabled={!typed.trim() || full}
            onClick={add}
          >
            <Plus aria-hidden className="h-3.5 w-3.5" />
            Teach
          </ActionButton>
        </div>
      )}
      {full && <p className="mt-1 text-meta text-ink-muted">It keeps {notes.data?.limit} notes. Retire one to add another.</p>}
      {teach.error != null && <ProblemNotice error={teach.error} />}
    </section>
  );
}
