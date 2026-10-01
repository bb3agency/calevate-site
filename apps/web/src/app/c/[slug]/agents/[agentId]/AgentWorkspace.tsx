"use client";

/**
 * ONE AGENT'S WORKSPACE — a settings layout (D-657).
 *
 * A slim header (name, live state, the one action that moves the agent forward), then a
 * section menu: Overview · Script · Voice · Call handling · Captured details · Knowledge ·
 * Advanced. Each section is short and complete on its own and is visited, not read in
 * sequence, which is the case the doctrine allows a section switch for.
 *
 * ## What may not move out of Overview
 *
 * The truthful-answer guarantee, the two opening-notice switches under it, and the
 * publish state. Overview is the section that opens first, so none of them is ever behind a
 * section switch (doctrine §8 rule 7). The header carries the publish state on every
 * section.
 *
 * ## Nothing was removed
 *
 * Every control the stacked workspace had is still here and still writes to the same
 * endpoint; what changed is where it sits. Sections live in `?section=` so the screen's
 * queries stay mounted between them, and a section with unsaved edits asks before it is
 * left (`SettingsLayout` reads `useUnsavedGuard`).
 *
 * ## A deleted agent is a different screen
 *
 * Read-only, with one move: bring it back. The history is the reason the server archives
 * rather than erases, so what it captured, what it was and its model stay on the page as
 * a record; every control that would write is gone.
 */

import Link from "next/link";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { SettingsLayout } from "@/components/console/settingsLayout";
import { isDeleted } from "@/lib/agentState";
import { useAgent, type Agent } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { KnowledgeGaps } from "../../KnowledgeGaps";
import { AgentIdentity } from "../AgentIdentity";
import { AgentModel } from "../AgentModel";
import { ExtractionList } from "../panels/extraction";
import { TrainingPanel } from "../panels/training";
import { AdvancedSection } from "./sections/advanced";
import { AgentHeader } from "./sections/agentHeader";
import { CallHandlingSection, VoiceSection } from "./sections/deliverySections";
import { Overview } from "./sections/overview";
import { ScriptSection } from "./sections/scriptSection";

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "script", label: "Script" },
  { id: "voice", label: "Voice" },
  { id: "calls", label: "Call handling" },
  { id: "captured", label: "Captured details" },
  { id: "knowledge", label: "Knowledge" },
  { id: "advanced", label: "Advanced" },
];

/** The screen, from the route's params. Loading, failure and the agent are three branches. */
export function AgentWorkspace({ slug, agentId }: { slug: string; agentId: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const agent = useAgent(session, agentId);

  // Declared only while there is no agent: once it arrives, the mounted section's own
  // surface (e.g. the capture columns) is the one the assistant should see.
  useCopilotSurface(
    agent.data
      ? null
      : {
          route: "/c/{slug}/agents/{id}",
          title: "Agent",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agentId },
            {
              key: "state",
              label: "What is on screen",
              value: agent.error
                ? "the agent failed to load, so none of its settings are on screen"
                : "still loading",
            },
          ],
          apply: noFill,
        },
  );

  if (agent.error) {
    // The way back stays: a 404 on a bookmarked agent is when a person most needs it.
    return (
      <div className="space-y-4">
        <PageHeader back={{ href: href(`/c/${slug}/agents`), label: "All agents" }} />
        <ProblemNotice error={agent.error} onRetry={() => void agent.refetch()} />
      </div>
    );
  }
  if (agent.isLoading || !agent.data) return <Skeleton rows={8} />;
  return <AgentDetail agent={agent.data} slug={slug} />;
}

function AgentDetail({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  const leadsLink = (
    <Link
      href={href(`/c/${slug}/leads`)}
      className="font-medium underline underline-offset-2 hover:text-ink"
    >
      Leads
    </Link>
  );

  if (isDeleted(agent)) {
    return (
      <div className="space-y-8">
        <AgentHeader agent={agent} slug={slug} />
        <p className="max-w-prose text-sm text-ink-muted">
          Its script and settings are kept exactly as they were, as the record of what it did,
          and cannot be changed while it is deleted. It comes back switched off.
        </p>
        <ExtractionList agent={agent} leadsHref={leadsLink} />
        <section aria-labelledby="deleted-identity-heading">
          <h3 id="deleted-identity-heading" className="mb-2 text-[15px] font-semibold text-ink">
            What it is
          </h3>
          <AgentIdentity agent={agent} />
        </section>
        <AgentModel agent={agent} slug={slug} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AgentHeader agent={agent} slug={slug} />
      <SettingsLayout
        label="Agent settings"
        sections={SECTIONS}
        renderSection={(id) => {
          switch (id) {
            case "script":
              return <ScriptSection agent={agent} slug={slug} />;
            case "voice":
              return <VoiceSection agent={agent} />;
            case "calls":
              return <CallHandlingSection agent={agent} />;
            case "captured":
              return <ExtractionList agent={agent} leadsHref={leadsLink} />;
            case "knowledge":
              return (
                <div className="space-y-8">
                  {/* The questions it could not answer on real calls, teachable in place. */}
                  <KnowledgeGaps agentId={agent.id} />
                  <section aria-labelledby="agent-knows-heading">
                    <h3 id="agent-knows-heading" className="mb-1 text-[15px] font-semibold text-ink">
                      What it knows
                    </h3>
                    <TrainingPanel agent={agent} />
                  </section>
                </div>
              );
            case "advanced":
              return <AdvancedSection agent={agent} slug={slug} />;
            default:
              return <Overview agent={agent} slug={slug} />;
          }
        }}
      />
    </div>
  );
}
