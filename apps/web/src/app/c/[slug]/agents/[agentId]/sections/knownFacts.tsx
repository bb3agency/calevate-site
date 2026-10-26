"use client";

/**
 * KNOWS BY HEART / LOOKS UP (D-896): which of the business's facts this agent answers at
 * once and which it looks up while the caller waits. The choice is the server's, made from
 * what this agent's callers ask (`GET /v1/agents/{id}/known-facts`); nothing here ranks.
 * One plain line per fact, no provider named (D-679). Hidden where every fact is in the
 * instructions anyway, so the split would say nothing.
 */

import { Zap } from "lucide-react";

import { Disclosure, ProblemNotice, Skeleton, formatCount, formatCountOf } from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import { useKnownFacts, type KnownFacts } from "@/lib/api/teach";

/** Facts by heart shown before "and N more". */
const BY_HEART_SHOWN = 8;

export function KnownFactsPanel({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const known = useKnownFacts(session, agentId);

  let body;
  if (known.isLoading) body = <Skeleton rows={2} label="Loading what this agent knows by heart" />;
  else if (known.error || !known.data) {
    body = (
      <ProblemNotice
        error={known.error ?? new Error("We could not load what this agent knows by heart.")}
        onRetry={() => void known.refetch()}
      />
    );
  } else if (!known.data.applies) return null;
  else body = <Split data={known.data} />;
  return (
    <section aria-labelledby={`known-facts-${agentId}`} className="space-y-3">
      <h4 id={`known-facts-${agentId}`} className="text-body font-semibold text-ink">
        Knows by heart
      </h4>
      {body}
    </section>
  );
}

function Split({ data }: { data: KnownFacts }) {
  if (!data.enabled) {
    return (
      <p className="text-meta text-ink-muted">
        This agent looks up every fact when a caller asks, which can add a short pause.
      </p>
    );
  }
  const shown = data.by_heart.slice(0, BY_HEART_SHOWN);
  const more = data.by_heart.length - shown.length;
  return (
    <div className="space-y-3">
      <p className="text-meta text-ink-muted">
        {data.by_heart.length === 0
          ? data.computed_at === null
            ? "It is still learning which facts callers ask about most. Check back after its next calls."
            : "No fact is asked about often enough yet, so it looks each one up when asked."
          : `Knows ${formatCountOf(data.by_heart.length, "fact")} by heart, the ones callers ask about most, and answers them at once.`}
      </p>
      {shown.length > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {shown.map((fact) => (
            <li key={fact.text} className="flex items-start gap-2 py-2.5 text-body text-ink">
              <Zap aria-label="Known by heart" className="mt-1 h-3.5 w-3.5 shrink-0 text-brand-strong" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{fact.text}</span>
            </li>
          ))}
        </ul>
      )}
      {more > 0 && (
        <p className="text-meta text-ink-muted">and {formatCountOf(more, "more fact")} by heart</p>
      )}
      {data.looked_up_total > 0 && (
        <Disclosure
          variant="inline"
          headingLevel={4}
          title={`Looks up ${formatCountOf(data.looked_up_total, "fact")} when asked`}
          subtitle="Found during the call, with a short pause before the answer."
        >
          <ul className="divide-y divide-line">
            {data.looked_up.map((text) => (
              <li key={text} className="py-2 text-body text-ink-muted [overflow-wrap:anywhere]">
                {text}
              </li>
            ))}
          </ul>
          {data.looked_up_total > data.looked_up.length && (
            <p className="pt-2 text-meta text-ink-muted">
              and {formatCount(data.looked_up_total - data.looked_up.length)} more
            </p>
          )}
        </Disclosure>
      )}
    </div>
  );
}
