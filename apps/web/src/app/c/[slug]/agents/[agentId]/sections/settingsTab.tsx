"use client";

/**
 * SETTINGS — the parts an owner sets once and rarely revisits (D-825): how calls are
 * handled, the model, what the agent is, where the business-wide leads and calling hours
 * are, and deleting it. Before D-825 these were four menu entries (Call handling, Model,
 * Leads & hours, Settings); each keeps its own heading here.
 *
 * Order is by how often each is changed. Call handling (length, pauses, hand-over, memory)
 * is tuned after real calls; the model and what the agent is are set once. Delete is
 * foreground, not disclosed, because it is rare but high-consequence (UX-DOCTRINE §3); while
 * the agent is taking calls it cannot be deleted, and the notice carries the one move that
 * changes that.
 *
 * Each panel declares its own copilot surface; the tab's `CopilotSurfaceScope` merges them, so
 * the assistant sees call handling, the model and what the agent is together.
 */

import Link from "next/link";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, ProblemNotice } from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { CopilotSurfaceScope } from "@/lib/copilot/registry";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentLifecycle } from "../../AgentLifecycle";
import { AgentModel } from "../../AgentModel";
import { CallHandlingSection } from "./deliverySections";

/** The anchor a test result's "Open call handling" lands on. */
export const CALL_HANDLING_ANCHOR = "call-handling";

export function SettingsTab({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const canDelete = movesFor(agent.status).includes("archive");
  return (
    <CopilotSurfaceScope
      route="/c/{slug}/agents/{id}"
      title={`Agent: settings (${agent.name})`}
      realm="client"
      facts={[{ key: "agent_id", label: "Agent id", value: agent.id }]}
    >
      <div className="max-w-3xl space-y-12">
        <div id={CALL_HANDLING_ANCHOR} className="scroll-mt-24">
          <Section
            headingLevel={3}
            title="How it handles calls"
            description="How long a call may run, when it replies, putting callers through to a person, and remembering callers."
          >
            <CallHandlingSection agent={agent} />
          </Section>
        </div>

        <Section headingLevel={3} title="Model">
          <AgentModel agent={agent} slug={slug} />
        </Section>

        <Section
          headingLevel={3}
          title="What it is"
          description="Its name, which way its calls go, and the language it speaks. Changing what it does can stop it answering your numbers."
        >
          <AgentIdentity agent={agent} />
        </Section>

        <Section
          headingLevel={3}
          title="Leads and calling hours"
          description="Where leads come from and when your agents may call them are set once for your whole business."
          action={
            <Link href={href(`/c/${slug}/lead-sources`)} className={TEXT_ACTION}>
              Open leads and hours
            </Link>
          }
        />

        <Section headingLevel={3} title="Delete this agent">
          {canDelete ? <AgentLifecycle agent={agent} only={["archive"]} /> : <SwitchOffFirst agent={agent} />}
        </Section>
      </div>
    </CopilotSurfaceScope>
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
