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

/** Every 15 seconds while failing, so an operator watching recovery sees it; a minute otherwise. */
export function useEngineHealth() {
  return useQuery({
    queryKey: ["admin", "ops", "engine-health"],
    queryFn: () => apiRequest<EngineHealth>(adminSession(), ENGINE_HEALTH_PATH),
    refetchInterval: untilRefused((query) => (query.state.data?.failing ? 15_000 : 60_000)),
  });
}

const KIND_WORDS: Record<string, string> = {
  unreachable: "no answer",
  server_error: "answered with a server error",
};

/**
 * Whether the voice engine is answering, from the same read the client banner and the
 * test-call buttons use (`engine/outage.py`), with what an operator needs to start: since
 * when, how many in a row, the last error and its route, the paging alarm's window.
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
          {data.outage_after_failures} failed requests in a row, with no answer between them and the
          newest under five minutes old, is an outage: clients then see a &ldquo;calls are
          paused&rdquo; banner and their test calls are paused. The first answer ends it. The page
          (<code>engine_error_spike</code>) needs {data.spike_threshold} failures in{" "}
          {data.window_minutes} minutes and clears on the next alert sweep after it answers.
        </p>
      }
    >
      {data.failing ? (
        <NoticeBox tone="stop" title={`Not answering since ${formatIST(data.since)}`}>
          {data.consecutive_failures} failed in a row. Clients see the paused banner.
        </NoticeBox>
      ) : (
        <p role="status" className="text-body font-medium text-ink">
          Answering
        </p>
      )}
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-body sm:grid-cols-[max-content_1fr]">
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
          {data.window_unreachable} no answer, {data.window_server_errors} server errors (page at{" "}
          {data.spike_threshold})
        </dd>
        <dt className="text-ink-muted">Alarm</dt>
        <dd className="text-ink">
          {data.alarm_open_since ? `Open since ${formatIST(data.alarm_open_since)}` : "Not open"}
        </dd>
        {data.recovered_at && (
          <>
            <dt className="text-ink-muted">Last outage ended</dt>
            <dd className="text-ink">{formatIST(data.recovered_at)}</dd>
          </>
        )}
      </dl>
    </Section>
  );
}
