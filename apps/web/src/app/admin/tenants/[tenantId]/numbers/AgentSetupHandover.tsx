"use client";

/**
 * HAND AGENTS' SETUPS TO THEIR WORK (D-1019).
 *
 * An agent published before D-1019 still holds an engine agent of its own, and that may be
 * what a number or a campaign rings. The job behind this section gives each one to the line
 * or campaign that uses it, retires it when nothing does, or holds it with a reason.
 *
 * "Run it" appears only after a dry run in this page view: the real run changes what answers
 * the client's numbers, so the operator sees the per-agent plan first. After a real run the
 * plan is cleared, and the next real run needs a fresh dry run.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { MonoValue, NoticeBox, ProblemNotice } from "@/components/ui";
import { useTenant, useTenantAgents, useTenantCampaigns, viewAsSession } from "@/lib/api/admin";
import {
  useAgentEngineRetirementPlan,
  useAgentEngineRetirementRun,
  type AgentEngineRetirement,
  type AgentEngineRetirementRun,
} from "@/lib/api/engineWorkspaces";
import { useInboundLines } from "@/lib/api/inboundLines";
import { lookup } from "@/lib/lookup";

/** `engine_retirement.py`'s reason codes, and the refusal codes it records as `waiting`. */
const REASON_COPY: Record<string, string> = {
  several_uses: "more than one line or campaign uses it",
  number_without_line: "a number rings it directly, not through a line",
  developer_workspace_in_use: "it is still in the platform account and something uses it",
  ref_changed: "its setup changed while this ran; run again",
  platform_maintenance: "the platform is in maintenance",
  kb_publish_in_progress: "a knowledge publish is in progress",
};

type Names = {
  agent: (id: string) => string | undefined;
  line: (id: string) => string | undefined;
  campaign: (id: string) => string | undefined;
};

function reasonPhrase(reason: string | null) {
  if (!reason) return "no reason given";
  return lookup(REASON_COPY, reason) ?? reason;
}

function outcomePhrase(row: AgentEngineRetirement, names: Names): string {
  switch (row.outcome) {
    case "adopted_line": {
      const name = row.holder_id ? names.line(row.holder_id) : undefined;
      return name ? `Its line ${name} takes over its setup` : "Its line takes over its setup";
    }
    case "adopted_campaign": {
      const name = row.holder_id ? names.campaign(row.holder_id) : undefined;
      return name ? `Campaign ${name} takes over its setup` : "A campaign takes over its setup";
    }
    case "retired":
      return "Setup removed";
    case "held":
      return `Held: ${reasonPhrase(row.reason)}`;
    case "waiting":
      return `Waiting: ${reasonPhrase(row.reason)}`;
  }
}

function testsPhrase(count: number): string {
  if (count === 0) return "None";
  return count === 1 ? "Ends 1 running script test" : `Ends ${count} running script tests`;
}

function RetirementTable({
  run,
  names,
  caption,
}: {
  run: AgentEngineRetirementRun;
  names: Names;
  caption: string;
}) {
  if (run.agents.length === 0) {
    return <p className="text-body text-ink-muted">No agent holds a setup of its own. Nothing to do.</p>;
  }
  return (
    <table className="w-full text-left text-meta">
      <caption className="sr-only">{caption}</caption>
      <thead className="text-ink-muted">
        <tr>
          <th className="py-1 pr-3 font-medium">Agent</th>
          <th className="py-1 pr-3 font-medium">Outcome</th>
          <th className="py-1 font-medium">Tests</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line border-y border-line">
        {run.agents.map((row) => {
          const name = names.agent(row.agent_id);
          return (
            <tr key={row.agent_id}>
              <td className="py-1.5 pr-3 align-top text-ink">
                {name ?? <MonoValue className="[overflow-wrap:anywhere]">{row.agent_id}</MonoValue>}
              </td>
              <td className="py-1.5 pr-3 align-top text-ink">{outcomePhrase(row, names)}</td>
              <td className="py-1.5 align-top text-ink-muted">
                {testsPhrase(row.experiments_concluded.length)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function AgentSetupHandover({ tenantId, canWrite }: { tenantId: string; canWrite: boolean }) {
  const tenant = useTenant(tenantId);
  const slug = tenant.data?.slug ?? "";
  const plan = useAgentEngineRetirementPlan(tenantId);
  const run = useAgentEngineRetirementRun(tenantId);
  const planFeedback = useActionFeedback(plan, { errorDisplay: "inline" });
  const runFeedback = useActionFeedback(run, { errorDisplay: "inline" });
  const [confirming, setConfirming] = useState(false);

  // Names are read only once there is a result to name: the agents are usually cached by the
  // screen already, the lines and campaigns are not.
  const shown = run.data ?? plan.data;
  const agents = useTenantAgents(slug);
  const lines = useInboundLines(viewAsSession(slug), Boolean(slug && shown));
  const campaigns = useTenantCampaigns(shown ? slug : "");
  const names: Names = {
    agent: (id) => agents.data?.find((a) => a.id === id)?.name,
    line: (id) => lines.data?.find((l) => l.id === id)?.name,
    campaign: (id) => campaigns.data?.find((c) => c.id === id)?.name,
  };

  const clientName = tenant.data?.name ?? "this client";

  return (
    <div className="space-y-2">
      <h3 className="text-body font-semibold text-ink">Hand agents&apos; setups to their work</h3>
      <p className="text-body text-ink-muted">
        Each agent that still holds a calling setup of its own gives it to the one line or
        campaign that uses it, or loses it when nothing does. Try a dry run first.
      </p>
      <div className="flex flex-wrap gap-2">
        <ActionButton
          variant="secondary-sm"
          status={planFeedback.status}
          pendingLabel="Checking…"
          disabled={!canWrite}
          onClick={() => {
            run.reset();
            plan.mutate();
          }}
        >
          Dry run
        </ActionButton>
        {plan.data && (
          <ActionButton
            variant="secondary-sm"
            disabled={!canWrite || plan.data.agents.length === 0}
            onClick={() => {
              run.reset();
              setConfirming(true);
            }}
          >
            Run it
          </ActionButton>
        )}
      </div>
      <ProblemNotice error={plan.error} />

      {run.data ? (
        <div className="space-y-2">
          <NoticeBox tone="ok">Done. This is what happened to each agent.</NoticeBox>
          <RetirementTable run={run.data} names={names} caption="What the run did, per agent" />
        </div>
      ) : plan.data ? (
        <RetirementTable run={plan.data} names={names} caption="What a run would do, per agent" />
      ) : null}

      {confirming && (
        <ConfirmDialog
          title={`Hand agents' setups to their work for ${clientName}`}
          confirmLabel="Run it"
          pendingLabel="Running…"
          status={runFeedback.status}
          error={run.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            run.mutate(undefined, {
              onSuccess: () => {
                setConfirming(false);
                plan.reset();
              },
            })
          }
        >
          <p>
            For {clientName}, each agent&apos;s own setup moves to the line or campaign that uses
            it, as the dry run showed. Its numbers keep ringing the same setup. An agent nothing
            uses loses it. Running script tests on these agents end, keeping the original script.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
