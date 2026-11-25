"use client";

import { useQuery } from "@tanstack/react-query";

import { Section } from "@/components/console/section";
import { NoticeBox, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { adminSession } from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import { untilRefused } from "@/lib/api/queryRetry";
import type { components } from "@/lib/api/schema";

export type EngineHealth = components["schemas"]["EngineHealthOut"];

export const ENGINE_HEALTH_PATH = "/v1/ops/engine-health";

/** Every 15 seconds while held or failing, so recovery shows as it happens; a minute otherwise. */
export function useEngineHealth() {
  return useQuery({
    queryKey: ["admin", "ops", "engine-health"],
    queryFn: () => apiRequest<EngineHealth>(adminSession(), ENGINE_HEALTH_PATH),
    refetchInterval: untilRefused((query: { state: { data?: EngineHealth } }) => {
      const data = query.state.data;
      return data?.held || data?.run_is_outage ? 15_000 : 60_000;
    }),
  });
}

const KIND_WORDS: Record<string, string> = {
  unreachable: "no answer",
  server_error: "answered with a server error",
};

/**
 * Whether the voice engine is answering. The dial hold is what clients see (their "calls are
 * paused" banner, Call me paused); the run of failures across every request says what failed
 * last and where, which is where an operator starts.
 */
export function EngineHealthPanel() {
  const health = useEngineHealth();
  const title = "Is the voice platform answering?";
  if (health.isLoading) {
    return (
      <Section title={title}>
        <Skeleton rows={2} />
      </Section>
    );
  }
  if (health.error || !health.data) {
    return (
      <Section title={title}>
        <ProblemNotice error={health.error} onRetry={() => void health.refetch()} />
      </Section>
    );
  }
  const data = health.data;
  return (
    <Section
      title={title}
      info={
        <p>
          {data.hold_after_dial_failures} failed dials in a row hold every dial on the platform
          (page <code>engine_dial_hold</code>); clients then see &ldquo;calls are paused&rdquo; and
          their test calls are paused. A read probe every 30 seconds lifts it. Separately,{" "}
          {data.outage_after_failures} failed requests of any kind in a row is an outage run: saved
          changes wait it out instead of giving up.
        </p>
      }
    >
      {data.held ? (
        <NoticeBox tone="stop" title={`Dials held since ${formatIST(data.held_since)}`}>
          Clients see the paused banner. It lifts by itself when the platform answers.
        </NoticeBox>
      ) : data.run_is_outage ? (
        <NoticeBox tone="warn" title={`Requests failing since ${formatIST(data.run_since)}`}>
          {data.consecutive_failures} in a row. Dials are not held yet.
        </NoticeBox>
      ) : (
        <p role="status" className="text-body font-medium text-ink">
          Answering
        </p>
      )}
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-body sm:grid-cols-[max-content_1fr]">
        <dt className="text-ink-muted">Failed in a row</dt>
        <dd className="text-ink tabular-nums">{data.consecutive_failures}</dd>
        <dt className="text-ink-muted">Last failure</dt>
        <dd className="text-ink">
          {data.last_failure_at ? (
            <>
              {formatIST(data.last_failure_at)}
              {data.last_kind ? `, ${KIND_WORDS[data.last_kind] ?? data.last_kind}` : ""}
              {data.last_error ? (
                <>
                  {" "}
                  (<code>{data.last_error}</code>
                  {data.last_route ? (
                    <>
                      {" "}
                      on <code>{data.last_route}</code>
                    </>
                  ) : null}
                  )
                </>
              ) : null}
            </>
          ) : (
            "None recorded"
          )}
        </dd>
        <dt className="text-ink-muted">Last {data.window_minutes} minutes</dt>
        <dd className="text-ink tabular-nums">
          {data.window_unreachable} no answer, {data.window_server_errors} server errors (spike page
          at {data.spike_threshold})
        </dd>
        <dt className="text-ink-muted">Hold page</dt>
        <dd className="text-ink">
          {data.alarm_open_since ? `Open since ${formatIST(data.alarm_open_since)}` : "Not open"}
        </dd>
        {data.recovered_at && (
          <>
            <dt className="text-ink-muted">Last outage run ended</dt>
            <dd className="text-ink">{formatIST(data.recovered_at)}</dd>
          </>
        )}
      </dl>
    </Section>
  );
}
