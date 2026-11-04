"use client";

/**
 * WHAT THIS AGENT TELLS YOUR HOT-LEAD LIST ABOUT (D-904, D-967).
 *
 * Who hears is one list for the account, kept on Settings → Alerts. Here is only when: an
 * outcome that makes a lead hot always counts (shown ticked and fixed), and the owner may add
 * other outcomes, chosen answers, and telling the team during the call. The rule is per agent
 * because each agent has its own outcomes and answers.
 *
 * Writes are the owner's (`org:manage`); the server's refusal is shown in its own words.
 */

import Link from "next/link";
import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD_HINT, FIELD_LABEL, ProblemNotice, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useSaveTeamAlertRule, useTeamAlertRule, type TeamAlertRule } from "@/lib/api/teamAlerts";

export function TeamAlertsPanel({ agent }: { agent: Pick<Agent, "id"> }) {
  const { session, href } = useClientRealm();
  const rule = useTeamAlertRule(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change who hears about hot leads");

  if (rule.isLoading) return <Skeleton rows={4} />;
  if (rule.error || !rule.data) {
    return (
      <ProblemNotice
        error={rule.error ?? new Error("These settings could not be read just now.")}
        onRetry={() => void rule.refetch()}
      />
    );
  }
  return (
    <div className="space-y-4">
      <p className="flex flex-wrap items-center gap-x-3 text-sm text-ink-muted">
        <span>
          {rule.data.team_addresses === 0
            ? "You hear about these. No team yet."
            : `You and ${rule.data.team_addresses} from your team hear about these.`}
        </span>
        <Link href={href(`/c/${session.orgSlug}/settings/alerts`)} className={TEXT_ACTION}>
          Who hears
        </Link>
      </p>
      <When agentId={agent.id} rule={rule.data} canWrite={write.allowed} reason={write.reason} />
    </div>
  );
}

function When({
  agentId,
  rule,
  canWrite,
  reason,
}: {
  agentId: string;
  rule: TeamAlertRule;
  canWrite: boolean;
  reason: string | null;
}) {
  const { session } = useClientRealm();
  const save = useSaveTeamAlertRule(session, agentId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [outcomes, setOutcomes] = useState<string[]>(rule.on_outcomes);
  const [fields, setFields] = useState<Record<string, string[]>>(
    Object.fromEntries(rule.on_fields.map((f) => [f.key, f.values])),
  );
  const [inCall, setInCall] = useState(rule.in_call);

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({
          on_outcomes: outcomes,
          on_fields: Object.entries(fields)
            .filter(([, values]) => values.length > 0)
            .map(([key, values]) => ({ key, values })),
          in_call: inCall,
        });
      }}
    >
      <fieldset className="space-y-1.5">
        <legend className={FIELD_LABEL}>After a call that ends as</legend>
        {rule.outcomes.map((o) => (
          <label key={o.key} className="flex items-start gap-2 text-sm text-ink touch:min-h-11 touch:py-2.5">
            <input
              type="checkbox"
              className="mt-0.5"
              disabled={!canWrite || o.hot}
              checked={o.hot || outcomes.includes(o.key)}
              onChange={() => setOutcomes(toggle(outcomes, o.key))}
            />
            <span>
              {o.label}
              {o.hot ? <span className="ml-2 text-meta text-ink-faint">Hot lead, always</span> : null}
            </span>
          </label>
        ))}
      </fieldset>

      {rule.fields.map((field) => (
        <fieldset key={field.key} className="space-y-1.5">
          <legend className={FIELD_LABEL}>After a call where &ldquo;{field.label}&rdquo; is</legend>
          {field.values.map((value) => (
            <label key={value} className="flex items-start gap-2 text-sm text-ink touch:min-h-11 touch:py-2.5">
              <input
                type="checkbox"
                className="mt-0.5"
                disabled={!canWrite}
                checked={(fields[field.key] ?? []).includes(value)}
                onChange={() => setFields({ ...fields, [field.key]: toggle(fields[field.key] ?? [], value) })}
              />
              <span>{value}</span>
            </label>
          ))}
        </fieldset>
      ))}

      <label className="flex items-start gap-2 text-sm text-ink touch:min-h-11 touch:py-2.5">
        <input type="checkbox" className="mt-0.5" disabled={!canWrite} checked={inCall} onChange={(event) => setInCall(event.target.checked)} />
        <span>
          Tell the team during the call, too
          {inCall && rule.in_call && !rule.in_call_live ? (
            <span className="block text-meta text-warn">Off until a team address is confirmed.</span>
          ) : null}
        </span>
      </label>
      <p className={FIELD_HINT}>The agent tells the caller it has done so.</p>

      {save.error ? <ProblemNotice error={save.error} /> : null}
      <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Saved" disabled={!canWrite} title={reason ?? undefined}>
        Save
      </ActionButton>
    </form>
  );
}
