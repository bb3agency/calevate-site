"use client";

import { Section } from "@/components/console/section";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import {
  FIELD,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  useDismissGap,
  useKnowledgeGaps,
  useLastGapWriteFailure,
  useTeachGap,
  type GapSignal,
  type KnowledgeGap,
} from "@/lib/api/knowledgeGaps";
import { useFormValidation } from "@/components/formValidation";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import type { VerticalExamples } from "@/lib/verticalExamples";
import { StatusPill } from "@/components/console/statusPill";
import { useEnterClass } from "@/components/live/arrivals";

/**
 * "Where it struggled on real calls" — one agent's open knowledge gaps, on its Training tab.
 *
 * A gap is a question a live agent could not answer, found automatically from the actual
 * (redacted) conversation — never guessed. It is urgent because the same question recurs on
 * every future call until it is taught. The dashboard does not repeat this list: "What needs
 * you today" carries the open count and links here, or to Knowledge when several agents
 * struggled.
 *
 * The quotes are the agent's own deflection and the caller's question, both REDACTED
 * server-side (hard rule 6). Every number comes from the API — `occurrence_count` and
 * `call_count` are the "N× on M calls" — and nothing on this card is computed from a capped
 * page: `open_count` is the server's own tally.
 */
export function KnowledgeGaps({
  agentId,
  className,
  headingLevel = 2,
}: {
  agentId: string;
  className?: string;
  /** 3 inside an agent's Training tab, whose tab label is the h2; its rows go one lower. */
  headingLevel?: 2 | 3;
}) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const gaps = useKnowledgeGaps(session, { agentId, status: "open", limit: 20 });
  // Reading gaps is `calls:read`; teaching and dismissing are `kb:write`, which staff hold
  // only when their owner has switched curation on (`/v1/me` reports the effective set).
  const write = useWriteAccess(session, "kb:write", "teach or dismiss these");
  /*
   * The writes live here, not in the row: both remove the row optimistically, so the row
   * that started one is gone before it settles. The confirmation is a toast because the
   * row leaving is the only other sign; a failure puts the row back and it shows the
   * reason itself (`useLastGapWriteFailure`), so it is not toasted as well.
   */
  const dismiss = useDismissGap(session);
  const teach = useTeachGap(session);
  const dismissFeedback = useActionFeedback(dismiss, {
    errorDisplay: "inline",
    successToast: "Dismissed",
  });
  const teachFeedback = useActionFeedback(teach, {
    errorDisplay: "inline",
    successToast: "Answer saved",
    successDescription: "Your agents will know it in a minute or two.",
  });
  const actions: GapActions = {
    dismiss: (gapId) => dismissFeedback.run({ gapId }),
    teach: (gapId, answer) => teachFeedback.run({ gapId, answer }),
    status: (gapId, kind) =>
      kind === "dismiss"
        ? dismiss.variables?.gapId === gapId
          ? dismissFeedback.status
          : "idle"
        : teach.variables?.gapId === gapId
          ? teachFeedback.status
          : "idle",
  };

  const title = "Where it struggled on real calls";
  // A gap found while the screen is open enters softly (D-774); the list on load does not.
  const enter = useEnterClass(gaps.data ? gaps.data.items.map((gap) => gap.id) : null);

  if (gaps.isLoading) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <Skeleton rows={4} />
      </Section>
    );
  }

  if (gaps.error || !gaps.data) {
    return (
      <Section title={title} headingLevel={headingLevel} className={className}>
        <ProblemNotice
          error={gaps.error ?? new Error("The questions your agents could not answer did not load.")}
          onRetry={() => void gaps.refetch()}
        />
      </Section>
    );
  }

  const { items, open_count } = gaps.data;

  return (
    <Section
      title={title}
      headingLevel={headingLevel}
      className={className}
      info={
        <p>
          Found automatically from real conversations — not guessed. Each one will keep
          happening until you teach the answer.
        </p>
      }
      action={
        open_count > 0 ? (
          <StatusPill tone="warn" className="tabular-nums">
            {open_count} need{open_count === 1 ? "s" : ""} attention
          </StatusPill>
        ) : undefined
      }
    >
      {write.reason && (
        <div className="px-2 pb-3">
          <RestrictionNote reason={write.reason} />
        </div>
      )}
      {items.length === 0 ? (
        /* The calm state is one line, not a block: nothing here needs the owner. */
        <p className="flex items-center gap-2 px-2 pb-1 text-meta text-ink-muted">
          <CheckCircle2 aria-hidden className="h-4 w-4 shrink-0 text-brand-strong" />
          <span>
            <span className="font-medium text-ink">Nothing unanswered</span> — when an agent
            tells a caller it doesn&apos;t know something, it shows up here so you can teach it.
          </span>
        </p>
      ) : (
        <ul className="divide-y divide-line" aria-label="Questions your agents could not answer">
          {items.map((gap) => (
            <GapRow
              eg={eg}
              key={gap.id}
              enterClass={enter(gap.id)}
              gap={gap}
              canWrite={write.allowed}
              actions={actions}
              rowHeading={headingLevel === 3 ? "h4" : "h3"}
            />
          ))}
        </ul>
      )}
    </Section>
  );
}

