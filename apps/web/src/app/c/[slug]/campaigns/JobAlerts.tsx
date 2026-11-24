"use client";

/**
 * ALERTS ON A CAMPAIGN OR AN INBOUND LINE (D-1040): which of its calls tell you and your team
 * after they end. Exactly what is ticked: no outcome is fixed on, because a business's best
 * outcome is not always a sale ("App installed"). Until the owner saves, the server sends every
 * positive outcome of the agent ticked (`saved` false). The answers are the job's own "What it
 * notes" details, so they sit beside that card on the same page. Who hears is Settings → Alerts;
 * messaging the team during a call is the agent's own switch.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useJobTeamAlert, useSaveJobTeamAlert, type AlertJobKind, type JobTeamAlert } from "@/lib/api/teamAlerts";

import { Group, Tick, WhoHears, jobAlertsAnchor } from "../agents/panels/teamAlerts";
import { FoldSection } from "./FoldSection";

const NOUN: Record<AlertJobKind, string> = { campaign: "campaign", line: "line" };

export function JobAlerts({ kind, jobId }: { kind: AlertJobKind; jobId: string }) {
  const { session } = useClientRealm();
  const rule = useJobTeamAlert(session, kind, jobId);
  const write = useWriteAccess(session, "org:manage", "change which calls you are alerted about");
  return (
    <FoldSection
      id={jobAlertsAnchor(kind)}
      title="Alerts"
      tone="settings"
      hint="Which calls you and your team hear about."
      info={`Only this ${NOUN[kind]}'s calls. Who hears is set once, on Settings, Alerts.`}
    >
      {rule.error != null && <ProblemNotice error={rule.error} onRetry={() => void rule.refetch()} />}
      {!rule.data && rule.error == null && <Skeleton rows={3} label="Loading alerts" />}
      {rule.data && (
        <div className="space-y-6">
          <WhoHears team={rule.data.team_addresses} />
          <AlertsForm
            key={`${rule.data.on_outcomes.join()}|${JSON.stringify(rule.data.on_fields)}`}
            kind={kind}
            jobId={jobId}
            rule={rule.data}
            canWrite={write.allowed}
            reason={write.reason}
          />
        </div>
      )}
    </FoldSection>
  );
}

function AlertsForm({
  kind,
  jobId,
  rule,
  canWrite,
  reason,
}: {
  kind: AlertJobKind;
  jobId: string;
  rule: JobTeamAlert;
  canWrite: boolean;
  reason: string | null;
}) {
  const { session } = useClientRealm();
  const save = useSaveJobTeamAlert(session, kind, jobId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [outcomes, setOutcomes] = useState<string[]>(rule.on_outcomes);
  const [fields, setFields] = useState<Record<string, string[]>>(
    Object.fromEntries(rule.on_fields.map((f) => [f.key, f.values])),
  );
  const toggle = (list: string[], value: string, on: boolean) =>
    on ? [...list.filter((v) => v !== value), value] : list.filter((v) => v !== value);
  const us = rule.team_addresses === 0 ? "me" : "us";

  if (rule.outcomes.length === 0 && rule.fields.length === 0) {
    return <p className="text-sm text-ink-muted">Nothing to choose yet. Add outcomes or details first.</p>;
  }
  return (
    <form
      noValidate
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({
          on_outcomes: outcomes,
          on_fields: Object.entries(fields)
            .filter(([, values]) => values.length > 0)
            .map(([key, values]) => ({ key, values })),
        });
      }}
    >
      {rule.outcomes.length > 0 ? (
        <Group legend={`Tell ${us} after a call that ends with`}>
          {rule.outcomes.map((o) => (
            <Tick
              key={o.key}
              disabled={!canWrite}
              checked={outcomes.includes(o.key)}
              onChange={(on) => setOutcomes(toggle(outcomes, o.key, on))}
            >
              {o.label}
              {o.goal ? <span className="ml-2 text-meta leading-none text-ink-faint">Goal</span> : null}
            </Tick>
          ))}
        </Group>
      ) : null}

      {rule.fields.map((field) => (
        <Group key={field.key} legend={<>Tell {us} after a call where &ldquo;{field.label}&rdquo; is</>}>
          {field.values.map((value) => (
            <Tick
              key={value}
              disabled={!canWrite}
              checked={(fields[field.key] ?? []).includes(value)}
              onChange={(on) => setFields({ ...fields, [field.key]: toggle(fields[field.key] ?? [], value, on) })}
            >
              {value}
            </Tick>
          ))}
        </Group>
      ))}

      {save.error ? <ProblemNotice error={save.error} /> : null}
      <ActionButton
        type="submit"
        variant="primary-sm"
        status={feedback.status}
        successLabel="Saved"
        disabled={!canWrite}
        title={reason ?? undefined}
      >
        Save alerts
      </ActionButton>
    </form>
  );
}
