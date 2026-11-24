"use client";

/**
 * KNOWLEDGE GAPS ACROSS EVERYTHING: what callers asked that no agent could answer, across
 * every agent, campaign and line, most asked first (`teach/questions.py`, the list "What your
 * agents know" works through). "Teach an answer" opens that question there, where one answer
 * becomes a fact every agent gives on its next call.
 */

import Link from "next/link";

import { TEXT_ACTION_SM } from "@/components/console/section";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatCount } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { knowledgeQuestionsHref, useTeachQuestions } from "@/lib/api/teachQuestions";

import { ImproveCard } from "../ImproveCard";
import { Quiet, type AccountCardProps } from "./shared";

export const GAPS_TITLE = "Questions no agent could answer";
/** The most asked shown here; the rest are in What your agents know. */
const SHOWN = 5;

export function KnowledgeGapsCard({ slug }: AccountCardProps) {
  const { session, href } = useClientRealm();
  const questions = useTeachQuestions(session);
  const asked = (questions.data?.items ?? []).filter((q) => q.why === "callers");
  return (
    <ImproveCard
      headingLevel={2}
      title={GAPS_TITLE}
      hint="What callers asked across all your agents. Answer once for all of them."
      info="An answer becomes a fact every agent gives on its next call."
    >
      {questions.isLoading ? (
        <Skeleton rows={3} label="Reading what callers asked" />
      ) : !questions.data ? (
        <ProblemNotice error={questions.error} onRetry={() => void questions.refetch()} />
      ) : asked.length === 0 ? (
        <Quiet>Your agents had an answer for everything callers asked.</Quiet>
      ) : (
        <ul className="divide-y divide-line" aria-label={GAPS_TITLE}>
          {asked.slice(0, SHOWN).map((q) => (
            <li key={q.key} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 py-2.5 first:pt-0">
              <div className="min-w-0">
                <p className="text-body text-ink [overflow-wrap:anywhere]">{q.question}</p>
                <p className="text-meta text-ink-muted tabular-nums">
                  Asked on {formatCount(q.callers)} {q.callers === 1 ? "call" : "calls"}
                  {q.agent_ids.length > 1 ? ` to ${formatCount(q.agent_ids.length)} agents` : ""}
                </p>
              </div>
              <Link
                href={href(knowledgeQuestionsHref(slug, q.key))}
                className={SECONDARY_BUTTON_SM}
                aria-label={`Teach an answer: ${q.question}`}
              >
                Teach an answer
              </Link>
            </li>
          ))}
        </ul>
      )}
      <Link href={href(`/c/${slug}/knowledge`)} className={`${TEXT_ACTION_SM} -mx-2 mt-2`}>
        What your agents know
      </Link>
    </ImproveCard>
  );
}
