"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Quote, Sparkles } from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  useDismissGap,
  useKnowledgeGaps,
  useTeachGap,
  type GapSignal,
  type KnowledgeGap,
} from "@/lib/api/knowledgeGaps";
import { useFormValidation } from "@/components/formValidation";
import { useClientSession } from "@/lib/api/session";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import type { VerticalExamples } from "@/lib/verticalExamples";

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
}: {
  agentId?: string;
  className?: string;
}) {
  const session = useClientSession();
  // This tenant's trade, not a clinic's — see `lib/verticalExamples.ts`.
  const eg = useVerticalExamples();
  const gaps = useKnowledgeGaps(session, { agentId, status: "open", limit: 20 });

  const title = agentId ? "Where this agent struggled" : "Where your agents struggled";

  if (gaps.isLoading) {
    return (
      <Card title={title} className={className}>
        <Skeleton rows={4} />
      </Card>
    );
  }

  if (gaps.error || !gaps.data) {
    return (
      <Card title={title} className={className}>
        <ProblemNotice
          error={gaps.error ?? new Error("Your knowledge gaps did not load.")}
          onRetry={() => void gaps.refetch()}
        />
      </Card>
    );
  }

  const { items, open_count } = gaps.data;

  return (
    <Card
      title={title}
      className={className}
      action={
        open_count > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-strong">
            <AlertTriangle aria-hidden className="h-3.5 w-3.5" />
            {open_count} need{open_count === 1 ? "s" : ""} attention
          </span>
        ) : undefined
      }
      bodyClassName="p-2 sm:p-3"
    >
      <p className="px-2 pb-3 pt-1 text-[12px] text-ink-muted">
        Found automatically from real conversations — not guessed. Each one will keep
        happening until you teach the answer.
      </p>
      {items.length === 0 ? (
        <EmptyState
          title="Nothing unanswered"
          hint="When an agent tells a caller it doesn't know something, it shows up here so you can teach it."
        />
      ) : (
        <ul className="space-y-2" aria-label="Knowledge gaps needing attention">
          {items.map((gap) => (
            <GapRow eg={eg} key={gap.id} gap={gap} showAgent={!agentId} />
          ))}
        </ul>
      )}
    </Card>
  );
}

const SIGNAL_BADGE: Record<GapSignal, string> = {
  dont_know: "DIDN'T KNOW THIS",
  deferred_channel: "PUNTED TO WHATSAPP / CALLBACK",
  unanswered_question: "LEFT UNANSWERED",
};

function GapRow({
  gap,
  showAgent,
  eg,
}: {
  gap: KnowledgeGap;
  showAgent: boolean;
  /** This tenant's examples, passed down rather than re-read: one `/v1/me` per screen. */
  eg: VerticalExamples;
}) {
  const session = useClientSession();
  const dismiss = useDismissGap(session);
  const teach = useTeachGap(session);
  const [teaching, setTeaching] = useState(false);
  const [answer, setAnswer] = useState("");
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
  const error = dismiss.error ?? teach.error;

  return (
    <li className="rounded-xl border border-line bg-surface p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="inline-flex items-center rounded-md bg-brand-soft px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-strong">
            {SIGNAL_BADGE[gap.signal]}
          </span>
          {/* `h3`, not `h4`. This row sits inside a `Card`, whose title is the `h2`, so
              `h4` skips a level — WCAG 2.2 1.3.1 Info and Relationships (Level A), and
              axe's `heading-order` reports it as soon as a screen renders this card after
              any other heading. UX-DOCTRINE §2: heading level is a property of where the
              component is allowed to be used, and this component is only ever used inside
              a card. */}
          <h3 className="mt-1.5 truncate text-sm font-semibold text-ink">{gap.topic_label}</h3>
          {showAgent && gap.agent_name ? (
            <p className="text-[12px] text-ink-muted">{gap.agent_name}</p>
          ) : null}
        </div>
        <span className="shrink-0 rounded-full bg-black/[0.04] px-2.5 py-1 text-[11px] font-medium tabular-nums text-ink-muted dark:bg-white/5">
          {gap.occurrence_count}× on {gap.call_count} call{gap.call_count === 1 ? "" : "s"}
        </span>
      </div>

      <figure className="mt-2 border-l-2 border-line pl-3">
        <blockquote className="flex gap-1.5 text-[13px] italic text-ink-muted">
          <Quote aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <span className="min-w-0">{gap.example_answer}</span>
        </blockquote>
      </figure>

      {error ? (
        <div className="mt-2">
          <ProblemNotice error={error} />
        </div>
      ) : null}

      {teaching ? (
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
          <label htmlFor={`teach-${gap.id}`} className="block text-[12px] font-medium text-ink-muted">
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
            This is saved as a draft for your agent&apos;s knowledge and reviewed before it
            goes live.
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
            <Sparkles aria-hidden className="mr-1 h-3.5 w-3.5" />
            Teach this
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