const SIGNAL_BADGE: Record<GapSignal, string> = {
  dont_know: "Didn't know this",
  deferred_channel: "Put it off to a message or call back",
  unanswered_question: "Left unanswered",
};

interface GapActions {
  dismiss: (gapId: string) => void;
  teach: (gapId: string, answer: string) => void;
  status: (gapId: string, kind: "dismiss" | "teach") => FeedbackStatus;
}

function GapRow({
  gap,
  canWrite,
  actions,
  eg,
  enterClass,
  rowHeading: RowHeading,
}: {
  enterClass: string;
  rowHeading: "h3" | "h4";
  gap: KnowledgeGap;
  canWrite: boolean;
  actions: GapActions;
  /** This tenant's examples, passed down rather than re-read: one `/v1/me` per screen. */
  eg: VerticalExamples;
}) {
  const session = useClientSession();
  // Set when this row was remounted by a rollback: the write that failed belonged to
  // the row the optimistic removal unmounted.
  const failed = useLastGapWriteFailure(session, gap.id);
  const failedTeach = failed?.action === "teach" ? failed.answer : null;
  const [teaching, setTeaching] = useState(failedTeach !== null);
  const [answer, setAnswer] = useState(failedTeach ?? "");
  // The rollback can remount this row a tick before the mutation records its error, so
  // the initial state above may not have seen it yet.
  useEffect(() => {
    if (failedTeach === null) return;
    setTeaching(true);
    setAnswer((typed) => typed || failedTeach);
  }, [failedTeach]);
  const valid = useFormValidation();
  const answerField = valid.field("answer", "Write what the agent should say.");
  const answerRef = useRef<HTMLTextAreaElement>(null);

  // Move focus to the answer box when the teach form opens — the keyboard-user
  // equivalent of `autoFocus`, which jsx-a11y forbids because it fires on page load; this
  // fires only on the deliberate click that reveals the form.
  useEffect(() => {
    if (teaching) answerRef.current?.focus();
  }, [teaching]);

  const teachStatus = actions.status(gap.id, "teach");
  const dismissStatus = actions.status(gap.id, "dismiss");
  const busy = teachStatus === "pending" || dismissStatus === "pending";
  const error = failed?.error ?? null;

  return (
    <li className={`px-2 py-3 ${enterClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="text-meta font-medium text-warn">{SIGNAL_BADGE[gap.signal]}</span>
          {/* One level under the panel's title, never two: a skipped level is WCAG 2.2
              1.3.1 (Level A) and axe's `heading-order`. */}
          <RowHeading
            title={gap.topic_label}
            className="mt-0.5 truncate text-sm font-semibold text-ink"
          >
            {gap.topic_label}
          </RowHeading>
        </div>
        <span className="shrink-0 text-meta tabular-nums text-ink-faint">
          {gap.occurrence_count}× on {gap.call_count} call{gap.call_count === 1 ? "" : "s"}
        </span>
      </div>

      <figure className="mt-2 border-l-2 border-line pl-3">
        <blockquote className="text-meta text-ink-muted">
          &ldquo;<span>{gap.example_answer}</span>&rdquo;
        </blockquote>
      </figure>

      {error ? (
        <div className="mt-2">
          <ProblemNotice error={error} />
        </div>
      ) : null}

      {!canWrite ? null : teaching ? (
        <form
          className="mt-3 space-y-2"
          noValidate
          /* The empty case used to be `if (!answer.trim()) return;` beside a dead
             button: pressing Save did nothing and said nothing, which is a worse
             refusal than the browser bubble the rest of this realm was converted away
             from. The rule is on the control now and it answers in words. */
          onSubmit={valid.onSubmit(() => {
            actions.teach(gap.id, answer.trim());
          })}
        >
          <label htmlFor={`teach-${gap.id}`} className="block text-meta font-medium text-ink-muted">
            What should the agent say next time?
          </label>
          <textarea
            {...answerField}
            required
            id={`teach-${gap.id}`}
            /* Both refs: this screen focuses the box when the panel opens, and the
               validation needs the same node to read the answer off on submit. */
            ref={(node) => {
              answerField.ref(node);
              answerRef.current = node;
            }}
            className={`${FIELD} min-h-[76px]`}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            placeholder={`e.g. ${eg.knowledgeAnswer}`}
          />
          {valid.error("answer")}
          <p className="text-meta text-ink-muted">
            This is added to your agent&apos;s knowledge and goes to your agent without
            review.
          </p>
          <div className="flex gap-2">
            <ActionButton type="submit" variant="primary-sm" status={teachStatus} successLabel="Saved">
              Save answer
            </ActionButton>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setTeaching(false)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-3 flex gap-2">
          {/* Bordered, not filled: it opens the form, and the form's Save is the filled one
              (REDESIGN-2: one filled action per view, bound to the form it submits). */}
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setTeaching(true)}
            disabled={busy}
          >
            Teach the answer
          </button>
          <ActionButton
            variant="secondary-sm"
            status={dismissStatus}
            successLabel="Dismissed"
            onClick={() => actions.dismiss(gap.id)}
          >
            Dismiss
          </ActionButton>
        </div>
      )}
    </li>
  );
}
