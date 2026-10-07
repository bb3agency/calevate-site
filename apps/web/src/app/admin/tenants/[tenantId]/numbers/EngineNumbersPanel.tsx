"use client";

import { ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import { useTenantEngineNumbers } from "@/lib/api/numbers";

/**
 * The numbers held in the voice platform's own console, for a platform that rents numbers
 * and points them at agents only there (ThinnestAI, D-678).
 *
 * On such a platform this console cannot buy a number or say which agent answers it: the
 * platform refuses both by name. So this panel shows what the platform holds that this
 * client's agents answer or that nobody answers yet, which of this client's agents the
 * platform knows and by what id, and the console steps — instead of a buy button that would
 * refuse. Renders nothing on a platform whose numbers are recorded and routed here.
 */
export function EngineNumbersPanel({ tenantId }: { tenantId: string }) {
  const engine = useTenantEngineNumbers(tenantId);

  if (engine.isLoading) return <Skeleton rows={2} />;
  if (engine.error) {
    return <ProblemNotice error={engine.error} onRetry={() => void engine.refetch()} />;
  }
  const data = engine.data;
  if (!data || !data.managed_in_engine_console) return null;
  const platform = data.platform ?? "the voice platform";

  return (
    <section
      aria-labelledby="engine-numbers-heading"
      className="space-y-4 rounded-card border border-line bg-surface p-4 sm:p-6"
    >
      <div>
        <h2 id="engine-numbers-heading" className="text-base font-semibold text-ink">
          Numbers on {platform}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          This deployment&apos;s calls run on {platform}. Numbers are rented and pointed at
          agents in the {platform} console, not here — the list below is what {platform}{" "}
          holds right now.
        </p>
      </div>

      {data.numbers.length === 0 ? (
        <p className="rounded-card border border-dashed border-line p-3 text-sm text-ink-muted">
          {platform} holds no number for this client&apos;s agents and none that is free to
          attach. Follow the steps below to rent one.
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line">
          {data.numbers.map((number) => (
            <li key={number.e164} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
              <span className="font-mono text-ink">{formatPhone(number.e164)}</span>
              {number.provider && (
                <span className="text-xs text-ink-muted">{number.provider}</span>
              )}
              <span className="ml-auto text-ink-muted">
                {number.agent_name
                  ? `Answered by ${number.agent_name}`
                  : number.unassigned
                    ? "Nobody answers it yet"
                    : "Answered by an agent outside this client"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {data.other_numbers > 0 && (
        <p className="text-xs text-ink-faint">
          {data.other_numbers === 1
            ? "One more number on the account is answered by another client's agent and is not shown."
            : `${data.other_numbers} more numbers on the account are answered by other clients' agents and are not shown.`}
        </p>
      )}

      <div>
        <h3 className="text-sm font-semibold text-ink">This client&apos;s published agents</h3>
        {data.agents.length === 0 ? (
          <p className="mt-1 text-sm text-ink-muted">
            None yet. Publish an agent first: it appears in the {platform} console under its
            own name once it is published.
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-line rounded-card border border-line">
            {data.agents.map((agent) => (
              <li
                key={agent.agent_id}
                className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm"
              >
                <span className="font-medium text-ink">{agent.name}</span>
                <span className="font-mono text-xs text-ink-muted">{agent.engine_agent_ref}</span>
                <span className="ml-auto text-ink-muted">
                  {agent.answers_a_number ? "Answers a number" : "Answers no number yet"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-ink">Rent a number and attach it</h3>
        <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-ink-muted">
          {data.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {data.notes.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-ink-faint">
            {data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
