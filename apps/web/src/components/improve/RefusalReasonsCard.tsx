"use client";

/**
 * WHY PEOPLE SAID NO (founder, 24 Nov 2026): the reasons the post-call reading counted on this
 * campaign's or line's calls (`calls.refusal_reason`, one of a fixed list, never the caller's
 * words), most first. Each reason gets "Teach an answer": a question-and-answer every agent
 * keeps in its instructions (`POST /v1/kb/facts`, pinned), or, once taught, where it is.
 */

import Link from "next/link";
import { useState } from "react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { FIELD, SECONDARY_BUTTON_SM, formatCount } from "@/components/ui";
import {
  REFUSAL_REASON_QUESTION,
  REFUSAL_REASON_WORDS,
  type RefusalReason,
} from "@/lib/api/improve";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useAddFact, useKnows } from "@/lib/api/teach";

import { ImproveCard, WithDiagnosis, type ImproveCardProps } from "./ImproveCard";

export const REFUSALS_TITLE = "Why people said no";

/** The longest answer a pinned fact holds (`teach/models.MAX_PINNED_ANSWER_CHARS`). */
const ANSWER_MAX = 2000;

export function RefusalReasonsCard({ slug, holder }: Pick<ImproveCardProps, "slug" | "holder">) {
  return (
    <ImproveCard
      title={REFUSALS_TITLE}
      hint="The reasons people gave for no, or not now."
      info="Teach an answer once and every agent can give it on its next call."
    >
      <WithDiagnosis holder={holder} label="Reading why people said no">
        {({ refusal_reasons: reasons, window_days }) =>
          reasons.length === 0 ? (
            <p className="text-meta text-ink-muted">
              No one gave a reason for no in the last {window_days} days.
            </p>
          ) : (
            <ul className="divide-y divide-line" aria-label={REFUSALS_TITLE}>
              {reasons.map((r) => (
                <ReasonRow key={r.reason} slug={slug} reason={r.reason} calls={r.calls} />
              ))}
            </ul>
          )
        }
      </WithDiagnosis>
    </ImproveCard>
  );
}

function ReasonRow({ slug, reason, calls }: { slug: string; reason: RefusalReason; calls: number }) {
  const { session, href } = useClientRealm();
  const knows = useKnows(session);
  const teach = useWriteAccess(session, "kb:write", "teach your agents");
  const add = useAddFact(session);
  const feedback = useActionFeedback(add, { errorDisplay: "inline", successToast: "Answer taught" });
  const [open, setOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const question = REFUSAL_REASON_QUESTION[reason];
  // Whether it is taught is read, never assumed: a failed read says so rather than offering
  // to teach an answer that may already be there.
  const taught = knows.isSuccess && knows.data.facts.some((f) => f.question === question);
  const words = REFUSAL_REASON_WORDS[reason];
  const fieldId = `teach-${reason}`;
  return (
    <li className="py-2.5 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="text-body text-ink">
          {words}{" "}
          <span className="text-meta text-ink-muted tabular-nums">
            · {formatCount(calls)} {calls === 1 ? "call" : "calls"}
          </span>
        </span>
        {knows.isPending ? null : knows.isError ? (
          <span className="flex items-center gap-x-2 text-meta text-ink-muted">
            We could not check whether it is taught.
            <button type="button" className={`${TEXT_ACTION_SM} -mx-2`} onClick={() => void knows.refetch()}>
              Try again
            </button>
          </span>
        ) : taught ? (
          <span className="flex items-center gap-x-2">
            <StatusPill tone="ok">Answer taught</StatusPill>
            <Link href={href(`/c/${slug}/knowledge`)} className={`${TEXT_ACTION_SM} -mx-2`}>
              See it
            </Link>
          </span>
        ) : (
          !open && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!teach.allowed}
              title={teach.reason ?? undefined}
              aria-label={`Teach an answer: ${words}`}
              onClick={() => setOpen(true)}
            >
              Teach an answer
            </button>
          )
        )}
      </div>
      {open && !taught && (
        <form
          noValidate
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            feedback.run({ text: answer.trim(), question, pinned: true });
          }}
        >
          <label htmlFor={fieldId} className="block text-meta font-medium text-ink">
            {question}
          </label>
          <textarea
            id={fieldId}
            className={`${FIELD} min-h-20 w-full resize-y`}
            maxLength={ANSWER_MAX}
            value={answer}
            placeholder="What the agent should say"
            onChange={(e) => setAnswer(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <ActionButton
              type="submit"
              variant="primary-sm"
              status={feedback.status}
              pendingLabel="Saving…"
              successLabel="Saved"
              disabled={!answer.trim()}
            >
              Save answer
            </ActionButton>
            <ActionButton
              variant="secondary-sm"
              disabled={add.isPending}
              onClick={() => setOpen(false)}
            >
              Cancel
            </ActionButton>
          </div>
          {add.error != null && (
            <p role="alert" className="text-meta text-danger">
              {problemToast(add.error, "The answer did not save").description}
            </p>
          )}
        </form>
      )}
    </li>
  );
}
