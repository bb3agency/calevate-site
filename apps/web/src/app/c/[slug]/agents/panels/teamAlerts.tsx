"use client";

/**
 * WHICH CALLS THIS AGENT TELLS YOU AND YOUR TEAM ABOUT (D-904, D-967).
 *
 * Who hears is one list for the account, kept on Settings → Alerts. Here is only when, and it
 * is exactly what is ticked: no outcome is fixed on, because a business's best outcome is not
 * always a sale ("App installed") and the owner must be able to switch any of them off. Until
 * the owner saves, the server sends every positive outcome ticked (`rule.saved` false). The
 * rule is per agent because each agent has its own outcomes and answers.
 *
 * Writes are the owner's (`org:manage`); the server's refusal is shown in its own words.
 */

import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD_LABEL, ProblemNotice, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useSaveTeamAlertRule, useTeamAlertRule, type TeamAlertRule } from "@/lib/api/teamAlerts";

type AlertAgent = Pick<Agent, "id" | "name">;

export function TeamAlertsPanel({ agent }: { agent: AlertAgent }) {
  const { session, href } = useClientRealm();
  const rule = useTeamAlertRule(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change which calls you are alerted about");

  if (rule.isLoading) return <Skeleton rows={4} />;
  if (rule.error || !rule.data) {
    return (
      <ProblemNotice
        error={rule.error ?? new Error("These settings could not be read just now.")}
        onRetry={() => void rule.refetch()}
      />
    );
  }
  const team = rule.data.team_addresses;
  return (
    <div className="space-y-6">
      <p className="flex flex-wrap items-center gap-x-3 text-sm text-ink-muted">
        <span>
          {team === 0
            ? "Only you hear these. No one from your team yet."
            : `You and ${team} from your team hear these.`}
        </span>
        <Link href={href(`/c/${session.orgSlug}/settings/alerts`)} className={TEXT_ACTION}>
          Who hears
        </Link>
      </p>
      <When agent={agent} rule={rule.data} canWrite={write.allowed} reason={write.reason} />
    </div>
  );
}

/**
 * One tick box. The whole row is the label, so the tap target is the row, not the 16px box;
 * every row has the same height so the list reads as one column, and the box sits on the
 * first line of text when a label wraps.
 */
function Tick({
  checked,
  disabled,
  onChange,
  children,
  hint,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
  children: ReactNode;
  hint?: ReactNode;
}) {
  const hintId = useId();
  return (
    <div>
      <label className="flex items-start gap-3 py-1.5 text-sm text-ink touch:min-h-11 touch:py-3">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 shrink-0 rounded border-line accent-brand-strong touch:-mt-0.5 touch:h-6 touch:w-6"
          disabled={disabled}
          checked={checked}
          aria-describedby={hint ? hintId : undefined}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="min-w-0">{children}</span>
      </label>
      {hint ? (
        <p id={hintId} className="-mt-1 max-w-prose pb-1.5 pl-7 text-xs text-ink-muted touch:-mt-2 touch:pl-9">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function Group({ legend, children }: { legend: ReactNode; children: ReactNode }) {
  return (
    <fieldset>
      <legend className={`${FIELD_LABEL} mb-1`}>{legend}</legend>
      {children}
    </fieldset>
  );
}

function When({
  agent,
  rule,
  canWrite,
  reason,
}: {
  agent: AlertAgent;
  rule: TeamAlertRule;
  canWrite: boolean;
  reason: string | null;
}) {
  const { session } = useClientRealm();
  const save = useSaveTeamAlertRule(session, agent.id);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [outcomes, setOutcomes] = useState<string[]>(rule.on_outcomes);
  const [fields, setFields] = useState<Record<string, string[]>>(
    Object.fromEntries(rule.on_fields.map((f) => [f.key, f.values])),
  );
  const [inCall, setInCall] = useState(rule.in_call);

  const toggle = (list: string[], value: string, on: boolean) =>
    on ? [...list.filter((v) => v !== value), value] : list.filter((v) => v !== value);
  const us = rule.team_addresses === 0 ? "me" : "us";

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
          in_call: inCall,
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

      <Group legend="During the call">
        <Tick
          disabled={!canWrite}
          checked={inCall}
          onChange={setInCall}
          hint={
            inCall && rule.in_call && !rule.in_call_live ? (
              <span className="text-warn">Off until someone on your team confirms.</span>
            ) : (
              <>
                {`If ${agent.name} can't help, your team gets the caller's details.`}{" "}
                {`${agent.name} tells the caller someone will contact them.`}
              </>
            )
          }
        >
          Message my team while the caller is on the line
        </Tick>
      </Group>

      {save.error ? <ProblemNotice error={save.error} /> : null}
      <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Saved" disabled={!canWrite} title={reason ?? undefined}>
        Save
      </ActionButton>
    </form>
  );
}
