"use client";

import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import {
  CALLER_ID_COPY,
  CARRIER_LABEL,
  CONCURRENCY_COPY,
  LINE_KIND_LABEL,
  OUTCOME_COPY,
  STATUS_COPY,
  modeSummary,
} from "@/components/forwarding/copy";
import { Fact, ProblemNotice, Skeleton, formatIST, formatPhone } from "@/components/ui";
import { useAdminForwarding } from "@/lib/api/forwarding";

/**
 * THE CLIENT'S EXISTING NUMBER, as an operator sees it (D-746): the published number, how it
 * forwards, whether the last test found it working, and the two findings a test records.
 * Read-only; the client runs the test from their own account.
 */
/** Two facts a row on a phone, three on a wider screen: label over a short value. */
const FACT_GRID = "grid grid-cols-2 gap-x-4 gap-y-3 border-y border-line py-4 sm:grid-cols-3";

export function ForwardingCard({ tenantId }: { tenantId: string }) {
  const forwarding = useAdminForwarding(tenantId);
  const data = forwarding.data;
  return (
    <Section
      title="Existing number"
      description="The number the client already publishes, forwarded to their Calevate number."
      info="The client sets the forward on their own phone. The test call rings it from our side and records which number arrived and whether two calls at once got through."
    >
      {forwarding.isLoading ? (
        <Skeleton rows={3} label="Loading the client's existing number" />
      ) : forwarding.error || !data ? (
        <ProblemNotice error={forwarding.error ?? new Error("The client's existing number did not load.")} onRetry={() => void forwarding.refetch()} />
      ) : (
        <div className="space-y-4">
          {data.lines.length === 0 ? (
            <p className="text-body text-ink-muted">No existing number set up.</p>
          ) : (
            data.lines.map((line) => {
              const status = STATUS_COPY[line.status];
              return (
                <dl key={line.id} className={FACT_GRID}>
                  <Fact label="Published number">
                    <span className="font-mono tabular-nums">{formatPhone(line.e164)}</span>
                  </Fact>
                  <Fact label="Line">
                    {line.line_kind === "mobile"
                      ? `${LINE_KIND_LABEL.mobile} · ${CARRIER_LABEL[line.carrier]}`
                      : LINE_KIND_LABEL[line.line_kind]}
                  </Fact>
                  <Fact label="Forwards to">
                    {line.calevate_number_e164 ? (
                      <span className="font-mono tabular-nums">{formatPhone(line.calevate_number_e164)}</span>
                    ) : (
                      "None"
                    )}
                  </Fact>
                  <Fact label="Forwarding">
                    <StatusPill tone={status.tone}>{status.text}</StatusPill>
                  </Fact>
                  <Fact label="Mode">{modeSummary(line.mode, line.ring_seconds)}</Fact>
                  <Fact label="Last test">
                    {line.last_tested_at
                      ? `${formatIST(line.last_tested_at)}${line.last_test_outcome ? ` · ${OUTCOME_COPY[line.last_test_outcome].text}` : ""}`
                      : "Never tested"}
                  </Fact>
                  <Fact label="Caller ID">
                    {line.caller_id_finding ? CALLER_ID_COPY[line.caller_id_finding] : "Not known yet"}
                  </Fact>
                  <Fact label="Two calls at once">
                    {line.concurrency_finding ? CONCURRENCY_COPY[line.concurrency_finding] : "Not known yet"}
                  </Fact>
                  {line.quiet_since && <Fact label="Quiet since">{formatIST(line.quiet_since)}</Fact>}
                </dl>
              );
            })
          )}
          <dl className={FACT_GRID}>
            <Fact label="Save-our-number message">
              {data.save_number_enabled ? `On · ${data.save_number_sent} sent` : "Off"}
            </Fact>
          </dl>
        </div>
      )}
    </Section>
  );
}
