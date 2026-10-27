"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { useFormValidation } from "@/components/formValidation";
import { useEnterClass } from "@/components/live/arrivals";
import {
  FIELD,
  FIELD_HINT,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { VoiceButton } from "@/components/voiceButton";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import {
  useAnswerQuestion,
  useDismissQuestion,
  useTeachQuestions,
  type TeachQuestion,
} from "@/lib/api/teachQuestions";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { useVoiceWords } from "./useVoiceWords";




/**
 * QUESTIONS TO ANSWER (D-893, PIP-AGENT-PLAN §5): one checklist of what the agents need,
 * most asked first. Each row opens to answer it in place: keep the draft Pip wrote from the
 * business's own words (named beside it), edit it, type or say an answer, or mark it "Not
 * something we answer". Saving makes it a fact every agent uses on its next call.
 *
 * Every "Add prices"-style link lands here with `focus` set, so the question it named is
 * open and ready to answer rather than a blank page.
 */
export function QuestionsToAnswer({
  agentId,
  focus = null,
  headingLevel = 2,
  className,
}: {
  /** One agent's callers' questions; the account's practice and setup questions too. */
  agentId?: string;
  /** A question key to open first (from a link). */
  focus?: string | null;
  headingLevel?: 2 | 3;
  className?: string;
}) {
  const session = useClientSession();
  const questions = useTeachQuestions(session, agentId);
  const write = useWriteAccess(session, "kb:write", "answer these");
  const title = "Questions to answer";
  const enter = useEnterClass(questions.data ? questions.data.items.map((q) => q.key) : null);

  if (questions.isLoading) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <Skeleton rows={3} label="Loading the questions to answer" />
      </Section>
    );
  }
  if (questions.error || !questions.data) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <ProblemNotice
          error={questions.error ?? new Error("The questions to answer did not load.")}
          onRetry={() => void questions.refetch()}
        />
      </Section>
    );
  }

  const { items, open_count } = questions.data;
  const focusMissing = focus !== null && !items.some((q) => q.key === focus);
  return (
    <Section
      title={title}
      headingLevel={headingLevel}
      className={className}
      action={
        open_count > 0 ? (
          <StatusPill tone="warn" className="tabular-nums">
            {open_count} to answer
          </StatusPill>
        ) : undefined
      }
    >
      {write.reason ? (
        <div className="pb-3">
          <RestrictionNote reason={write.reason} />
        </div>
      ) : null}
      {focusMissing ? (
        <p role="status" className="pb-3 text-meta text-ink-muted">
          That question is already answered.
        </p>
      ) : null}
      {items.length === 0 ? (
        <p className="flex items-center gap-2 text-meta text-ink-muted">
          <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
          <span>
            <span className="font-medium text-ink">All answered.</span> New questions from
            calls show up here.
          </span>
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line" aria-label={title}>
          {items.map((question) => (
            <QuestionRow
              key={question.key}
              question={question}
              canWrite={write.allowed}
              startOpen={question.key === focus}
              enterClass={enter(question.key)}
              rowHeading={headingLevel === 3 ? "h4" : "h3"}
            />
          ))}
        </ul>
      )}
    </Section>
  );
}

function whyLine(question: TeachQuestion): string {
  if (question.why === "callers") {
    return question.callers === 1 ? "1 caller asked" : `${question.callers} callers asked`;
  }
  return question.why === "practice" ? "Practice callers ask this" : "Your setup leaves this open";
}

