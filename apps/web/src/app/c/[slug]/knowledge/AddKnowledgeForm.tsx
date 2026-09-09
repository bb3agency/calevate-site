"use client";

import { Send } from "lucide-react";

import { Card } from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import type { Agent } from "@/lib/api/agents";
import { useSubmitKnowledge } from "@/lib/api/kb";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * TEACH IT SOMETHING, IN TYPING — the fastest way to add one fact.
 *
 * Knowledge belongs to ONE agent. Silently posting it against `agents[0]` means a client
 * with two agents teaches the wrong one and waits for an answer the right one will never
 * give — so the choice is shown whenever there is one.
 */
export function AddKnowledgeForm({
  agentOptions,
  selectedAgentId,
  onAgentId,
  hasNoAgents,
  name,
  onName,
  body,
  onBody,
  submit,
  canWrite,
  reason,
}: {
  agentOptions: Agent[];
  selectedAgentId: string;
  onAgentId: (id: string) => void;
  hasNoAgents: boolean;
  name: string;
  onName: (value: string) => void;
  body: string;
  onBody: (value: string) => void;
  submit: ReturnType<typeof useSubmitKnowledge>;
  canWrite: boolean;
  reason: string | null;
}) {
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const valid = useFormValidation();

  return (
    <Card title="Add knowledge">
      <form
        className="space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          if (!selectedAgentId) return;
          submit.mutate(
            { agentId: selectedAgentId, name, body },
            {
              onSuccess: () => {
                onName("");
                onBody("");
              },
            },
          );
        })}
      >
        {hasNoAgents && (
          <p className="rounded-lg border border-line bg-app px-3 py-2 text-xs text-ink-muted">
            There is no agent on this account yet, so there is nothing to teach.
            Your account manager sets the first one up with you.
          </p>
        )}

        {agentOptions.length > 1 ? (
          <label className="block">
            <span className="text-xs font-medium text-ink-muted">
              Which agent should know this
            </span>
            <select
              value={selectedAgentId}
              onChange={(e) => onAgentId(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink"
            >
              {agentOptions.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          /* One agent is still a choice the client should be able to check —
             the submission is filed against it either way. */
          agentOptions.length === 1 && (
            <p className="text-xs text-ink-muted">
              Goes to{" "}
              <span className="font-semibold text-ink">{agentOptions[0]?.name}</span>.
            </p>
          )
        )}

        <input
          {...valid.field("title", "Say what this is about.")}
          /* The copilot field id — what the "filled" outline is drawn on. The
             control is named by its own `aria-label`, so nothing else needs it. */
          id="kb-title"
          required
          minLength={2}
          value={name}
          onChange={(e) => onName(e.target.value)}
          aria-label="What this knowledge is about"
          placeholder={`What is this about? e.g. ${eg.knowledgeTitle}`}
          className="w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
        />
        {valid.error("title")}
        <textarea
          {...valid.field("body", "Write what the agent should say.")}
          id="kb-body"
          required
          minLength={10}
          rows={8}
          value={body}
          onChange={(e) => onBody(e.target.value)}
          aria-label="What the agent should say"
          placeholder={
            "Write it the way you would tell a new receptionist.\n\n" +
            "Leave a blank line between topics."
          }
          className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint"
        />
        {valid.error("body")}
        {/* Chunking is paragraph-aware, so telling the client that changes how
            they write — and what they write is what the agent carries verbatim,
            so better input is the only lever there is. */}
        <p className="text-xs text-ink-muted">
          Submitting a topic that already exists creates a new version; the previous
          one stays until this is approved.
        </p>
        <button
          type="submit"
          /* The length rule is not repeated here — pressing now answers in words
             instead of the button going quietly dead at nine characters. Having no
             agent to teach IS still a dead button, because that one is not about
             an answer the person can correct on this form. */
          disabled={!canWrite || submit.isPending || !selectedAgentId}
          /* The reason travels WITH the control as well as sitting at the top of
             the screen: `RestrictionNote` is above the fold on a phone only by
             luck, and a dead button with the explanation off-screen is the 403 we
             are trying not to ship. */
          title={reason ?? undefined}
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send className="h-3.5 w-3.5" />
          {submit.isPending ? "Submitting…" : "Submit for review"}
        </button>
      </form>
    </Card>

  );
}
