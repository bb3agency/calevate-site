"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";

import { useActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { PipMark } from "@/components/illustration/pip";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  useCreateFollowUp,
  useFollowUpStarters,
  type FollowUpStarterOut,
} from "@/lib/api/followUps";
import { openAssistant } from "@/lib/copilot/launcher";

import { triggerWords } from "./followUpCopy";

/** What "New Follow-up" puts in Pip's ask box. Prefilled, never sent. */
export const NEW_FOLLOW_UP_PROMPT = "Make a new Follow-up. Describe what should happen to a lead: ";

/** Opens Pip with the request written; the owner finishes the sentence and presses Ask. */
export function NewFollowUpButton() {
  return (
    <button
      type="button"
      className={`${PRIMARY_BUTTON} inline-flex items-center gap-1.5`}
      onClick={() => openAssistant({ prompt: NEW_FOLLOW_UP_PROMPT })}
    >
      <PipMark size={16} className="shrink-0" />
      New Follow-up
    </button>
  );
}

/**
 * The ready-made Follow-ups, filled in for this account by the server. Choosing one makes
 * a DRAFT and opens it: nothing runs until the owner publishes it there. A starter the
 * account already has is not offered twice.
 */
export function Starters({
  session,
  href,
  taken,
}: {
  session: Session;
  href: (path: string) => string;
  taken: ReadonlySet<string>;
}) {
  const router = useRouter();
  const starters = useFollowUpStarters(session);
  const create = useCreateFollowUp(session);
  const feedback = useActionFeedback(create, { errorTitle: "Could not make that Follow-up" });
  const [chosen, setChosen] = useState<string | null>(null);

  const choose = (starter: FollowUpStarterOut) => {
    setChosen(starter.key);
    create.mutate(
      {
        name: starter.name,
        trigger: starter.trigger,
        steps: starter.steps,
        settings: starter.settings,
        starter: starter.key,
      },
      { onSuccess: (made) => router.push(href(`/c/${session.orgSlug}/follow-ups/${made.id}`)) },
    );
  };

  const offered = starters.data?.items.filter((starter) => !taken.has(starter.key));
  if (offered && offered.length === 0) return null;

  return (
    <Section title="Ready-made" headingLevel={2} description="Start from one, then change it.">
      {starters.isLoading ? (
        <Skeleton rows={3} label="Loading the ready-made Follow-ups" />
      ) : starters.error ? (
        <ProblemNotice error={starters.error} onRetry={() => void starters.refetch()} />
      ) : offered ? (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {offered.map((starter) => {
            const busy = feedback.status === "pending" && chosen === starter.key;
            return (
              <li key={starter.key}>
                <button
                  type="button"
                  disabled={feedback.status === "pending"}
                  onClick={() => choose(starter)}
                  aria-label={`Use ready-made: ${starter.name}`}
                  className="press flex w-full items-start gap-3 rounded-lg border border-line px-3 py-2.5 text-left transition-colors duration-(--duration-fast) hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-60 touch:min-h-11"
                >
                  <Plus aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
                  <span className="min-w-0">
                    <span className="block font-medium text-ink">{busy ? "Making it…" : starter.name}</span>
                    <span className="block text-meta text-ink-muted">
                      {triggerWords(starter.trigger)} · {starter.steps.length}{" "}
                      {starter.steps.length === 1 ? "step" : "steps"}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </Section>
  );
}
