"use client";

/**
 * ALERTS FROM AN AGENT (D-904, D-967, D-1040).
 *
 * Who hears is one list for the account, kept on Settings → Alerts. Which calls alert after
 * they end belongs to each campaign and Inbound line (`campaigns/JobAlerts`), because what a call
 * notes is its job's list (D-1028) and the same detail on two campaigns can mean two things. The
 * agent keeps only what is truly its own: whether it may message the team while a caller is on
 * the line, which every campaign's and line's calls in its voice carry (founder, 24 Nov 2026).
 * Below it, one link per job to that job's alerts.
 *
 * Writes are the owner's (`org:manage`); the server's refusal is shown in its own words.
 */

import Link from "next/link";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { FIELD_LABEL, ProblemNotice, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import {
  useAgentTeamAlert,
  useSaveAgentTeamAlert,
  type AgentTeamAlert,
  type AlertJobKind,
} from "@/lib/api/teamAlerts";

type AlertAgent = Pick<Agent, "id" | "name">;

/** Where links to an agent's alerts land (`?section=settings#…`). */
export const TEAM_ALERTS_ANCHOR = "team-alerts";

/** The id of a campaign's or line's Alerts section on its own page. */
export function jobAlertsAnchor(kind: AlertJobKind): string {
  return kind === "campaign" ? "campaign-alerts" : "line-alerts";
}

/** A campaign's or line's own page, at its Alerts section. */
export function jobAlertsPath(slug: string, kind: AlertJobKind, jobId: string): string {
  const page = kind === "campaign" ? `/c/${slug}/campaigns/${jobId}` : `/c/${slug}/inbound/${jobId}`;
  return `${page}#${jobAlertsAnchor(kind)}`;
}

/** Who hears, and where that is changed. */
export function WhoHears({ team }: { team: number }) {
  const { session, href } = useClientRealm();
  return (
    <p className="flex flex-wrap items-center gap-x-3 text-sm text-ink-muted">
      <span>
        {team === 0 ? "Only you hear these. No one from your team yet." : `You and ${team} from your team hear these.`}
      </span>
      <Link href={href(`/c/${session.orgSlug}/settings/alerts`)} className={TEXT_ACTION}>
        Who hears
      </Link>
    </p>
  );
}

export function TeamAlertsPanel({ agent }: { agent: AlertAgent }) {
  const { session } = useClientRealm();
  const rule = useAgentTeamAlert(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change which calls you are alerted about");
  const loaded = rule.data != null;
  // The agent page draws this only after its data loads, so the browser's own jump to a link
  // naming it found no target: scroll to it once the rule is in.
  useEffect(() => {
    if (loaded && window.location.hash === `#${TEAM_ALERTS_ANCHOR}`) {
      document.getElementById(TEAM_ALERTS_ANCHOR)?.scrollIntoView?.({ block: "start" });
    }
  }, [loaded]);

  if (rule.isLoading) return <Skeleton rows={3} />;
  if (rule.error || !rule.data) {
    return (
      <ProblemNotice
        error={rule.error ?? new Error("These settings could not be read just now.")}
        onRetry={() => void rule.refetch()}
      />
    );
  }
  return (
    <div className="space-y-6">
      <WhoHears team={rule.data.team_addresses} />
      <InCall agent={agent} rule={rule.data} canWrite={write.allowed} reason={write.reason} />
      <JobLinks jobs={rule.data.jobs} agentName={agent.name} />
    </div>
  );
}

/**
 * One tick box. The whole row is the label, so the tap target is the row, not the 16px box;
 * every row has the same height so the list reads as one column, and the box sits on the
 * first line of text when a label wraps.
 */
export function Tick({
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

export function Group({ legend, children }: { legend: ReactNode; children: ReactNode }) {
  return (
    <fieldset>
      <legend className={`${FIELD_LABEL} mb-1`}>{legend}</legend>
      {children}
    </fieldset>
  );
}

function InCall({
  agent,
  rule,
  canWrite,
  reason,
}: {
  agent: AlertAgent;
  rule: AgentTeamAlert;
  canWrite: boolean;
  reason: string | null;
}) {
  const { session } = useClientRealm();
  const save = useSaveAgentTeamAlert(session, agent.id);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [inCall, setInCall] = useState(rule.in_call);
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({ in_call: inCall });
      }}
    >
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
      <ActionButton
        type="submit"
        variant="primary-sm"
        status={feedback.status}
        successLabel="Saved"
        disabled={!canWrite || inCall === rule.in_call}
        title={reason ?? undefined}
      >
        Save
      </ActionButton>
    </form>
  );
}

/** One link per campaign and line: their after-call alerts are set on their own pages. */
function JobLinks({ jobs, agentName }: { jobs: AgentTeamAlert["jobs"]; agentName: string }) {
  const { session, href } = useClientRealm();
  return (
    <Group legend="After the call">
      {jobs.length === 0 ? (
        <p className="text-sm text-ink-muted">{`Set on each campaign and Inbound line. None uses ${agentName} yet.`}</p>
      ) : (
        <>
          <p className="mb-2 text-sm text-ink-muted">Set on each campaign and Inbound line.</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-2">
            {jobs.map((job) => (
              <li key={`${job.kind}:${job.id}`}>
                <Link href={href(jobAlertsPath(session.orgSlug, job.kind, job.id))} className={TEXT_ACTION}>
                  <span className="text-ink-muted">{job.kind === "campaign" ? "Campaign" : "Inbound line"}</span>{" "}
                  {job.name}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </Group>
  );
}
