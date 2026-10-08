"use client";

import { Send } from "lucide-react";

import { useFormValidation } from "@/components/formValidation";
import { useSubmitKnowledge } from "@/lib/api/kb";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * TEACH IT SOMETHING, IN TYPING — the fastest way to add one fact.
 *
 * There is no agent to choose: the fact joins the business's knowledge, which every agent
 * answers from (D-689). Nor is the form closed while the account has no agent — what is
 * added now reaches the first agent when it is published.
 */
export function AddKnowledgeForm({
  name,
  onName,
  body,
  onBody,
  submit,
  canWrite,
  reason,
}: {
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
    <div>
      <h3 className="text-sm font-semibold text-ink">Add a fact</h3>
      <form
        className="mt-2 space-y-3"
        noValidate
        onSubmit={valid.onSubmit(() => {
          submit.mutate(
            { name, body },
            {
              onSuccess: () => {
                onName("");
                onBody("");
              },
            },
          );
        })}
      >
        <p className="text-xs text-ink-muted">Every one of your agents will know this.</p>

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
          rows={4}
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
          Adding a topic that already exists creates a new version; the previous one
          stays in use until the new one has reached your agents.
        </p>
        <button
          type="submit"
          /* The length rule is not repeated here — pressing now answers in words
             instead of the button going quietly dead at nine characters. */
          disabled={!canWrite || submit.isPending}
          /* The reason travels WITH the control as well as sitting at the top of
             the screen: `RestrictionNote` is above the fold on a phone only by
             luck, and a dead button with the explanation off-screen is the 403 we
             are trying not to ship. */
          title={reason ?? undefined}
          className="press flex w-full items-center justify-center gap-1.5 rounded-md bg-brand-strong sm:w-auto px-4 py-2 text-sm font-semibold text-white enabled:hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:min-h-11"
        >
          <Send className="h-3.5 w-3.5" />
          {submit.isPending ? "Adding…" : "Add to your knowledge"}
        </button>
      </form>
    </div>

  );
}
