"use client";

/**
 * SETTINGS — how the agent sounds and behaves wherever it calls for: its voice, what it
 * notes down, how calls are handled, the model, what the agent is, where the business-wide
 * leads and calling hours are, and deleting it. Voice and What it notes were tabs of their
 * own until the agent page became four tabs (D-997, founder 16 Nov 2026); each keeps its own
 * heading here.
 *
 * Order is by how often each is changed. The voice is picked and re-picked while an owner
 * gets to know the agent, and what it notes changes with the business; call handling
 * (length, pauses, hand-over, memory) is tuned after real calls; the model and what the
 * agent is are set once. Delete is
 * foreground, not disclosed, because it is rare but high-consequence (UX-DOCTRINE §3); while
 * the agent is taking calls it cannot be deleted, and the notice carries the one move that
 * changes that.
 *
 * Each panel declares its own copilot surface; the tab's `CopilotSurfaceScope` merges them, so
 * the assistant sees the voice, call handling, the model and what the agent is together.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { useActionFeedback, type ActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { NoticeBox, SECONDARY_BUTTON_SM } from "@/components/ui";
import { movesFor } from "@/lib/agentState";
import { useAgentLifecycle, type Agent, type LifecycleMove } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { CopilotSurfaceScope } from "@/lib/copilot/registry";

import { AgentIdentity } from "../../AgentIdentity";
import { AgentLifecycle, LifecycleError } from "../../AgentLifecycle";
import { AgentModel } from "../../AgentModel";
import { ExtractionList } from "../../panels/extraction";
import { TEAM_ALERTS_ANCHOR, TeamAlertsPanel } from "../../panels/teamAlerts";
import { CallHandlingSection, VoiceSection } from "./deliverySections";

/** The anchor a test result's "Open call handling" lands on. */
export const CALL_HANDLING_ANCHOR = "call-handling";

export function SettingsTab({
  agent,
  slug,
  leadsLink,
}: {
  agent: Agent;
  slug: string;
  /** The link to the Leads table that What it notes names. */
  leadsLink: ReactNode;
}) {
  const { href } = useClientRealm();
  const canDelete = movesFor(agent.status).includes("archive");
  // The tab, not the notice, holds the switch-off: the move waits for the agent to reload
  // switched off, and by then the notice has given way to the delete panel and would take
  // its feedback with it.
  const session = useClientSession();
  const switchOff = useAgentLifecycle(session, agent.id);
  const switchOffFeedback = useActionFeedback(switchOff, {
    errorDisplay: "inline",
    successToast: "Switched off. You can delete it now.",
  });
  return (
    <CopilotSurfaceScope
      route="/c/{slug}/agents/{id}"
      title={`Agent: settings (${agent.name})`}
      realm="client"
      facts={[{ key: "agent_id", label: "Agent id", value: agent.id }]}
    >
      <div className="space-y-12">
        <Section headingLevel={3} title="Voice">
          <VoiceSection agent={agent} />
        </Section>

        <ExtractionList agent={agent} leadsHref={leadsLink} />

        <div id={CALL_HANDLING_ANCHOR} className="scroll-mt-24">
          {/* Each section: a title and one short line. The fuller reason, where one is
              worth having, is behind the ⓘ (critique-information-density). */}
          <Section
            headingLevel={3}
            title="How it handles calls"
            description="Call length, pauses, handing over, memory."
          >
            <CallHandlingSection agent={agent} />
          </Section>
        </div>

        <div id={TEAM_ALERTS_ANCHOR} className="scroll-mt-24">
          <Section
            headingLevel={3}
            title={`Alerts from ${agent.name}`}
            description={`Which calls ${agent.name} tells you and your team about.`}
            info={<p>Who hears is set once, on Settings, Alerts. Its campaigns&apos; and lines&apos; own details are here too.</p>}
          >
            <TeamAlertsPanel agent={agent} />
          </Section>
        </div>

        <Section headingLevel={3} title="Model">
          <AgentModel agent={agent} slug={slug} />
        </Section>

        <Section
          headingLevel={3}
          title="What it is"
          description="Name, call direction and language."
          info={<p>Changing which way its calls go can stop it answering your numbers.</p>}
        >
          <AgentIdentity agent={agent} />
        </Section>

        <Section
          headingLevel={3}
          title="Leads and calling hours"
          description="Set once for your whole business."
          action={
            <Link href={href(`/c/${slug}/lead-sources`)} className={TEXT_ACTION}>
              Open leads and hours
            </Link>
          }
        />

        <Section headingLevel={3} title="Delete this agent">
          {canDelete ? <AgentLifecycle agent={agent} only={["archive"]} /> : <SwitchOffFirst agent={agent} move={switchOff} moveFeedback={switchOffFeedback} />}
        </Section>
      </div>
    </CopilotSurfaceScope>
  );
}

/** Why there is no delete yet, with the switch-off beside it. */
function SwitchOffFirst({
  agent,
  move,
  moveFeedback,
}: {
  agent: Agent;
  move: ReturnType<typeof useAgentLifecycle>;
  moveFeedback: ActionFeedback<LifecycleMove>;
}) {
  const session = useClientSession();
  const write = useWriteAccess(session, "org:manage", "change whether this agent is working");
  const canSwitchOff = movesFor(agent.status).includes("deactivate");
  return (
    <div className="space-y-3">
      <LifecycleError error={move.error} />
      <NoticeBox
        tone="neutral"
        action={
          canSwitchOff ? (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={!write.allowed}
              aria-disabled={moveFeedback.status === "pending" || undefined}
              aria-busy={moveFeedback.status === "pending" || undefined}
              title={write.reason ?? undefined}
              onClick={() => {
                if (moveFeedback.status !== "pending") moveFeedback.run("deactivate");
              }}
            >
              {moveFeedback.status === "pending"
                ? "Switching off…"
                : moveFeedback.status === "error"
                  ? "Try switching off again"
                  : "Switch off"}
            </button>
          ) : undefined
        }
      >
        It is taking calls. Switch it off first.
      </NoticeBox>
    </div>
  );
}
