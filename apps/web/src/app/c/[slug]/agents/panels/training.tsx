"use client";

/**
 * WHAT THE AGENT KNOWS — the facts an owner teaches it, and this agent's queue.
 *
 * Split out of `agents/panels.tsx` (UX-DOCTRINE §6). It renders a bare `<section>` rather
 * than its own `Card`: the screen that mounts it decides its container, which is what let
 * the agent workspace place it inside the "Teach it" group without a card nested in a card
 * (UX-DOCTRINE §1 — never nest a Card inside a Card; a panel does not choose its own
 * chrome, the screen that mounts it does).
 */

import { useState } from "react";
import { BookOpen, Clock, Send } from "lucide-react";

import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  Skeleton,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { isDeleted } from "@/lib/agentState";
import { useWriteAccess } from "@/lib/api/hooks";
import { useKbSources, useSubmitKnowledge } from "@/lib/api/kb";
import type { Agent } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/** What a knowledge submission's state means, in the client's words. Mirrors the wording
 *  on `/c/<slug>/knowledge`, which is the screen that owns the full list. */
const KB_STATUS_COPY: Record<string, string> = {
  pending_approval: "In review",
  approved: "Approved, not live yet",
  rejected: "Not accepted",
  archived: "Replaced by a newer version",
};

/**
 * TRAINING — teaching the agent a fact, which is a client's own control.
 *
 * `POST /v1/kb/sources` is client-realm and `kb:write` is held by the OWNER role, so this
 * is a real control rather than a button that would 403. A knowledge source is reviewed
 * before it goes live and cannot change what the agent is instructed to DO, which is why
 * it sits on this side of D-21's line while the script's own authoring surface has its own
 * route.
 *
 * Scoped to THIS agent both ways: the list is filtered to `agent_id`, and the submission
 * is filed against it with no picker at all — the picker exists on `/knowledge`, where the
 * screen is about the whole account. A client who arrived here arrived at one agent.
 */
export function TrainingPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const sources = useKbSources(session);
  const submit = useSubmitKnowledge(session);
  const write = useWriteAccess(session, "kb:write", "teach this agent");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const valid = useFormValidation();

  return (
    <section>
      <p className="text-sm text-ink-muted">
        Facts this agent can answer from — opening hours, prices, what you do and do not
        offer. Everything you add is reviewed by your account manager before callers hear
        it, because the agent speaks under your registration.
      </p>

      {sources.error && (
        <div className="mt-4">
          <ProblemNotice error={sources.error} onRetry={() => void sources.refetch()} />
        </div>
      )}

      <div className="mt-4">
        {sources.isLoading ? (
          <Skeleton rows={3} />
        ) : sources.data ? (
          <AgentKnowledgeList sources={sources.data} agentId={agent.id} />
        ) : null}
      </div>

      {submit.error && (
        <div className="mt-4">
          <ProblemNotice error={submit.error} />
        </div>
      )}

      {/* A retired agent answers nobody, so a form for teaching it one more thing is a
          control with no outcome. The list above stays, because what it knew is part of
          the record of what it did. */}
      {isDeleted(agent) ? (
        <p className="mt-5 border-t border-line pt-5 text-sm text-ink-muted">
          This agent is deleted, so there is nothing to teach it. Bring it back first.
        </p>
      ) : (
        <form
          className="mt-5 space-y-3 border-t border-line pt-5"
          noValidate
          onSubmit={valid.onSubmit(() => {
            submit.mutate(
              { agentId: agent.id, name, body },
              {
                onSuccess: () => {
                  setName("");
                  setBody("");
                },
              },
            );
          })}
        >
          {/* Each message sits outside its wrapping `<label>`: enclosed, it would become
              part of the field's accessible name instead of its description. */}
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>What this is about</span>
              <input
                {...valid.field("title", "Say what this is about.")}
                required
                minLength={2}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={`e.g. ${eg.knowledgeTitle}`}
                className={FIELD}
              />
            </label>
            {valid.error("title")}
          </div>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>What the agent should say</span>
              <textarea
                {...valid.field("body", "Write what the agent should say.")}
                required
                minLength={10}
                rows={6}
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder={
                  "Write it the way you would tell a new receptionist.\n\n" +
                  "Leave a blank line between topics."
                }
                className={`${FIELD} py-2`}
              />
            </label>
            {valid.error("body")}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              /* The length rule is NOT repeated here. A button that goes dead at nine
                 characters explains nothing; pressing it now answers in words. */
              disabled={!write.allowed || submit.isPending}
              /* The reason travels WITH the control: a dead button whose explanation is
                 off-screen is the 403 this pattern exists to avoid shipping. */
              title={write.reason ?? undefined}
              className={PRIMARY_BUTTON}
            >
              <Send aria-hidden className="h-3.5 w-3.5" />
              {submit.isPending ? "Submitting…" : "Submit for review"}
            </button>
            {write.reason && <span className="text-xs text-ink-muted">{write.reason}</span>}
          </div>
        </form>
      )}
    </section>
  );
}

/** This agent's knowledge, from the account-wide list. */
function AgentKnowledgeList({
  sources,
  agentId,
}: {
  sources: ReturnType<typeof useKbSources>["data"] & object;
  agentId: string;
}) {
  const mine = sources.filter((source) => source.agent_id === agentId);
  if (mine.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-app px-3 py-3 text-sm text-ink-muted">
        Nothing taught yet. The agent still handles calls from its script — this is for the
        questions callers ask that the script does not answer.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-line">
      {mine.map((source) => (
        <li key={source.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2.5">
          <BookOpen aria-hidden className="h-3.5 w-3.5 shrink-0 self-center text-ink-faint" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
            {source.name}
          </span>
          <span className="flex items-center gap-1 text-xs text-ink-muted">
            <Clock aria-hidden className="h-3 w-3" />
            {/* A status this build has never seen keeps its own word rather than
                disappearing — read through `lookup` because it is a wire string. */}
            {lookup(KB_STATUS_COPY, source.status) ?? source.status.replace(/_/g, " ")}
          </span>
        </li>
      ))}
    </ul>
  );
}
