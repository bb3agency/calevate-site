"use client";

/**
 * What the agent could not answer on this campaign's calls (D-992), from the same findings
 * the Knowledge screen's "where they struggled" list reads (`teach/struggles.py`). The owner
 * answers here; the answer goes into What your agents know as a note and the campaign picks
 * it, so the next script Pip writes works it in. Updating the script puts it on these calls.
 */

import Link from "next/link";
import { useState } from "react";

import { SearchField } from "@/components/arc/search-field";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST } from "@/components/ui";
import { useAnswerQuestion, useCampaignQuestions, type CampaignQuestion } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { matchesWords } from "./matchWords";
import { NOTE_MAX_CHARS } from "@/lib/textLimits";

const KIND: Record<CampaignQuestion["kind"], string> = {
  didnt_know: "Did not know",
  put_off: "Put it off",
  unanswered: "Left unanswered",
  needed_you: "Needed you",
};

export function CampaignQuestions({
  slug,
  campaignId,
  canWrite,
  refusal,
  onAnswered,
}: {
  slug: string;
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
  /** After an answer is kept: the owner goes to the script to work it in. */
  onAnswered?: () => void;
}) {
  const { session, href } = useClientRealm();
  const questions = useCampaignQuestions(session, campaignId);
  const [query, setQuery] = useState("");
  if (questions.isLoading) return <Skeleton rows={3} label="Loading what the agent could not answer" />;
  if (!questions.data) return <ProblemNotice error={questions.error} onRetry={() => questions.refetch()} />;
  if (questions.data.length === 0) {
    return (
      <p className="text-body text-ink-muted">Nothing yet. Questions it could not answer show here.</p>
    );
  }
  const shown = questions.data.filter((q) => matchesWords(query, [q.topic, q.question, q.answer, KIND[q.kind]]));
  return (
    <div className="space-y-4">
      <p className="flex items-center gap-1 text-meta text-ink-muted">
        <span className="block">Answer once; it goes into What your agents know.</span>
        <InfoTip label="answering a question" align="start">
          Then rewrite or edit the script so the agent says it on calls.
        </InfoTip>
      </p>
      {questions.data.length > 3 && (
        <SearchField label="Search questions" hideLabel value={query} onValueChange={setQuery} placeholder="Search questions" />
      )}
      <ul className="max-w-4xl divide-y divide-line border-y border-line">
        {shown.map((q) => (
          <Question
            key={q.id}
            question={q}
            slug={slug}
            callHref={q.last_call_id ? href(`/c/${slug}/calls/${q.last_call_id}`) : null}
            campaignId={campaignId}
            canWrite={canWrite}
            refusal={refusal}
            onAnswered={onAnswered}
          />
        ))}
        {shown.length === 0 && <li className="text-meta text-ink-muted">No question matches “{query}”.</li>}
      </ul>
    </div>
  );
}

function Question({
  question,
  callHref,
  campaignId,
  canWrite,
  refusal,
  onAnswered,
}: {
  question: CampaignQuestion;
  slug: string;
  callHref: string | null;
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
  onAnswered?: () => void;
}) {
  const { session } = useClientRealm();
  const answer = useAnswerQuestion(session, campaignId);
  useActionFeedback(answer, { errorDisplay: "inline" });
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const submit = () =>
    answer.mutate(
      { topic: question.topic, answer: text.trim() },
      {
        onSuccess: () => {
          setDone(true);
          setOpen(false);
          onAnswered?.();
        },
      },
    );
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-body font-medium text-ink">{question.topic}</p>
        <span className="text-meta text-warn">{KIND[question.kind]}</span>
        <span className="text-meta text-ink-faint">
          {question.times > 1 ? `${question.times} times · ` : ""}last {formatIST(question.last_seen_at)}
        </span>
      </div>
      {question.question && <p className="mt-1 text-meta text-ink-muted">Caller: “{question.question}”</p>}
      {question.answer && <p className="text-meta text-ink-muted">Agent: “{question.answer}”</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {done ? (
          <span className="text-meta font-medium text-brand-strong">Answer added to What your agents know</span>
        ) : (
          <button
            type="button"
            className={open ? SECONDARY_BUTTON_SM : PRIMARY_BUTTON_SM}
            disabled={!canWrite}
            title={refusal}
            onClick={() => setOpen(!open)}
          >
            {open ? "Cancel" : "Answer it"}
          </button>
        )}
        {callHref && (
          <Link href={callHref} className={SECONDARY_BUTTON_SM}>
            Listen to the call
          </Link>
        )}
      </div>
      {open && (
        <div className="mt-3 space-y-2">
          <label className="block text-meta font-medium text-ink">
            What should the agent say?
            <textarea
              className={`${FIELD} mt-1 min-h-24 w-full resize-y`}
              value={text}
              maxLength={NOTE_MAX_CHARS}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          {answer.error != null && <ProblemNotice error={answer.error} />}
          <ActionButton
            variant="primary-sm"
            status={answer.isPending ? "pending" : "idle"}
            pendingLabel="Saving…"
            disabled={!text.trim()}
            onClick={submit}
          >
            Keep this answer
          </ActionButton>
        </div>
      )}
    </li>
  );
}
