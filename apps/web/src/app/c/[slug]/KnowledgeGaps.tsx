"use client";

import { Section } from "@/components/console/section";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import {
  FIELD,
  PRIMARY_BUTTON_SM,
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
 * "Where the agents struggled on real calls" — the URGENT insights surface.
 *
 * A gap is a question a live agent could not answer, found automatically from the actual
 * (redacted) conversation — never guessed. It is urgent because the same question recurs on
 * every future call until it is taught, so this card sits on the dashboard HOME (all
 * agents) as well as on the per-agent page (`agentId` set).
 *
 * The quotes are the agent's own deflection and the caller's question, both REDACTED
 * server-side (hard rule 6). Every number comes from the API — `occurrence_count` and
 * `call_count` are the "N× on M calls" — and nothing on this card is computed from a capped
 * page: `open_count` is the server's own tally.
 */
export function KnowledgeGaps({
  agentId,
  className,
  hideWhenClear = false,
  headingLevel = 2,
}: {
  agentId?: string;
  className?: string;
  /** 3 inside an agent's Training tab, whose tab label is the h2; its rows go one lower. */
  headingLevel?: 2 | 3;
  /** Render nothing until there is something to teach: the dashboard home shows this card
   *  only when an agent actually struggled. The agent page keeps the calm line. */
  hideWhenClear?: boolean;
}) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const gaps = useKnowledgeGaps(session, { agentId, status: "open", limit: 20 });
  // Reading gaps is `calls:read`; teaching and dismissing are `kb:write`, which staff hold
  // only when their owner has switched curation on (`/v1/me` reports the effective set).
  const write = useWriteAccess(session, "kb:write", "teach or dismiss these");

  const title = agentId ? "Where it struggled on real calls" : "Where your agents struggled";
  // A gap found while the screen is open enters softly (D-774); the list on load does not.
  const enter = useEnterClass(gaps.data ? gaps.data.items.map((gap) => gap.id) : null);

  if (gaps.isLoading) {
    if (hideWhenClear) return null;
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
          error={gaps.error ?? new Error("Your knowledge gaps did not load.")}
          onRetry={() => void gaps.refetch()}
        />
      </Section>
    );
  }

  const { items, open_count } = gaps.data;
  if (hideWhenClear && items.length === 0 && open_count === 0) return null;

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
        <ul className="divide-y divide-line" aria-label="Knowledge gaps needing attention">
          {items.map((gap) => (
            <GapRow
              eg={eg}
              key={gap.id}
              enterClass={enter(gap.id)}
              gap={gap}
              showAgent={!agentId}
              canWrite={write.allowed}
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

function GapRow({
  gap,
  showAgent,
  canWrite,
  eg,
  enterClass,
  rowHeading: RowHeading,
}: {
  enterClass: string;
  rowHeading: "h3" | "h4";
  gap: KnowledgeGap;
  showAgent: boolean;
  canWrite: boolean;
  /** This tenant's examples, passed down rather than re-read: one `/v1/me` per screen. */
  eg: VerticalExamples;
}) {
  const session = useClientSession();
  const dismiss = useDismissGap(session);
  const teach = useTeachGap(session);
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

  const busy = dismiss.isPending || teach.isPending;
  const error = dismiss.error ?? teach.error ?? failed?.error ?? null;

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
          {showAgent && gap.agent_name ? (
            <p className="text-meta text-ink-muted">{gap.agent_name}</p>
          ) : null}
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
            teach.mutate(
              { gapId: gap.id, answer: answer.trim() },
              { onSuccess: () => setTeaching(false) },
            );
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
          <p className="text-[11px] text-ink-faint">
            This is added to your agent&apos;s knowledge and goes to your agent without
            review.
          </p>
          <div className="flex gap-2">
            <button type="submit" className={PRIMARY_BUTTON_SM} disabled={busy}>
              {teach.isPending ? "Saving…" : "Save answer"}
            </button>
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
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            onClick={() => setTeaching(true)}
            disabled={busy}
          >
            Teach the answer
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => dismiss.mutate({ gapId: gap.id })}
            disabled={busy}
          >
            {dismiss.isPending ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      )}
    </li>
  );
}
