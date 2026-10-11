"use client";

/**
 * SETTINGS: what the agent is, and deleting it. Plain headed sections like every other part
 * of the agent page (REDESIGN-2), not closed cards: each is short, and its controls show the
 * facts they edit. The model has its own section.
 *
 * Delete is foreground, not disclosed: it is rare but high-consequence. While the agent is
 * taking calls it cannot be deleted, and the notice carries the one move that changes that.
 */

import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, ProblemNotice } from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentLifecycle } from "../../AgentLifecycle";

export function AdvancedSection({ agent }: { agent: Agent; slug: string }) {
  const canDelete = movesFor(agent.status).includes("archive");
  return (
    <div className="space-y-10">
      <Section
        headingLevel={3}
        title="What it is"
        description="Its name, which way its calls go, and the language it speaks. Changing what it does can stop it answering your numbers."
      >
        <AgentIdentity agent={agent} />
      </Section>

      <Section headingLevel={3} title="Delete this agent">
        {canDelete ? (
          <AgentLifecycle agent={agent} only={["archive"]} />
        ) : (
          <SwitchOffFirst agent={agent} />
        )}
      </Section>
    </div>
  );
}

/** Why there is no delete yet, with the switch-off beside it. */
function SwitchOffFirst({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const move = useAgentLifecycle(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  const canSwitchOff = movesFor(agent.status).includes("deactivate");
  return (
    <div className="space-y-3">
      {move.error != null && <ProblemNotice error={move.error} />}
      <NoticeBox
        tone="neutral"
        action={
          canSwitchOff ? (
            <button
              type="button"
              className={TEXT_ACTION}
              disabled={!write.allowed || move.isPending}
              title={write.reason ?? undefined}
              onClick={() => move.mutate("deactivate")}
            >
              {move.isPending ? "Switching off…" : "Switch off"}
            </button>
          ) : undefined
        }
      >
        It is taking calls. Switch it off before you delete it.
      </NoticeBox>
    </div>
  );
}
