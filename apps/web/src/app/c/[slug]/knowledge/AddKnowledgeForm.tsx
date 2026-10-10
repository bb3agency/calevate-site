"use client";

import { Send } from "lucide-react";

import { Section } from "@/components/console/section";
import { useFormValidation } from "@/components/formValidation";
import { FIELD, PRIMARY_BUTTON } from "@/components/ui";
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
    <Section title="Add a fact" description="Every one of your agents will know this.">
      <form
        className="max-w-2xl space-y-4"
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
          className={`${FIELD} mt-0`}
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
            "Write it the way you would tell a new member of your team.\n\n" +
            "Leave a blank line between topics."
          }
          className={`${FIELD} mt-0`}
        />
        {valid.error("body")}
        {/* Chunking is paragraph-aware, so telling the client that changes how
            they write — and what they write is what the agent carries verbatim,
            so better input is the only lever there is. */}
        <p className="-mt-2 text-meta text-ink-muted">
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
          className={`${PRIMARY_BUTTON} mt-2 w-full justify-center sm:w-auto`}
        >
          <Send className="h-3.5 w-3.5" />
          {submit.isPending ? "Adding…" : "Add to your knowledge"}
        </button>
      </form>
    </Section>

  );
}
