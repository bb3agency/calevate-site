"use client";

import { HAIRLINE_LIST, StatusPill } from "@/components/admin/kit";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import { useTenantEngineNumbers } from "@/lib/api/numbers";

import { EngineNumberActions } from "./EngineNumberActions";
import { RecordEngineNumber } from "./RecordEngineNumber";

/**
 * The numbers held in the voice platform's own console, for a platform that rents numbers
 * and points them at agents only there (ThinnestAI, D-678).
 *
 * Renting happens in that console; recording and attaching happen here (D-691). So this panel
 * shows what the platform holds that this client's agents answer or that nobody answers
 * yet, offers "Record this number" on each one not yet recorded, names this client's
 * agents the platform knows, and the console steps — instead of a buy button that would
 * refuse. Renders nothing on a platform whose numbers are recorded and routed here.
 */
export function EngineNumbersPanel({
  tenantId,
  canWrite,
}: {
  tenantId: string;
  canWrite: boolean;
}) {
  const engine = useTenantEngineNumbers(tenantId);

  if (engine.isLoading) return <Skeleton rows={2} />;
  if (engine.error) {
    return <ProblemNotice error={engine.error} onRetry={() => void engine.refetch()} />;
  }
  const data = engine.data;
  if (!data || !data.managed_in_engine_console) return null;
  const platform = data.platform ?? "the voice platform";

  return (
    <Section
      title={`Numbers on ${platform}`}
      description={
        <>
          This deployment&apos;s calls run on {platform}. Numbers are rented in the {platform}{" "}
          console; record each one here for this client, then choose its agent below — the
          list is what {platform} holds right now.
        </>
      }
    >
      <div className="space-y-8">

      {data.numbers.length === 0 ? (
        <p className="border-y border-line py-4 text-body text-ink-muted">
          {platform} holds no number for this client&apos;s agents and none that is free to
          attach. Follow the steps below to rent one.
        </p>
      ) : (
        <ul aria-label={`Numbers on ${platform}`} className={HAIRLINE_LIST}>
          {data.numbers.map((number) => (
            <li key={number.e164} className="flex flex-wrap items-center gap-3 py-3 text-body sm:px-2">
              <span className="font-mono text-ink">{formatPhone(number.e164)}</span>
              {number.provider && (
                <span className="text-meta text-ink-muted">{number.provider}</span>
              )}
              {number.platform_held && (
                <StatusPill tone="warn">Held in the platform account (testing only)</StatusPill>
              )}
              <span className="ml-auto text-ink-muted">
                {number.agent_name
                  ? `Answered by ${number.agent_name}`
                  : number.unassigned
                    ? "Nobody answers it yet"
                    : "Answered by an agent outside this client"}
              </span>
              {number.number_id ? (
                <div className="w-full space-y-2">
                  <span className="block text-meta text-ink-muted">Recorded for this client.</span>
                  <EngineNumberActions
                    tenantId={tenantId}
                    numberId={number.number_id}
                    e164={number.e164}
                    canWrite={canWrite}
                  />
                </div>
              ) : (
                <div className="w-full">
                  <RecordEngineNumber
                    tenantId={tenantId}
                    e164={number.e164}
                    agents={data.agents}
                    canWrite={canWrite}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {data.other_numbers > 0 && (
        <p className="text-meta text-ink-muted">
          {data.other_numbers === 1
            ? "One more number on the account is answered by another client's agent and is not shown."
            : `${data.other_numbers} more numbers on the account are answered by other clients' agents and are not shown.`}
        </p>
      )}

      <div>
        <h3 className="text-body font-semibold text-ink">This client&apos;s published agents</h3>
        {data.agents.length === 0 ? (
          <p className="mt-1 text-body text-ink-muted">
            None yet. Publish an agent first: it appears in the {platform} console under its
            own name once it is published.
          </p>
        ) : (
          <ul className={`mt-2 ${HAIRLINE_LIST}`}>
            {data.agents.map((agent) => (
              <li
                key={agent.agent_id}
                className="flex flex-wrap items-center gap-3 py-2.5 text-body sm:px-2"
              >
                <span className="font-medium text-ink">{agent.name}</span>
                <span className="font-mono text-meta text-ink-muted">{agent.engine_agent_ref}</span>
                <span className="ml-auto text-ink-muted">
                  {agent.answers_a_number ? "Answers a number" : "Answers no number yet"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h3 className="text-body font-semibold text-ink">Rent a number and record it</h3>
        <ol className="mt-1 list-decimal space-y-1 pl-5 text-body text-ink-muted">
          {data.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
        {data.notes.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-meta text-ink-muted">
            {data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>
      </div>
    </Section>
  );
}