function QuestionRow({
  question,
  canWrite,
  startOpen,
  enterClass,
  rowHeading: RowHeading,
}: {
  question: TeachQuestion;
  canWrite: boolean;
  startOpen: boolean;
  enterClass: string;
  rowHeading: "h3" | "h4";
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const [open, setOpen] = useState(startOpen);
  const rowRef = useRef<HTMLLIElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!startOpen) return;
    rowRef.current?.scrollIntoView?.({ block: "center" });
  }, [startOpen]);

  return (
    <li ref={rowRef} className={`py-3 ${enterClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <RowHeading className="text-sm font-semibold text-ink [overflow-wrap:anywhere]">
            {question.question}
          </RowHeading>
          {/* A flex row, not a " · " in running text: on a phone the link wraps to its own
              line and a trailing dot was left hanging after the reason. */}
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1 text-meta text-ink-muted">
            <span>{whyLine(question)}</span>
            {question.latest_call_id ? (
              <>
                <Link
                  href={href(`/c/${session.orgSlug}/calls/${question.latest_call_id}`)}
                  className={TEXT_ACTION_SM}
                >
                  Latest call
                </Link>
              </>
            ) : null}
          </p>
        </div>
        {canWrite && !open ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            aria-expanded={false}
            aria-controls={panelId}
            onClick={() => setOpen(true)}
          >
            {question.draft ? "Review answer" : "Answer"}
          </button>
        ) : null}
      </div>
      {canWrite && open ? (
        <div id={panelId}>
          <AnswerForm question={question} focusOnOpen onClose={() => setOpen(false)} />
        </div>
      ) : null}
    </li>
  );
}

function AnswerForm({
  question,
  focusOnOpen,
  onClose,
}: {
  question: TeachQuestion;
  focusOnOpen: boolean;
  onClose: () => void;
}) {
  const session = useClientSession();
  const answer = useAnswerQuestion(session);
  const dismiss = useDismissQuestion(session);
  const answerFeedback = useActionFeedback(answer, {
    errorDisplay: "inline",
    successToast: "Answer saved",
    successDescription: "Your agents use it from their next call.",
  });
  const dismissFeedback = useActionFeedback(dismiss, {
    errorDisplay: "inline",
    successToast: "Removed from the list",
  });
  const [text, setText] = useState(question.draft ?? "");
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const reasonId = useId();
  const valid = useFormValidation();
  const field = valid.field("answer", "Write the answer, or say it.");

  useEffect(() => {
    if (focusOnOpen) boxRef.current?.focus();
  }, [focusOnOpen]);

  // A draft written while the form was open fills an empty box, never one being typed in.
  useEffect(() => {
    if (question.draft) setText((current) => current || (question.draft ?? ""));
  }, [question.draft]);

  const voice = useVoiceWords(
    session,
    useCallback((heard: string) => {
      setText((current) => [current.trim(), heard].filter(Boolean).join(" "));
      boxRef.current?.focus();
    }, []),
  );
  const busy = answer.isPending || dismiss.isPending || voice.listening;
  const keepsDraft = question.draft !== null && text.trim() === question.draft;

  return (
    <div className="mt-3 space-y-3">
      <form
        noValidate
        className="space-y-2"
        onSubmit={valid.onSubmit(() => answerFeedback.run({ key: question.key, answer: text.trim() }))}
      >
        <label htmlFor={inputId} className="sr-only">
          Your answer to: {question.question}
        </label>
        <textarea
          {...field}
          required
          id={inputId}
          ref={(node) => {
            field.ref(node);
            boxRef.current = node;
          }}
          rows={3}
          maxLength={500}
          value={text}
          disabled={busy}
          onChange={(event) => setText(event.target.value)}
          className={`${FIELD} mt-0`}
        />
        {valid.error("answer")}
        {question.draft && question.draft_source_label ? (
          <p className={FIELD_HINT}>
            {ASSISTANT_NAME} drafted this from {question.draft_source_label}.
          </p>
        ) : question.drafting ? (
          <p role="status" className={FIELD_HINT}>
            <span className="text-shimmer">{ASSISTANT_NAME} is drafting an answer…</span>
          </p>
        ) : null}
        {voice.error ? <ProblemNotice error={voice.error} /> : null}
        {voice.failure ? (
          <p role="alert" className="text-sm text-ink">
            {voice.failure}
          </p>
        ) : null}
        {answer.error ? <ProblemNotice error={answer.error} /> : null}
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            type="submit"
            variant="primary-sm"
            status={answerFeedback.status}
            successLabel="Saved"
            disabled={busy}
          >
            {keepsDraft ? "Keep this answer" : "Save answer"}
          </ActionButton>
          <VoiceButton
            disabled={busy}
            onRecorded={voice.record}
            onTypeInstead={() => boxRef.current?.focus()}
            why="Say the answer. Your browser will ask to use the microphone; choose Allow."
          />
          {voice.listening ? (
            <span role="status" className="text-meta text-ink-muted">
              <span className="text-shimmer">Listening…</span>
            </span>
          ) : null}
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>

      {dismissing ? (
        <form
          noValidate
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            dismissFeedback.run({ key: question.key, reason: reason.trim() || null });
          }}
        >
          <label htmlFor={reasonId} className="block text-meta font-medium text-ink-muted">
            Why not? (optional)
          </label>
          <input
            id={reasonId}
            value={reason}
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            className={`${FIELD} mt-0`}
          />
          {dismiss.error ? <ProblemNotice error={dismiss.error} /> : null}
          <div className="flex flex-wrap gap-2">
            <ActionButton
              type="submit"
              variant="secondary-sm"
              status={dismissFeedback.status}
              successLabel="Removed"
              disabled={busy}
            >
              Remove from the list
            </ActionButton>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setDismissing(false)}
              disabled={busy}
            >
              Keep it
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          className={TEXT_ACTION_SM}
          onClick={() => setDismissing(true)}
          disabled={busy}
        >
          Not something we answer
        </button>
      )}
    </div>
  );
}
